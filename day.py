"""The day phase: speaking budget, chat turns, nominations and simultaneous votes."""

import json
from typing import Any

from players import (LAST_WILL_SCHEMA, STR, VOTE_SCHEMA, Players, day_turn_schema, name_enum, nullable, obj,
                     truncate_words, word_count)
from events import CHAT, DEATH, NOMINATION, PHASE, PM, VOTE
from roles import logic
from state import Game, Player, majority


# Speaking budget. A message costs round_multiplier * (MESSAGE_BASE_COST + length_cost(words)),
# times PRIVATE_COST_FACTOR if private. Players earn BUDGET_PER_ROUND each round, carrying over up
# to BUDGET_MAX; the budget resets to 0 each day.
BUDGET_PER_ROUND = 2.5
BUDGET_MAX = 8.0
MESSAGE_BASE_COST = 1.0
PRIVATE_COST_FACTOR = 0.25
MAX_MESSAGE_WORDS = 800
FULL_PRICE_ROUNDS = 3  # rounds at 1x; each later round's multiplier is ROUND_COST_STEP higher
ROUND_COST_STEP = 0.5  # linear, so late rounds stay affordable: round 8 is 3.5x
MAX_DAY_ROUNDS = 8  # rules R16; the day also ends after a full go-around in which nobody sends a public message
FREE_DEFENSE_WORDS = 150  # the accused's first message on trial is free up to this length
# Each player's turn in a trial is priced at 1x whatever the round, and comes with a trial-only budget
# that is spent before their regular budget. Unspent trial budget is lost when the turn ends.
TRIAL_BUDGET = 3.0
MIN_TRUNCATED_WORDS = 3  # a message truncated below this is dropped instead
MAX_TRIALS_PER_DAY = 3
NOMINATION_COST = 1.0  # times the round multiplier, paid from the speaking budget; deters spam


LAST_WILL_WORDS = 300  # longer wills are truncated
CLAIM_WORDS = 30  # claims (in the public ledger) are short and free, so they can't replace chat


def length_cost(words: int) -> float:
    """Cheap for short and medium messages, superlinear for long ones."""
    return words / 60 + (words / 200) ** 2


def round_multiplier(rnd: int) -> float:
    """rnd is 1-based."""
    return 1 + ROUND_COST_STEP * max(0, rnd - FULL_PRICE_ROUNDS)


def message_cost(words: int, rnd: int, private: bool, free_words: int = 0) -> float:
    if words == 0:
        return 0.0
    cost = MESSAGE_BASE_COST + length_cost(words)
    if free_words:
        cost = 0.0 if words <= free_words else length_cost(words) - length_cost(free_words)
    return cost * round_multiplier(rnd) * (PRIVATE_COST_FACTOR if private else 1.0)


def price_table(rnd: int, trial: bool = False) -> str:
    """trial: the 1x prices of a trial turn, whatever the round."""
    price_rnd = 1 if trial else rnd
    rows = [f"  {w:>3} words: public {message_cost(w, price_rnd, False):.2f}, "
            f"private {message_cost(w, price_rnd, True):.2f}"
            for w in (10, 25, 50, 100, 200, 400, MAX_MESSAGE_WORDS)]
    if trial:
        return "Message prices during this trial (1.00x):\n" + "\n".join(rows)
    nxt = round_multiplier(rnd + 1)
    return (f"Message prices this round (round {rnd}, {round_multiplier(rnd):.2f}x; next round "
            f"{nxt:.2f}x):\n" + "\n".join(rows))


def run_day(game: Game, players: Players) -> None:
    game.phase = "day"
    game.emit(f"Day {game.day} begins.", cat=PHASE)
    game.announce_dawn()
    game.run_dawn_hooks()
    if game.check_winner() is not None:
        return
    game.puppets, game.puppets_next = game.puppets_next, {}
    for puppet, puppeteer in list(game.puppets.items()):
        # A Puppeteer who died overnight can't act any more (rules R12), so the puppeting lapses.
        if game.player(puppet).alive and game.player(puppeteer).alive:
            game.emit("You are being puppeted today: you can't chat or see private messages, but you can "
                      "still nominate and vote.", [puppet])
        else:
            del game.puppets[puppet]

    # Last wills, written at the beginning of each day (including day 1); also on day turns. Rules R13.
    task = (f"Write or update your last will (max {LAST_WILL_WORDS} words). If you die, it is revealed "
            "to ALL players, including other factions. An empty answer keeps your current will.")
    outs = players.ask_many([(p, task, LAST_WILL_SCHEMA, {"last_will": p.last_will}) for p in game.alive()])
    for p, out in zip(game.alive(), outs):
        will = out["last_will"]
        if not will.strip():  # blank means no change, as on day turns
            continue
        p.last_will = truncate_words(will, LAST_WILL_WORDS) if word_count(will) > LAST_WILL_WORDS else will

    for p in game.alive():
        p.speaking_budget = 0.0
    trials = 0
    # Prosecutions happen when nominations would start, before any chat. Round 1's budget is paid
    # out first so others can speak at the trial.
    prosecuted = [n for n in dict.fromkeys(game.prosecutions) if game.player(n).alive]
    game.prosecutions.clear()
    if prosecuted:
        for p in game.alive():
            p.speaking_budget = BUDGET_PER_ROUND
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
        game.emit("Three trials ended in Innocent verdicts. The day ends.")
        return
    # Turns go around the circle in seat order from a random start, the same every round, so nobody
    # speaks last in one round and first in the next.
    start = game.rng.choice(game.alive()).seat
    game.emit(f"Speaking order today goes around the circle in seat order, starting with "
              f"{game.players[start].name}.")
    for rnd in range(1, MAX_DAY_ROUNDS + 1):
        for p in game.alive():
            if not (rnd == 1 and prosecuted):
                p.speaking_budget = min(BUDGET_MAX, p.speaking_budget + BUDGET_PER_ROUND)
        alive = game.alive()
        order = [p for p in alive if p.seat >= start] + [p for p in alive if p.seat < start]
        active = False  # did anyone send a public message or nominate this go-around?
        round_start = len(game.events)

        def turn(p: Player, rnd: int, extra: str = "") -> bool:
            """One chat turn plus any nomination it makes. Returns whether the day is over."""
            nonlocal active, trials
            public, nominee = chat_turn(game, players, p, rnd, can_nominate=trials < MAX_TRIALS_PER_DAY,
                                        extra=extra)
            active |= public or nominee is not None
            if nominee:
                outcome = run_nomination(game, players, nominator=p, nominee=nominee, rnd=rnd)
                if outcome == "executed":
                    return True  # an execution ends the day
                trials += outcome == "innocent"  # failed nominations don't count toward the limit
                if trials >= MAX_TRIALS_PER_DAY:
                    game.emit("Three trials ended in Innocent verdicts. The day ends.")
                    return True
            return False

        for p in order:
            if p.alive and turn(p, rnd):
                return
        if not active:
            # Rules R16: before a silent round ends the day, anyone sent a
            # private message this round gets one last turn to react to it (or the day just ends).
            got_pm = {e.fields["to"] for e in game.events[round_start:] if e.cat == PM}
            for p in [q for q in order if q.alive and q.name in got_pm]:
                if turn(p, rnd, extra="Nobody spoke publicly this round, so the day ends after this turn unless "
                                 "someone does. You get this last turn because you were sent a private "
                                 "message this round.\n"):
                    return
        if not active:
            game.emit("A full round passed with no public messages. The day ends.")
            return
    game.emit("Discussion time is over. The day ends.")


def planned_messages(out: dict) -> list[tuple[str | None, str]]:
    """(recipient or None for public, text), public message first."""
    msgs: list[tuple[str | None, str]] = []
    if (out.get("public_message") or "").strip():  # blank messages aren't messages
        msgs.append((None, out["public_message"]))
    msgs += [(pm["to"], pm["text"]) for pm in out.get("private_messages", []) if (pm.get("text") or "").strip()]
    return msgs


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
        return message_cost(words, price_rnd, private=to is not None,
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
    task = (f"It is Day {game.day}, round {rnd} of at most {MAX_DAY_ROUNDS}. It's your turn. Your speaking "
            f"budget is {p.speaking_budget:.2f}; you earn {BUDGET_PER_ROUND:g} per round, carrying over "
            f"up to {BUDGET_MAX:g}, and it resets each day. You may send one public message and any "
            f"number of private messages (everyone sees who you messaged, but only the recipient sees "
            f"the contents), or nothing. Messages are "
            f"capped at {MAX_MESSAGE_WORDS} words. Prices grow each round after round {FULL_PRICE_ROUNDS}, "
            "so late messages are only worth it if important. The day ends after a full round where "
            "nobody sends a public message.\n" + price_table(rnd, trial) + "\n"
            + (f"This is a trial turn: prices are 1x whatever the round, and you also get a trial-only "
               f"budget of {TRIAL_BUDGET:.2f}, spent before your regular budget. Unspent trial budget is "
               "lost when this turn ends, but don't speak just to use it up: say nothing if you have "
               "nothing to add.\n" if trial else "")
            + (f"Your public message this turn is free up to {free_words} words; beyond that you "
               "pay only for the extra length.\n" if free_words else "")
            + ("You may also replace your last will (free; null keeps it), e.g. to match a claim you make "
               "today. It's shown to everyone if you die.\n" if writer is p else "")
            + (f"You may also set {'your' if writer is p else p.name + chr(39) + 's'} claim (free, max "
               f"{CLAIM_WORDS} words; null keeps it): a claimed role and night results, e.g. 'Sheriff. N1: "
               "Bob Not Evil'. The public ledger lists every player's latest claim and any earlier ones they "
               "changed from, as unverified claims.\n")
            + (f"You may nominate a player for trial, which stops chat for a vote. Nominating costs "
               f"{nomination_fee:.2f} from your budget this round and is paid before your messages.\n"
               if can_nominate else "")
            + extra)
    fallback: dict[str, Any] = {"thoughts": "", "public_message": None, "private_messages": [], "nominate": None}
    if writer is p:
        schema = day_turn_schema(game, p.name, can_nominate)
        out = players.ask(p, task, schema, fallback)
    else:
        # Puppeted: the Puppeteer writes p's messages (on p's budget); p still decides any nomination.
        task = (f"You are puppeting {p.name} today. This is {p.name}'s turn: the messages you write are "
                f"sent as {p.name}, and the budget below is {p.name}'s.\n" + task)
        schema = day_turn_schema(game, p.name, can_nominate=False, own_turn=False)
        out = players.ask(writer, task, schema, fallback)
        if can_nominate:
            nominate_task = (f"It is Day {game.day}, round {rnd}, and your turn. You are puppeted, so you "
                             "can't chat, but you may nominate a player for trial (or null). Nominating costs "
                             f"{nomination_fee:.2f} from your budget ({p.speaking_budget:.2f}).")
            nominate_schema = obj(thoughts=STR, nominate=nullable(name_enum(game.alive_names())))
            out["nominate"] = players.ask(p, nominate_task, nominate_schema, {"nominate": None})["nominate"]
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
        out = players.ask(writer, task + warning, schema, out)
        if writer is not p:
            out["nominate"] = nominee

    if writer is p and isinstance(will := out.get("last_will"), str) and will.strip():
        p.last_will = truncate_words(will, LAST_WILL_WORDS) if word_count(will) > LAST_WILL_WORDS else will
    if isinstance(claim := out.get("claim"), str) and claim.strip():  # a Puppeteer may set the puppet's
        claim = truncate_words(claim, CLAIM_WORDS) if word_count(claim) > CLAIM_WORDS else claim.strip()
        claims = game.claim_record.setdefault(p.name, [])
        if claims and claims[-1][0] == game.day:
            claims[-1] = (game.day, claim)  # one entry per day: a same-day change replaces it
        elif not claims or claims[-1][1] != claim:
            claims.append((game.day, claim))
    nominee = out.get("nominate") if can_nominate else None
    if nominee:
        if nomination_fee <= p.speaking_budget + 1e-9:
            p.speaking_budget -= nomination_fee
        else:
            game.log.write("nomination_dropped", player=p.name, nominee=nominee, budget=p.speaking_budget)
            game.emit(f"You couldn't afford to nominate {nominee}.", [p.name])
            nominee = None
    public = False
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
            game.emit(f"{p.name} (public): {text}", cat=CHAT, speaker=p.name, message=text)
        else:
            # A puppeted player's private chat is read and written by their Puppeteer instead. Listeners
            # (Wiretap, Eavesdropper) read it under the puppet's name, unaware of the puppeting.
            readers = [writer.name, game.chat_controller(to)] + game.pm_listeners(p.name, to)
            game.emit(f"{p.name} -> {to} (private): {text}", readers, cat=PM, speaker=p.name, to=to, message=text)
            pair = f"{p.name} -> {to}"
            counts = game.pm_record.setdefault(game.day, {})
            counts[pair] = counts.get(pair, 0) + 1
            # Everyone else sees that the message happened, but not its contents.
            game.emit(f"{p.name} sent {to} a private message.",
                      [q.name for q in game.players if q.name not in (p.name, to, *readers)], kind="notice")
    return public, nominee


def run_nomination(game: Game, players: Players, nominator: Player, nominee: str, rnd: int) -> str:
    """Rules R4. Nomination vote, then trial and verdict. Returns "failed", "innocent" or "executed".
    Both votes are simultaneous: every voter decides without seeing the others, then all votes
    are revealed together."""
    game.emit(f"{nominator.name} nominated {nominee}. Everyone now votes Yes/No simultaneously.", cat=NOMINATION)
    others = [v for v in game.clockwise_from(nominator.name) if v is not nominator]
    task = (f"{nominator.name} nominated {nominee}. Vote true (Yes) to put them on trial, false (No) "
            "otherwise. Voting is simultaneous: you can't see anyone else's vote, and all votes are "
            f"revealed publicly once everyone has voted. {nominator.name} votes Yes automatically.")
    outs = players.ask_many([(v, task, VOTE_SCHEMA, {"thoughts": "", "vote": False}) for v in others])
    yes_voters = [nominator.name] + [v.name for v, o in zip(others, outs) if o["vote"]]
    no_voters = [v.name for v, o in zip(others, outs) if not o["vote"]]
    game.emit(f"Nomination votes on {nominee}: Yes - {', '.join(yes_voters)}; "
              f"No - {', '.join(no_voters) or 'nobody'}.", cat=VOTE)
    passed = majority(len(yes_voters), len(game.alive()))
    log_vote(game, "nomination", nominator.name, nominee, yes_voters, no_voters, "passed" if passed else "failed")
    game.vote_record.append(f"Day {game.day}: {nominator.name} nominated {nominee}; Yes - {', '.join(yes_voters)}; "
                            f"No - {', '.join(no_voters) or 'nobody'}; {'passed' if passed else 'failed'}")
    if not passed:
        game.emit(f"The nomination of {nominee} failed ({len(yes_voters)} Yes).", cat=VOTE)
        return "failed"
    game.emit(f"{nominee} is put on trial ({len(yes_voters)} Yes).", cat=VOTE)
    return run_trial(game, players, nominator, nominee, rnd)


TRIAL_VOTE_NOTE = ("This turn is only for discussion: after everyone has spoken, all players vote "
                   "Guilty/Innocent in a separate, simultaneous vote.")


def log_vote(game: Game, stage: str, nominator: str, nominee: str, yes: list[str], no: list[str], outcome: str,
             prosecuted: bool = False, weights: dict[str, int] | None = None) -> None:
    """A structured vote record for analysis. stage is "nomination" (yes = Yes votes, including the
    nominator's automatic one) or "trial" (yes = Guilty votes). weights: trial voters counted more than once."""
    game.log.write("vote", day=game.day, stage=stage, nominator=nominator, nominee=nominee,
                   votes={**{n: True for n in yes}, **{n: False for n in no}}, outcome=outcome,
                   prosecuted=prosecuted, **({"weights": weights} if stage == "trial" else {}))


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

    voters = game.alive()
    task = (f"{nominee} is on trial. Vote true for Guilty (execute), false for Innocent. Voting is "
            "simultaneous: you can't see anyone else's vote, and all votes are revealed publicly once "
            "everyone has voted.")
    outs = players.ask_many([(v, task, VOTE_SCHEMA, {"thoughts": "", "vote": False}) for v in voters])
    guilty = [v.name for v, o in zip(voters, outs) if o["vote"]]
    innocent = [v.name for v, o in zip(voters, outs) if not o["vote"]]
    game.emit(f"Trial votes on {nominee}: Guilty - {', '.join(guilty) or 'nobody'}; "
              f"Innocent - {', '.join(innocent) or 'nobody'}.", cat=VOTE)
    # A role may count a voter more than once (Ballot Stuffer); the verdict then needs a majority of all
    # votes counted, and the announced totals include the extra votes without saying whose they are.
    weight = {v.name: logic(v.role).trial_vote_weight(game, v) for v in voters}
    guilty_votes, total_votes = sum(weight[n] for n in guilty), sum(weight.values())
    tally = f"{guilty_votes} Guilty of {total_votes} votes"
    voted_guilty = majority(guilty_votes, total_votes)
    rigged = not voted_guilty and game.rigged_day == game.day
    verdict = "executed" if voted_guilty else "executed (Clerk-rigged)" if rigged else "Innocent"
    log_vote(game, "trial", nominator.name, nominee, guilty, innocent, verdict, prosecuted=prosecuted,
             weights={n: w for n, w in weight.items() if w != 1})
    game.vote_record.append(f"Day {game.day}: trial of {nominee}; Guilty - {', '.join(guilty) or 'nobody'}; "
                            f"Innocent - {', '.join(innocent) or 'nobody'}; {verdict}")
    if voted_guilty or game.rigged_day == game.day:
        if not voted_guilty:
            game.emit(f"The vote was rigged by a Clerk: {nominee} is executed despite the Innocent verdict.",
                      cat=VOTE)
        game.emit(f"{nominee} is executed by hanging ({tally}).", cat=DEATH)
        game.kill(nominee, "executed by hanging", guilty_voters=guilty)
        return "executed"
    game.emit(f"{nominee} is found Innocent ({tally}).", cat=VOTE)
    return "innocent"
