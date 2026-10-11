"""The night phase: Yakuza chat, night actions, the Katana vote, then moderator resolution."""

import json

from players import BOOL, Players, STR, as_chosen, cap_words, name_enum, night_action_schema, nullable, obj, tokens_left
from roles import LOGIC, Alignment, Status, logic
from roles.base import swaps_tonight
from events import PHASE, YAKUZA_CHAT
from state import Game, majority
from moderator import Moderator
from night_check import NightChecker


YAKUZA_CHAT_ROUNDS = 3
YAKUZA_MESSAGE_WORDS = 200  # Yakuza chat is free but each message is capped at this length


def run_night(game: Game, players: Players, moderator: Moderator, checker: NightChecker | None = None) -> None:
    game.phase = "night"
    game.emit(f"Night {game.day} begins.", cat=PHASE)
    alive_at_start = {p.name for p in game.alive()}  # the revenge draw's pool (R10)
    yakuza_at_start = [y.name for y in game.yakuza()]
    if len(game.yakuza()) > 1:
        yakuza_chat(game, players, YAKUZA_CHAT_ROUNDS,
                    "Discuss tonight's plan: who holds the Katana, who it attacks, and your other actions. "
                    + katana_majority_note(game))

    actors = [p for p in game.alive() if logic(p.role).acts_at_night(p) or p.info.alignment is Alignment.EVIL]
    jobs = []
    for p in actors:
        task = (f"It is Night {game.day}. Choose your night action for your role, following the rules. "
                "Set act=false to do nothing. Fill only the fields your role needs."
                + (f" You have {tokens_left(p)}." if p.tokens else ""))
        if p.info.alignment is Alignment.EVIL:
            task += (" Also vote on who should hold the Katana and who the Katana should attack (or null). "
                     + katana_majority_note(game))
        jobs.append((p, task, night_action_schema(game, p), {"act": False}))
    actions = dict(zip([p.name for p in actors], players.ask_many(jobs, step="night_action")))
    for p in game.alive():
        if p.name not in actions and (auto := logic(p.role).automatic_action(game, p)) is not None:
            actions[p.name] = {**auto, "automatic": True}
    game.log.write("night_actions", day=game.day, actions=actions,
                   roles={name: game.player(name).role for name in actions})

    holder_before = game.katana_holder  # restored before the tally is redone below
    katana = tally_katana(game, actions)
    revote: dict[str, str | None] = {}  # Yakuza -> target, if there was a revote
    yakuza = game.yakuza()
    if katana.get("note") == NO_MAJORITY and len(yakuza) > 1:
        # No majority: show the votes, one more round of chat, then a Katana-only revote.
        votes = "; ".join(f"{y.name}: holder {actions[y.name].get('katana_vote_holder')}, target "
                          f"{actions[y.name].get('katana_vote_target')}" for y in yakuza)
        game.emit(f"The Katana vote had no majority on a target, so there would be no attack. Votes: {votes}.",
                  [y.name for y in yakuza])
        yakuza_chat(game, players, 1, "Agree on the Katana holder and target before the revote. "
                    + katana_majority_note(game))
        names = game.alive_names()
        revote_schema = obj(katana_vote_holder=name_enum([y.name for y in yakuza]),
                            katana_vote_target=nullable(name_enum(names)))
        outs = players.ask_many([(y, "Revote on the Katana holder and the Katana target (or null). "
                                  + katana_majority_note(game),
                                  revote_schema, {"katana_vote_holder": game.katana_holder or y.name,
                                                 "katana_vote_target": None})
                                 for y in yakuza], step="katana_revote")
        for y, out in zip(yakuza, outs):
            actions[y.name].update(katana_vote_holder=out["katana_vote_holder"],
                                   katana_vote_target=out["katana_vote_target"])
            revote[y.name] = out["katana_vote_target"]
        katana = tally_katana(game, actions)
    for role_logic in LOGIC.values():  # e.g. a Smuggler's swap redirects the other actions (rules R23)
        role_logic.before_resolution(game, actions)
    game.katana_holder = holder_before
    katana = tally_katana(game, actions)
    game.night_actions[game.day] = actions  # shown back to each player (players.night_history)
    game.log.write("katana", day=game.day, result=katana, revote_targets=revote or None)
    instructions = (
        f"Resolve Night {game.day}." + (" There was no Day 1 (rules R1): this night comes first." if game.day == 1
                                        else "") + " Submitted night actions (JSON, keyed by player):\n"
        f"{json.dumps(actions, indent=1)}\n\nKatana vote result: {json.dumps(katana)}\n"
        + (f"Code has already moved the Katana from {katana['moved_from']}, who held it when the night began, to "
           f"{katana['holder']}; get_state shows the new holder.\n" if katana.get("moved_from") else "")
        + swap_text(game, katana) + "\n"
        "Resolve all actions simultaneously per the rules, following the R20 checklist (R10; visits R6, "
        "role-blocks R9, attack vs defense R3, investigation results R19, e.g. the Katana holder and Fabricator "
        "frames). Use apply_changes for deaths and token/status changes, tell() for each private result, "
        "and end_phase when done. "
        "Deaths you apply are announced publicly at dawn automatically, including the kill's cause, so "
        "make the cause just the source as the rules allow it to be known (e.g. 'Katana', 'Vigilante', "
        "'Serial Killer', 'Trap'). For each kill also set `by` to the player whose action killed them "
        "(the trap's owner for a trap) and katana=true for the Katana attack; these are recorded for "
        "analysis, never shown. Don't tell() deaths to all. Code tells each player who dies tonight that they "
        "were attacked and died, with the kill's cause, at the end of the night; you tell every attacked player who "
        "survived (R20 step 5). "
        "Tell each role-blocked player that they were role-blocked, even one with no night action or who chose not to "
        "act (R9); a role-blocker learns only whether the "
        "block failed because its target can't be role-blocked (R9). "
        "Write private results in the present, about tonight ('You were role-blocked tonight'), never 'last "
        "night': they are delivered at the end of this night. "
        "Every player who used an ability gets a private result line, even when nothing "
        "else happened (e.g. 'You went on alert. 1 alert token left.'), stating any tokens they have left, "
        "except where a role note below says otherwise (e.g. code tells them, so don't tell() them a second result). "
        "Code tells the Yakuza which actions each of them chose and the Katana's holder and target (R8), so don't "
        "tell() them that; role-blocked Yakuza's Katana votes still count. Only the attacker learns whether the "
        "Katana attack succeeded: tell them. Update token counts for any "
        "tokens spent. "
        "Before end_phase, call record_visits once with every visit that happened tonight (R6, R20 steps 1-2), "
        "as [visitor, target] pairs, a self-visit as [X, X] (an empty list if there were none). Easy to miss: the "
        "Katana holder visits the Katana target (R8) besides any visit from their own role's action; automatic "
        "visits (the Ex-Con's); a Seer's chosen pair is a visit to both players. Leave out the actions of "
        "role-blocked players, Astral Visits and actions that target no player. The submitted actions above "
        "already show any swap (R23), so record each visit to the player it landed on.\n\n"
        + role_notes(game)
    )
    before = snapshot(game.full_state())
    wills = {p.name: p.last_will for p in game.alive()}
    transcript = moderator.run_phase(instructions)
    if checker:
        checker.submit(game.day, instructions, before, snapshot(transcript), snapshot(game.full_state()),
                       moderator=moderator.model)
    game.resolve_revenge(alive_at_start)
    game.run_night_end_hooks()  # after revenge: a Cardinal it kills curses this same night
    tell_night_deaths(game, alive_at_start)
    tell_yakuza_summary(game, actions, katana, yakuza_at_start)
    # A forged will and a Mortician's clean only take effect if their target died tonight; the moderator may
    # apply them before knowing (any op order is fine), so survivors get theirs back.
    for p in game.alive():
        undone = []
        if p.name in wills and p.last_will != wills[p.name]:
            p.last_will = wills[p.name]
            undone.append("last will")
        if p.status.pop(Status.CLEANED, None) is not None:
            undone.append("cleaned")
        if undone:
            game.log.write("night_effects_undone", day=game.day, player=p.name, undone=undone)
    game.pass_katana()
    game.day += 1


def tell_night_deaths(game: Game, alive_at_start: set[str]) -> None:
    """Rules R3, R20 step 5: each player who died tonight learns they were attacked and by what. Moderators left it
    out for about one victim in ten (moderator accuracy audit, Oct 11 2026), so code sends it."""
    for p in game.players:
        if p.name in alive_at_start and not p.alive and p.death and p.death["phase"] == "night" \
                and p.death["day"] == game.day:
            game.tell([p.name], f"You were attacked tonight ({p.death['cause']}) and died.")


def describe_choice(a: dict) -> str:
    """A teammate's chosen night action for the Yakuza summary (R8), as chosen (a swap stays hidden, R23)."""
    if not a.get("act"):
        return "no action"
    text = "to act"
    if a.get("target"):
        text += f" on {a['target']}" + (f" and {a['second_target']}" if a.get("second_target") else "")
    if a.get("guessed_role"):
        text += f", naming {a['guessed_role']}"
    if a.get("tokens_to_spend"):
        text += f", spending {a['tokens_to_spend']} token(s)"
    return text + (f' ("{a["details"]}")' if a.get("details") else "")


def tell_yakuza_summary(game: Game, actions: dict[str, dict], katana: dict, yakuza_at_start: list[str]) -> None:
    """Rules R8: at the end of the night each Yakuza learns the actions the other Yakuza chose, not their results or
    blocks. Code writes it from the submitted actions; moderators worded it two ways for a blocked teammate and
    misnamed the holder after a move (moderator accuracy audit, Oct 11 2026)."""
    living = [y.name for y in game.yakuza()]
    if len(yakuza_at_start) < 2 or not living:
        return
    chosen = {n: as_chosen(actions.get(n, {})) for n in yakuza_at_start}
    votes = [chosen[n].get("katana_vote_target") for n in yakuza_at_start]
    target = katana.get("attack") and next((t for t in set(votes) if t and majority(votes.count(t), len(votes))),
                                           katana["attack"])
    holder = katana.get("holder")
    line = (f"{holder} holds the Katana" + (f" (moved from {katana['moved_from']})" if katana.get("moved_from") else "")
            + (f" and chose to attack {target}." if target else ", with no Katana attack."))
    for name in living:
        others = [f"{n} ({game.player(n).role}) chose {describe_choice(chosen[n])}" for n in yakuza_at_start
                  if n != name]
        game.tell([name], f"Yakuza night summary: {line} " + "; ".join(others) + ".")


def swap_text(game: Game, katana: dict) -> str:
    """Tonight's swaps for the moderator (rules R23). The JSON above already has them applied, yet a moderator swapped
    the Katana attack back onto the player it was aimed at (game_20261011_074934_1113, Night 3), so this says so."""
    swaps = swaps_tonight(game)
    if not swaps:
        return ""
    pairs = "; ".join(f"{by} swapped {x} and {y}" for by, x, y in swaps)
    attack = f" The Katana attack lands on {katana['attack']}." if katana.get("attack") else ""
    return (f"Swaps tonight (R23): {pairs}. Code has ALREADY applied them: every target, second_target and the Katana "
            f"vote result above is the player the action lands on (the user's own pick is kept in chosen_*), so "
            f"resolve them exactly as given and don't swap anything again.{attack}\n")


def snapshot(x):
    """A deep copy, for a night check that reads it in another thread while the game goes on."""
    return json.loads(json.dumps(x, default=str))


def role_notes(game: Game) -> str:
    """Reminders from roles/*.py for roles in this game (alive or dead, e.g. a dead Trapper's traps)."""
    notes = [logic(r).night_note for r in sorted({p.role for p in game.players}) if logic(r).night_note]
    if not notes:
        return ""
    return ("Also handle these roles' effects, using random_choice for anything random:\n"
            + "\n".join(f"- {n}" for n in notes))


def yakuza_chat(game: Game, players: Players, rounds: int, topic: str) -> None:
    """Free Yakuza chat in seat order (rules R8). Ends early once everyone says they're ready."""
    yakuza = game.yakuza()
    names = [y.name for y in yakuza]
    schema = obj(message=nullable(STR), ready=BOOL)
    for rnd in range(1, rounds + 1):
        ready = []
        for y in yakuza:
            out = players.ask(
                y, f"It is Night {game.day}. Yakuza chat, round {rnd} of at most {rounds}. {topic} "
                f"Send a message (max {YAKUZA_MESSAGE_WORDS} words; longer is truncated) or null. Set "
                "ready=true if you have nothing more to discuss; chat ends when everyone is ready.",
                schema, {"message": None, "ready": True}, step="yakuza_chat", rnd=rnd)
            if (msg := out.get("message") or "").strip():
                msg = cap_words(msg, YAKUZA_MESSAGE_WORDS)
                game.emit(f"{y.name} (Yakuza chat): {msg}", names, cat=YAKUZA_CHAT, speaker=y.name, message=msg)
            ready.append(out.get("ready", True))
        if all(ready):
            return


def katana_majority_note(game: Game) -> str:
    """Rules R8, spelled out for the Yakuza: players were surprised that one missing vote of two
    cancelled the attack."""
    n = len(game.yakuza())
    need = n // 2 + 1
    both = " (with two of you, both must agree)" if n == 2 else ""
    return (f"There is no attack unless at least {need} of the {n} living Yakuza vote for the same target{both}. "
            f"The holder vote is separate: the Katana moves only if at least {need} vote for the same new holder, "
            "and otherwise the current holder keeps it and makes any attack.")


NO_MAJORITY = "no majority on a target; no attack"  # tally_katana's note when the Yakuza get a revote


def tally_katana(game: Game, actions: dict[str, dict]) -> dict:
    """Rules R8: the Katana holder and target each need a strict majority of living Yakuza."""
    yakuza = [y.name for y in game.yakuza()]
    if not yakuza:
        return {"attack": None, "holder": game.katana_holder}
    holders = [actions.get(y, {}).get("katana_vote_holder") for y in yakuza]
    targets = [actions.get(y, {}).get("katana_vote_target") for y in yakuza]
    holder = next((h for h in set(holders) if h and majority(holders.count(h), len(yakuza))), None)
    target = next((t for t in set(targets) if t and majority(targets.count(t), len(yakuza))), None)
    # The two choices are separate: a holder majority moves the Katana whatever happens to the attack.
    # moved_from: the moderator wrote "X kept the Katana" after it moved, seeing only the new holder.
    moved = {"moved_from": game.katana_holder} if holder and holder != game.katana_holder else {}
    game.katana_holder = holder or game.katana_holder
    if target is not None:
        return {"attack": target, "holder": game.katana_holder, **moved, "attack_level": "Standard"}
    if majority(targets.count(None), len(yakuza)):
        return {"attack": None, "holder": game.katana_holder, **moved, "note": "the Yakuza agreed not to attack"}
    return {"attack": None, "holder": game.katana_holder, **moved, "note": NO_MAJORITY}
