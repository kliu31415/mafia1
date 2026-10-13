"""The day phase: speaking budget, chat turns, nominations and simultaneous votes."""

import json
import math
import re
from typing import Any

from llm import Model
from players import (LAST_WILL_SCHEMA, blank, VOTE_SCHEMA, Players, cap_words, day_turn_schema, name_enum, nullable,
                     obj, truncate_words, word_count)
from events import CHAT, CLAIM, DEATH, NOMINATION, PHASE, PM, VOTE
from roles import RoleLogic, logic
from roles.base import DayAction
from state import Game, Player, majority
from traits import LOGIC as TRAIT_LOGIC, fixed_trial_vote, trait_logic


# Speaking budget. A message costs MESSAGE_BASE_COST + round_multiplier * length_cost(words), times
# PRIVATE_COST_FACTOR if private: the base fee doesn't grow with the round, so a short question stays cheap late in
# the day (Kevin, Oct 11 2026; the base fee was most of a short message's price). Players earn
# BUDGET_PER_ROUND each round, carrying over up to BUDGET_MAX; at the start of each day, CARRY_SHARE of what's
# left carries over.
BUDGET_PER_ROUND = 2.5
BUDGET_MAX = 8.0
CARRY_SHARE = 0.5
MESSAGE_BASE_COST = 1.0
PRIVATE_COST_FACTOR = 0.25
MAX_MESSAGE_WORDS = 800
FULL_PRICE_ROUNDS = 3  # rounds at 1x; each later round's multiplier is ROUND_COST_STEP higher
ROUND_COST_STEP = 0.5  # linear, so late rounds stay affordable: round 8 is 3.5x
MAX_DAY_ROUNDS = 8  # rules R16; the day also ends after a full go-around in which nobody sends a public message
# Rules R1 (Kevin, Oct 12): Day 1 is for talking only, no nominations or trials, and is shorter (R16). A full Day 1
# hanged someone in 2 of 50 live games (both Jesters, a free win); skipping it left Night 1 with nothing to go on.
TALK_DAY_ROUNDS = 2


def talk_only(game: Game) -> bool:
    return game.day == 1


def day_rounds(game: Game) -> int:
    return TALK_DAY_ROUNDS if talk_only(game) else MAX_DAY_ROUNDS
FREE_DEFENSE_WORDS = 150  # the accused's first message on trial is free up to this length
# Each player's turn in a trial is priced at 1x whatever the round, and comes with a trial-only budget
# that is spent before their regular budget. Unspent trial budget is lost when the turn ends.
TRIAL_BUDGET = 2.0
MIN_TRUNCATED_WORDS = 3  # a message truncated below this is dropped instead
MAX_TRIALS_PER_DAY = 3
NOMINATION_COST = 1.0  # times the round multiplier, paid from the speaking budget; deters spam


LAST_WILL_WORDS = 300  # longer wills are truncated
CLAIM_WORDS = 40  # claims (in the public ledger) are short and free, so they can't replace chat


def budget_factor(p: Player) -> float:
    """How much more p earns per round and can hold than BUDGET_PER_ROUND and BUDGET_MAX (the Loud trait, R24)."""
    return math.prod(trait_logic(t).budget_factor for t in p.traits)


def length_factor(p: Player) -> float:
    """What multiplies the length part of p's message prices (the Curt trait, R24)."""
    return math.prod(trait_logic(t).length_factor for t in p.traits)


def earn(p: Player) -> None:
    """A round's speaking budget (rules R22)."""
    f = budget_factor(p)
    p.speaking_budget = min(BUDGET_MAX * f, p.speaking_budget + BUDGET_PER_ROUND * f)


def length_cost(words: int) -> float:
    """Cheap for short and medium messages, superlinear for long ones. budget_parameters spells this out."""
    return words / 60 + (words / 200) ** 2


def round_multiplier(rnd: int) -> float:
    """rnd is 1-based."""
    return 1 + ROUND_COST_STEP * max(0, rnd - FULL_PRICE_ROUNDS)


def message_cost(words: int, rnd: int, private: bool, free_words: int = 0, length_factor: float = 1.0) -> float:
    """length_factor: multiplies the length part (the Curt trait, R24), not the base fee."""
    if words == 0:
        return 0.0
    cost = MESSAGE_BASE_COST + length_cost(words) * round_multiplier(rnd) * length_factor
    if free_words:
        cost = 0.0 if words <= free_words else ((length_cost(words) - length_cost(free_words)) * round_multiplier(rnd)
                                                * length_factor)
    return cost * (PRIVATE_COST_FACTOR if private else 1.0)


def budget_parameters() -> str:
    """The speaking-budget numbers (rules R22), shown to every player at the start of the game."""
    return (f"Speaking budget numbers for this game (rules R22): you earn {BUDGET_PER_ROUND:g} per round, up to "
            f"{BUDGET_MAX:g}; at the start of each Day {CARRY_SHARE:.0%} of what you have left carries over, "
            "except that nothing carries over from Day 1. A "
            f"public message costs {MESSAGE_BASE_COST:g} + (words/60 + (words/200)^2) x the round multiplier; "
            f"a private one costs {PRIVATE_COST_FACTOR:g} of that. The multiplier is 1 for rounds 1-"
            f"{FULL_PRICE_ROUNDS} and rises by {ROUND_COST_STEP:g} each later round (round {MAX_DAY_ROUNDS}: "
            f"{round_multiplier(MAX_DAY_ROUNDS):g}x). A nomination costs {NOMINATION_COST:g} x the multiplier. "
            f"Messages are capped at {MAX_MESSAGE_WORDS} words. Trial turns use the 1x price plus a trial-only "
            f"budget of {TRIAL_BUDGET:g}; the accused's first defense message is free up to {FREE_DEFENSE_WORDS} "
            f"words. At most {MAX_TRIALS_PER_DAY} trials per Day. Each turn's prompt shows your budget and a "
            "price table.")


def price_table(rnd: int, trial: bool = False, length_factor: float = 1.0) -> str:
    """trial: the 1x prices of a trial turn, whatever the round. length_factor: the player's (the Curt trait)."""
    price_rnd = 1 if trial else rnd
    rows = [f"  {w:>3} words: public {message_cost(w, price_rnd, False, length_factor=length_factor):.2f}, "
            f"private {message_cost(w, price_rnd, True, length_factor=length_factor):.2f}"
            for w in (10, 25, 50, 100, 200, 400, MAX_MESSAGE_WORDS)]
    if trial:
        return "Message prices during this trial (1.00x):\n" + "\n".join(rows)
    nxt = round_multiplier(rnd + 1)
    return (f"Message prices this round (round {rnd}, {round_multiplier(rnd):.2f}x; next round "
            f"{nxt:.2f}x):\n" + "\n".join(rows))


def write_wills(game: Game, players: Players) -> None:
    """Last wills, written at the beginning of each Day; also on day turns and with the night action. Rules R13."""
    task = (f"Write or update your last will (max {LAST_WILL_WORDS} words). If you die, it is revealed "
            "to ALL players, including other factions, so think about what each of them would learn from it. "
            "An empty answer keeps your current will.")
    outs = players.ask_many([(p, task, LAST_WILL_SCHEMA, {"last_will": p.last_will}) for p in game.alive()],
                            step="will")
    for p, out in zip(game.alive(), outs):
        will = out["last_will"]
        if blank(will):  # blank (or a written-out null) means no change, as on day turns
            continue
        p.last_will = cap_words(will, LAST_WILL_WORDS)


def run_day(game: Game, players: Players) -> None:
    play_day(game, players)
    if talk_only(game):  # rules R22: Day 1's budget is use-it-or-lose-it, so staying quiet saves nothing for Day 2
        for p in game.players:
            p.speaking_budget = 0.0
    if game.check_winner() is None:
        for role_logic in day_action_logics(game):  # rules R25: day actions still waiting
            role_logic.at_day_end(game)


def day_action_logics(game: Game) -> list[RoleLogic]:
    """The logic of each role among the game's players, in name order, for day-action hooks (rules R25)."""
    return [logic(role) for role in sorted({q.role for q in game.players})]


def end_day_after_three_trials(game: Game) -> None:
    game.emit("Three trials ended in Innocent verdicts. The day ends.")


def announce_votes_needed(game: Game) -> None:
    n_alive = len(game.alive())  # players asked for the day's numbers (game_20261009_084630_739772)
    game.emit(f"{n_alive} players are alive, so a nomination needs {n_alive // 2 + 1} Yes votes (rules R4).")


def play_day(game: Game, players: Players) -> None:
    game.phase = "day"
    game.emit(f"Day {game.day} begins.", cat=PHASE)
    if game.day > 1 and not game.pending_deaths:  # players asked whether a quiet night was ever announced
        game.emit("Nobody died last night.")
    game.announce_dawn()
    game.run_dawn_hooks()
    if game.check_winner() is not None:
        return
    game.puppets, game.puppets_next = game.puppets_next, {}
    for puppet, puppeteer in list(game.puppets.items()):
        # A Puppeteer who died overnight can't act any more, so the puppeting lapses (rules R21).
        if game.player(puppet).alive and game.player(puppeteer).alive:
            game.emit("You are being puppeted today: you can't chat or see private messages, but you can "
                      "still nominate and vote.", [puppet])
        else:
            del game.puppets[puppet]

    if not talk_only(game):  # the first will comes with the Night 1 action (R13)
        write_wills(game, players)
    for p in game.alive():
        p.speaking_budget *= CARRY_SHARE
    trials = 0
    # Prosecutions happen at the start of the Day, before any chat (rules: Prosecutor). Round 1's budget is paid
    # out first so others can speak at the trial.
    prosecuted = [n for n in dict.fromkeys(game.prosecutions) if game.player(n).alive]
    game.prosecutions.clear()
    if prosecuted:
        for p in game.alive():
            earn(p)
    for name in prosecuted:
        if trials >= MAX_TRIALS_PER_DAY or not game.player(name).alive:
            break
        nominator = game.rng.choice(game.alive())  # the rules pick a random "nominator"
        game.emit(f"{name} is being prosecuted and goes straight to trial.", cat=NOMINATION)
        game.vote_record.append(f"Day {game.day}: {name} was prosecuted (straight to trial)")
        if run_trial(game, players, nominator, name, rnd=1, prosecuted=True) == "executed":
            return
        trials += 1
    if trials >= MAX_TRIALS_PER_DAY:
        end_day_after_three_trials(game)
        return
    # Turns go around the circle in seat order from a random start, the same every round, so nobody
    # speaks last in one round and first in the next.
    start = game.rng.choice(game.alive()).seat
    game.emit(f"Speaking order today goes around the circle in seat order, starting with "
              f"{game.players[start].name}.")
    if talk_only(game):
        game.emit(f"Day 1 is for talking only (rules R1): there are no nominations or trials today, and it lasts at "
                  f"most {TALK_DAY_ROUNDS} rounds.")
    else:
        announce_votes_needed(game)
    for rnd in range(1, day_rounds(game) + 1):
        for p in game.alive():
            if not (rnd == 1 and prosecuted):
                earn(p)
        alive = game.alive()
        order = [p for p in alive if p.seat >= start] + [p for p in alive if p.seat < start]
        active = False  # did anyone send a public message or nominate this go-around?
        round_start = len(game.events)

        def turn(p: Player, rnd: int, extra: str = "") -> bool:
            """One chat turn plus any nomination it makes. Returns whether the day is over."""
            nonlocal active, trials
            public, nominee = chat_turn(game, players, p, rnd, extra=extra,
                                        can_nominate=trials < MAX_TRIALS_PER_DAY and not talk_only(game))
            active |= public or nominee is not None
            over = False
            if nominee:
                outcome = run_nomination(game, players, nominator=p, nominee=nominee, rnd=rnd)
                over = outcome == "executed"  # an execution ends the day
                trials += outcome == "innocent"  # failed nominations don't count toward the limit
                if not over and trials >= MAX_TRIALS_PER_DAY:
                    end_day_after_three_trials(game)
                    over = True
            if not over:  # rules R25: day actions due after this turn (an ending Day fires the rest in run_day)
                n_alive = len(game.alive())
                for role_logic in day_action_logics(game):
                    role_logic.after_day_turn(game, p)
                if len(game.alive()) != n_alive and game.check_winner() is None and not talk_only(game):
                    announce_votes_needed(game)  # a death mid-Day (a day action) changes the count
            return over or game.check_winner() is not None

        over = False  # did a turn end the day?
        for p in order:
            if p.alive and turn(p, rnd):
                over = True
                break
        if not over and not active:
            # Rules R16: before a silent round ends the day, anyone sent a
            # private message this round gets one last turn to react to it (or the day just ends).
            got_pm = {e.fields["to"] for e in game.events[round_start:] if e.cat == PM}
            for p in [q for q in order if q.alive and q.name in got_pm]:
                if turn(p, rnd, extra="Nobody spoke publicly this round, so the day ends after this turn unless "
                                 "someone does. You get this last turn because you were sent a private "
                                 "message this round.\n"):
                    over = True
                    break
        if over:
            return
        if not active:
            game.emit("A full round passed with no public messages. The day ends.")
            return
    game.emit("Discussion time is over. The day ends.")


def drop_own_name(out: dict, name: str, model: Model) -> dict:
    """HACK, Haiku only: strips a leading "Name:" from the public message. The prompt already says not to
    write it, and every other model follows that; Haiku 5.5 wrote it on nearly every turn
    (game_20261009_084630_739772). Kept to models marked name_prefix in llm.MODELS so other models'
    messages are never rewritten; drop it if a later Haiku follows the prompt."""
    msg = out.get("public_message")
    if (model.info.name_prefix and isinstance(msg, str)
            and (m := re.match(rf"\s*\**{re.escape(name)}\**\s*:\s*", msg)) and msg[m.end():].strip()):
        out = {**out, "public_message": msg[m.end():]}
    return out


def planned_messages(out: dict) -> list[tuple[str | None, str]]:
    """(recipient or None for public, text), public message first."""
    msgs: list[tuple[str | None, str]] = []
    if (out.get("public_message") or "").strip():  # blank messages aren't messages
        msgs.append((None, out["public_message"]))
    msgs += [(pm["to"], pm["text"]) for pm in out.get("private_messages", []) if (pm.get("text") or "").strip()]
    return msgs


def turn_task(game: Game, p: Player, writer: Player, rnd: int, can_nominate: bool, nomination_fee: float,
              free_words: int, trial: bool) -> str:
    """What a speaking turn asks (chat_turn's arguments); writer is the Puppeteer when p is puppeted."""
    return (f"It is Day {game.day}, round {rnd} of at most {day_rounds(game)}. It's your turn. Your speaking "
            f"budget is {p.speaking_budget:.2f}; you earn {BUDGET_PER_ROUND * budget_factor(p):g} per round, "
            f"carrying over up to {BUDGET_MAX * budget_factor(p):g}; at the start of each day, {CARRY_SHARE:.0%} of "
            "what you have left carries over" + (" (nothing carries over from Day 1)" if talk_only(game) else "")
            + ". You may send one public message and any "
            f"number of private messages (everyone sees who you messaged, but only the recipient sees "
            f"the contents), or nothing. The transcript already shows who sent each message, so there's "
            "no need to start a message with your own name. Messages are "
            f"capped at {MAX_MESSAGE_WORDS} words. Prices grow each round after round {FULL_PRICE_ROUNDS}. "
            "The day ends after a full round where nobody sends a public message.\n"
            + price_table(rnd, trial, length_factor(p)) + "\n"
            + (f"This is a trial turn: prices are 1x whatever the round, and you also get a trial-only "
               f"budget of {TRIAL_BUDGET:.2f}, spent before your regular budget. Unspent trial budget is "
               "lost when this turn ends.\n" if trial else "")
            + (f"Your public message this turn is free up to {free_words} words; beyond that you "
               "pay only for the extra length.\n" if free_words else "")
            + (f"You may also replace your last will (free, max {LAST_WILL_WORDS} words; leave it \"\" to keep it), "
               "e.g. to match a claim you make today. It's shown to everyone if you die.\n" if writer is p else "")
            + (f"You may also set {'your' if writer is p else p.name + chr(39) + 's'} claim (free, max "
               f"{CLAIM_WORDS} words; leave it \"\" to keep it): a concise note of what you want everyone to know "
               "about you: your claimed role, your night visits and results, and your votes in key trials, e.g. "
               "'Sheriff. N1: checked Bob, Not Evil. N2: checked Dave, Evil. D3: Guilty on Dave'. A new or "
               "changed claim appears to everyone as a [Claim] line in the history, "
               "and the public ledger lists every player's latest claim and any earlier ones they changed from, "
               "as unverified claims.\n")
            + (f"You may nominate a player for trial, which stops chat for a vote. Nominating costs "
               f"{nomination_fee:.2f} from your budget this round and is paid before your messages.\n"
               if can_nominate else ""))


def record_claim(game: Game, p: Player, claim: str, puppeted: dict[str, Any]) -> None:
    """A new or changed claim goes in the public ledger (Game.claim_record) and the chat history."""
    if word_count(claim) > CLAIM_WORDS:  # said, so the writer can shorten it (game_20261011_225511_1253)
        game.emit(f"(Program note: your claim was over {CLAIM_WORDS} words, so the ledger shows only its first "
                  f"{CLAIM_WORDS}, ending in [truncated].)", [puppeted.get("puppeteer", p.name)])
    claim = cap_words(claim.strip(), CLAIM_WORDS)
    # The ledger already names the player: "Bob: Bob: Lookout" (game_20261011_055615_1112) drops the repeat.
    while m := re.match(rf"{re.escape(p.name)}\s*[:,]\s*(?=\w)", claim):
        claim = claim[m.end():]
    claims = game.claim_record.setdefault(p.name, [])
    if claims and same_claim(claims[-1][1], claim):  # e.g. only a final period differs
        claim = claims[-1][1]
    if not claims or claims[-1][1] != claim:  # shown in the chat history, so it's attributable like a message
        game.emit(f"[Claim] {p.name}: {claim}", cat=CLAIM, speaker=p.name, claim=claim, **puppeted)
    if claims and claims[-1][0] == game.day:
        claims[-1] = (game.day, claim)  # one entry per day: a same-day change replaces it
    elif not claims or claims[-1][1] != claim:
        claims.append((game.day, claim))


def chat_turn(game: Game, players: Players, p: Player, rnd: int, can_nominate: bool,
              extra: str = "", free_words: int = 0, trial: bool = False) -> tuple[bool, str | None]:
    """One speaking turn. Returns (whether a public message was sent, nominee or None).
    free_words: this turn's public message is free up to that many words (the accused's defense).
    trial: a trial turn, priced at 1x with a TRIAL_BUDGET spent first; what's left of it is lost.

    If the planned messages cost more than the player's budget, they're warned and asked once to
    revise; anything still over budget is then truncated (later messages first) or dropped."""

    price_rnd = 1 if trial else rnd
    trial_budget = TRIAL_BUDGET if trial else 0.0

    def cost_of(i: int, to: str | None, words: int) -> float:
        return message_cost(words, price_rnd, private=to is not None, length_factor=length_factor(p),
                            free_words=free_words if i == 0 and to is None else 0)

    def available() -> float:
        return trial_budget + p.speaking_budget

    def spend(cost: float) -> None:
        nonlocal trial_budget
        from_trial = min(trial_budget, cost)
        trial_budget -= from_trial
        p.speaking_budget -= cost - from_trial

    nomination_fee = NOMINATION_COST * round_multiplier(rnd)

    def total_cost(out: dict) -> float:
        fee = nomination_fee if can_nominate and out.get("nominate") else 0.0
        return fee + sum(cost_of(i, to, min(word_count(t), MAX_MESSAGE_WORDS))
                         for i, (to, t) in enumerate(planned_messages(out)))

    writer = game.player(game.chat_controller(p.name))
    step = "trial_turn" if trial else "day_turn"
    task = turn_task(game, p, writer, rnd, can_nominate, nomination_fee, free_words, trial) + extra
    fallback: dict[str, Any] = {"public_message": None, "private_messages": [], "nominate": None}
    # Rules R25: a day action only on a player's own speaking turn, not a trial turn or while puppeted.
    action = logic(p.role).day_action(game, p) if writer is p and not trial else None
    if action:
        task += action.text + "\n"
        fallback |= dict.fromkeys(action.fields)
    # Rules R24: a hidden private message (Confidant) only on a player's own turn, not while puppeted.
    hider = next((t for t in p.traits if trait_logic(t).can_hide_pm(game, p)), None) if writer is p else None
    if hider:
        task += ("You may also send one of this turn's private messages hidden (your trait, once per game): set "
                 "hidden_pm to its recipient, or leave it null. Nobody else is told that message was sent, and it "
                 "isn't counted in the public ledger.\n")
    # A human seat's page prices messages as they're typed (human.py); LLMs read the same numbers in the task.
    ui = {"budget": available(), "base": MESSAGE_BASE_COST, "multiplier": round_multiplier(price_rnd),
          "private_factor": PRIVATE_COST_FACTOR, "length_factor": length_factor(p), "free_words": free_words,
          "nomination_fee": nomination_fee if can_nominate else None, "max_words": MAX_MESSAGE_WORDS,
          "will_words": LAST_WILL_WORDS, "claim_words": CLAIM_WORDS}
    if writer is p:
        schema = day_turn_schema(game, p.name, can_nominate, action=action.fields if action else None,
                                 hidden_pm=bool(hider))
        out = players.ask(p, task, schema, fallback, step=step, rnd=rnd, ui=ui)
        out = drop_own_name(out, p.name, writer.model)
    else:
        # Puppeted: the Puppeteer writes p's messages (on p's budget); p still decides any nomination.
        task = (f"You are puppeting {p.name} today. This is {p.name}'s turn: the messages you write are "
                f"sent as {p.name}, and the budget below is {p.name}'s.\n" + task)
        schema = day_turn_schema(game, p.name, can_nominate=False, own_turn=False)
        out = players.ask(writer, task, schema, fallback, step=step, rnd=rnd, ui={**ui, "nomination_fee": None})
        out = drop_own_name(out, p.name, writer.model)
        if can_nominate:
            nominate_task = (f"It is Day {game.day}, round {rnd}, and your turn. You are puppeted, so you "
                             "can't chat, but you may nominate a player for trial (or null). Nominating costs "
                             f"{nomination_fee:.2f} from your budget ({p.speaking_budget:.2f}).")
            nominate_schema = obj(nominate=nullable(name_enum(game.alive_names())))
            out["nominate"] = players.ask(p, nominate_task, nominate_schema, {"nominate": None},
                                         step="puppet_nomination", rnd=rnd)["nominate"]
    # A puppet's own nomination is private: the Puppeteer revising the messages neither sees nor pays for it.
    planned = total_cost(out if writer is p else {**out, "nominate": None})
    if planned > available() + 1e-9:
        nominating = (f" plus a nomination of {out['nominate']}" if writer is p and can_nominate
                      and out.get("nominate") else "")
        warning = (f"\n\nWARNING: your planned messages {json.dumps(planned_messages(out))}{nominating} "
                   f"cost {planned:.2f}, but your budget is {available():.2f}. Revise them to fit. "
                   "If you still can't afford a nomination it won't happen, and messages over budget will "
                   "be truncated, starting with your last message.")
        game.log.write("budget_warning", player=p.name, planned=planned, budget=available())
        nominee = out.get("nominate")
        # If the revision fails, the first answer stands (and is cut to fit) rather than losing the turn.
        out = players.ask(writer, task + warning, schema, out, step="budget_revision", rnd=rnd, ui=ui)
        out = drop_own_name(out, p.name, writer.model)
        if writer is not p:
            out["nominate"] = nominee

    if writer is p and isinstance(will := out.get("last_will"), str) and not blank(will):
        p.last_will = cap_words(will, LAST_WILL_WORDS)
        if p.last_will != will:  # Sol's wills were cut 40 times unnoticed (game_20261009_152409_117630)
            game.emit(f"(Program note: your last will was over {LAST_WILL_WORDS} words, so it was cut to its "
                      f"first {LAST_WILL_WORDS}.)", [p.name])
    # The puppet sees these marked as their Puppeteer's in their own history (Game.history_split), as do log views.
    puppeted: dict[str, Any] = {} if writer is p else {"puppeteer": writer.name}
    # A claim with no letters or digits (Sol wrote "/" for "no change") or a written-out null keeps the old one.
    # (A Puppeteer may set the puppet's.)
    if isinstance(claim := out.get("claim"), str) and any(ch.isalnum() for ch in claim) and not blank(claim):
        record_claim(game, p, claim, puppeted)
    nominee = out.get("nominate") if can_nominate else None
    if nominee:
        if nomination_fee <= p.speaking_budget + 1e-9:
            p.speaking_budget -= nomination_fee
        else:
            game.log.write("nomination_dropped", player=p.name, nominee=nominee, budget=p.speaking_budget)
            game.emit(f"You couldn't afford to nominate {nominee}.", [p.name])
            nominee = None
    public = False
    hide_to = out.get("hidden_pm") if hider else None
    for i, (to, text) in enumerate(planned_messages(out)):
        if to is not None and to not in game.alive_names():  # the schema only offers living players
            game.log.error("harness_error", f"{p.name}'s private message went to {to!r}, who isn't a living "
                           "player; it was not sent", player=p.name, to=to)
            continue
        words = min(word_count(text), MAX_MESSAGE_WORDS)
        while words > 0 and cost_of(i, to, words) > available() + 1e-9:
            words -= 1
        where = ("Your " if writer is p else f"{p.name}'s ") + ("public message" if to is None
                                                               else f"private message to {to}")
        if words == 0 or (words < word_count(text) and words < MIN_TRUNCATED_WORDS):
            game.log.write("message_dropped", player=p.name, to=to, words=word_count(text))
            game.emit(f"{where} was not sent: over budget.", [writer.name])
            continue
        if words < word_count(text):
            if words < min(word_count(text), MAX_MESSAGE_WORDS):
                game.emit(f"{where} was cut to {words} words to fit the budget.", [writer.name])
            text = truncate_words(text, words)
        spend(cost_of(i, to, words))
        if to is None:
            public = True
            game.emit(f"{p.name} (public): {text}", cat=CHAT, speaker=p.name, message=text, **puppeted)
        else:
            # A puppeted player's private chat is read and written by their Puppeteer instead. Listeners
            # (Wiretap, Eavesdropper) read it under the puppet's name, unaware of the puppeting.
            readers = [writer.name, game.chat_controller(to)] + game.pm_listeners(p.name, to)
            if hider and to == hide_to:  # the first message to them this turn; nobody else is told it was sent
                hide_to = None
                game.emit(f"{p.name} -> {to} (private, hidden: nobody else was told it was sent): {text}", readers,
                          cat=PM, speaker=p.name, to=to, message=text, hidden=True)
                trait_logic(hider).hid_pm(game, p, to)
                continue
            game.emit(f"{p.name} -> {to} (private): {text}", readers, cat=PM, speaker=p.name, to=to, message=text,
                      **puppeted)
            pair = f"{p.name} -> {to}"
            counts = game.pm_record.setdefault(game.day, {})
            counts[pair] = counts.get(pair, 0) + 1
            # Everyone else sees that the message happened, but not its contents.
            game.emit(f"{p.name} sent {to} a private message.",
                      [q.name for q in game.alive() if q.name not in (p.name, to, *readers)], kind="notice")
    if hide_to:
        game.emit(f"You sent {hide_to} no private message this turn, so nothing was hidden and your hidden message "
                  "is still unused.", [p.name])
    if action:
        logic(p.role).carry_out_day_action(game, p, out)
    return public, nominee


def same_claim(a: str, b: str) -> bool:
    """Claims that differ only in case, spacing or end punctuation ("Carol Evil." and "Carol Evil" made two
    [Claim] lines in game_20261009_214935_178025)."""
    def norm(s: str) -> str:
        return " ".join(s.split()).rstrip(".!;, ").casefold()
    return norm(a) == norm(b)


def run_nomination(game: Game, players: Players, nominator: Player, nominee: str, rnd: int) -> str:
    """Rules R4. Nomination vote, then trial and verdict. Returns "failed", "innocent" or "executed".
    Both votes are simultaneous: every voter decides without seeing the others, then all votes
    are revealed together, or only their totals when the game's rule settings make them secret (variants.py)."""
    game.emit(f"{nominator.name} nominated {nominee}. Everyone now votes Yes/No simultaneously.", cat=NOMINATION)
    others = [v for v in game.clockwise_from(nominator.name) if v is not nominator]
    secret = game.rule_settings["nomination_votes"] == "secret"
    task = (f"{nominator.name} nominated {nominee}. Vote true (Yes) to put them on trial, false (No) "
            "otherwise. Voting is simultaneous: you can't see anyone else's vote, and "
            + ("the votes are secret: only the number of Yes votes is announced, never who voted which way. "
               if secret else "all votes are revealed publicly once everyone has voted. ")
            + f"{nominator.name} votes Yes automatically.")
    outs = players.ask_many([(v, task, VOTE_SCHEMA, {"vote": False}) for v in others], step="nomination_vote")
    yes_voters = [nominator.name] + [v.name for v, o in zip(others, outs) if o["vote"]]
    no_voters = [v.name for v, o in zip(others, outs) if not o["vote"]]
    # rules R4: majority of all votes counted (one each; no abstentions)
    passed = majority(len(yes_voters), len(game.alive()))
    log_vote(game, "nomination", nominator.name, nominee, yes_voters, no_voters, "passed" if passed else "failed")
    outcome = "passed" if passed else "failed"
    if secret:  # rule setting: only the nominator and the Yes count are public; each voter is told their own vote
        game.emit(f"Nomination votes on {nominee}: {len(yes_voters)} Yes (the votes are secret).", cat=VOTE)
        for v, o in zip(others, outs):
            game.emit(f"(Only you see this) You voted {'Yes' if o['vote'] else 'No'} on the nomination of {nominee}.",
                      [v.name], kind="notice", cat=VOTE)
        game.vote_record.append(f"Day {game.day}: {nominator.name} nominated {nominee}; {len(yes_voters)} Yes "
                                f"(secret vote); {outcome}")
    else:
        game.emit(f"Nomination votes on {nominee}: Yes - {', '.join(yes_voters)}; "
                  f"No - {', '.join(no_voters) or 'nobody'}.", cat=VOTE)
        game.vote_record.append(f"Day {game.day}: {nominator.name} nominated {nominee}; Yes - {', '.join(yes_voters)}"
                                f"; No - {', '.join(no_voters) or 'nobody'}; {outcome}")
    if not passed:
        game.emit(f"The nomination of {nominee} failed ({len(yes_voters)} Yes).", cat=VOTE)
        return "failed"
    game.emit(f"{nominee} is put on trial ({len(yes_voters)} Yes).", cat=VOTE)
    return run_trial(game, players, nominator, nominee, rnd)


TRIAL_VOTE_NOTE = ("This turn is only for discussion: after everyone has spoken, all players vote "
                   "Guilty/Innocent in a separate, simultaneous vote.")


def log_vote(game: Game, stage: str, nominator: str, nominee: str, yes: list[str], no: list[str], outcome: str,
             prosecuted: bool = False, weights: dict[str, int] | None = None,
             reversed_voters: list[str] | None = None, fixed: dict[str, str] | None = None) -> None:
    """A structured vote record for analysis. stage is "nomination" (yes = Yes votes, including the
    nominator's automatic one) or "trial" (yes = Guilty votes). weights: trial voters counted more than once.
    fixed: trial voters whose vote a trait fixed (rules R24), with the trait."""
    game.votes.setdefault(game.day, []).append(
        {"stage": stage, "nominee": nominee, "votes": {**dict.fromkeys(yes, True), **dict.fromkeys(no, False)}})
    game.log.write("vote", day=game.day, stage=stage, nominator=nominator, nominee=nominee,
                   votes={**dict.fromkeys(yes, True), **dict.fromkeys(no, False)}, outcome=outcome,
                   prosecuted=prosecuted, secret=game.rule_settings[f"{stage}_votes"] == "secret",
                   **({"weights": weights, "reversed": reversed_voters or [], "fixed": fixed or {}}
                      if stage == "trial" else {}))


def run_trial(game: Game, players: Players, nominator: Player, nominee: str, rnd: int,
              prosecuted: bool = False) -> str:
    """Defense, discussion, then a simultaneous Guilty/Innocent vote. Returns "innocent" or "executed".
    If a Clerk rigged today's vote, the accused is executed regardless; the rigging is announced
    only if the vote alone wouldn't have executed them. A prosecuted player's nominator is random."""
    accused = game.player(nominee)
    chat_turn(game, players, accused, rnd, can_nominate=False, free_words=FREE_DEFENSE_WORDS, trial=True,
              extra="You are on trial. Defend yourself; you speak first. " + TRIAL_VOTE_NOTE)
    for p in game.clockwise_from(accused.name)[1:]:
        chat_turn(game, players, p, rnd, can_nominate=False, trial=True,
                  extra=f"{nominee} is on trial. " + TRIAL_VOTE_NOTE)
    # rules R4: a last word, so questions asked during the trial get an answer
    chat_turn(game, players, accused, rnd, can_nominate=False, free_words=FREE_DEFENSE_WORDS, trial=True,
              extra="You are on trial. Everyone else has spoken: this is your last public message before the "
                    "vote, to answer questions and accusations. " + TRIAL_VOTE_NOTE)

    voters = game.alive()
    secret = game.rule_settings["trial_votes"] == "secret"
    task = (f"{nominee} is on trial. Vote true for Guilty (execute), false for Innocent. Voting is "
            "simultaneous: you can't see anyone else's vote, and "
            + ("the votes are secret: only the Guilty and Innocent totals are announced, never who voted which way."
               if secret else "all votes are revealed publicly once everyone has voted."))
    # A role may add a choice to its vote (Ballot Stuffer)
    options: dict[str, DayAction] = {v.name: opt for v in voters if (opt := logic(v.role).trial_vote_option(game, v))}
    outs = players.ask_many([(v, f"{task} {options[v.name].text}", obj(**VOTE_SCHEMA["properties"],
                                                                         **options[v.name].fields), {"vote": False})
                             if v.name in options else (v, task, VOTE_SCHEMA, {"vote": False}) for v in voters],
                            step="trial_vote")
    # A trait may fix how a vote counts (Zealot, Merciful, rules R24): its holder knows, so their reminder says so;
    # it overrides a Fixer. A role may count a vote as the opposite of what was cast (Fixer): the voter's reminder
    # shows the vote they cast. The count, the log and anyone who sees votes (Informant, Auditor) see the vote as
    # counted.
    fixed = {v.name: f for v in voters if (f := fixed_trial_vote(v))}
    reversed_voters = [v.name for v in voters if v.name not in fixed and game.trial_vote_reversed(v)]
    counted = [fixed[v.name][1] if v.name in fixed else o["vote"] != (v.name in reversed_voters)
               for v, o in zip(voters, outs)]
    guilty = [v.name for v, c in zip(voters, counted) if c]
    innocent = [v.name for v, c in zip(voters, counted) if not c]
    # A role may count a voter more than once (Ballot Stuffer); the verdict then needs a majority of all
    # votes counted, and the announced totals include the extra votes without saying whose they are.
    weight = {v.name: logic(v.role).trial_vote_weight(game, v, o) for v, o in zip(voters, outs)}
    guilty_votes, total_votes = sum(weight[n] for n in guilty), sum(weight.values())
    if secret:  # rule setting: only the totals are public; each voter is told their own vote
        game.emit(f"Trial votes on {nominee}: {guilty_votes} Guilty, {total_votes - guilty_votes} Innocent (the "
                  "votes are secret).", cat=VOTE)
        for v, o, c in zip(voters, outs, counted):
            trait = (f" Your {fixed[v.name][0]} trait counted it as {'Guilty' if c else 'Innocent'}."
                     if v.name in fixed else "")
            game.emit(f"(Only you see this) You voted {'Guilty' if o['vote'] else 'Innocent'} in the trial of "
                      f"{nominee}.{trait}", [v.name], kind="notice", cat=VOTE)
        informants = [p.name for p in game.alive() if logic(p.role).sees_trial_votes(game, p)]
        if informants:
            game.emit(f"(Only you see this) How everyone voted in the trial of {nominee}: Guilty - "
                      f"{', '.join(guilty) or 'nobody'}; Innocent - {', '.join(innocent) or 'nobody'}.", informants,
                      cat=VOTE)
    else:
        game.emit(f"Trial votes on {nominee}: Guilty - {', '.join(guilty) or 'nobody'}; "
                  f"Innocent - {', '.join(innocent) or 'nobody'}.", cat=VOTE)
    for t in TRAIT_LOGIC.values():  # rules R24, e.g. the Kindred's result
        t.after_trial_vote(game, nominee, {v.name: o["vote"] for v, o in zip(voters, outs)}, guilty)
    tally = f"{guilty_votes} Guilty of {total_votes} votes; {total_votes // 2 + 1} needed"  # rules R4: a majority
    if total_votes != len(voters):
        tally += (f"; there are more votes than the {len(voters)} voters because a role manipulated the count on "
                  "purpose (rules R4), not because of an error")
    voted_guilty = majority(guilty_votes, total_votes)
    rigged = not voted_guilty and game.rigged_day == game.day
    verdict = "executed" if voted_guilty else "executed (Clerk-rigged)" if rigged else "Innocent"
    log_vote(game, "trial", nominator.name, nominee, guilty, innocent, verdict, prosecuted=prosecuted,
             weights={n: w for n, w in weight.items() if w != 1}, reversed_voters=reversed_voters,
             fixed={n: t for n, (t, _) in fixed.items()})
    game.vote_record.append(
        f"Day {game.day}: trial of {nominee}; "
        + (f"{guilty_votes} Guilty, {total_votes - guilty_votes} Innocent (secret vote)" if secret else
           f"Guilty - {', '.join(guilty) or 'nobody'}; Innocent - {', '.join(innocent) or 'nobody'}")
        + f"; {verdict}")
    if voted_guilty or game.rigged_day == game.day:
        # One line for a rigged hanging: "executed (3 Guilty of 7; 4 needed)" read as a contradiction
        # (game_20261009_121338_61703).
        game.emit(f"{nominee} is executed by hanging ({tally})." if voted_guilty else
                  f"The verdict was Innocent ({tally}), but the vote was rigged by a Clerk, so {nominee} is "
                  "executed by hanging anyway.", cat=DEATH)
        game.kill(nominee, "executed by hanging", guilty_voters=guilty)
        for t in TRAIT_LOGIC.values():  # rules R24, e.g. a Remorseful voter's death
            t.after_hanging(game, game.player(nominee), {v.name: o["vote"] for v, o in zip(voters, outs)})
        return "executed"
    game.emit(f"{nominee} is found Innocent ({tally}).", cat=VOTE)
    return "innocent"
