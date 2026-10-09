"""The night phase: Yakuza chat, night actions, the Katana vote, then moderator resolution."""

import json

from players import (BOOL, Players, STR, name_enum, night_action_schema, nullable, obj, tokens_left, truncate_words,
                     word_count)
from roles import Alignment, Status, logic
from events import PHASE, YAKUZA_CHAT
from state import Game, majority
from moderator import Moderator
from night_check import NightChecker


YAKUZA_CHAT_ROUNDS = 3
YAKUZA_MESSAGE_WORDS = 200  # Yakuza chat is free but each message is capped at this length


def run_night(game: Game, players: Players, moderator: Moderator, checker: NightChecker | None = None) -> None:
    game.phase = "night"
    game.emit(f"Night {game.day} begins.", cat=PHASE)
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
    game.log.write("night_actions", day=game.day, actions=actions, roles={p.name: p.role for p in actors})

    katana = tally_katana(game, actions)
    revote: dict[str, str | None] = {}  # Yakuza -> target, if there was a revote
    yakuza = game.yakuza()
    if katana.get("note", "").startswith("no majority") and len(yakuza) > 1:
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
    game.night_actions[game.day] = actions  # shown back to each player (players.night_history)
    game.log.write("katana", day=game.day, result=katana, revote_targets=revote or None)
    instructions = (
        f"Resolve Night {game.day}. Submitted night actions (JSON, keyed by player):\n"
        f"{json.dumps(actions, indent=1)}\n\nKatana vote result: {json.dumps(katana)}\n\n"
        "Resolve all actions simultaneously per the rules, following the R20 checklist (R10; visits R6, role-blocks R9, "
        "attack vs defense R3, investigation results R19, e.g. the Katana holder and Fabricator frames). Use apply_changes "
        "for deaths and token/status changes, tell() for each private result, and end_phase when done. "
        "Deaths you apply are announced publicly at dawn automatically, including the kill's cause, so "
        "make the cause just the source as the rules allow it to be known (e.g. 'Katana', 'Vigilante', "
        "'Serial Killer', 'Trap'). For each kill also set `by` to the player whose action killed them "
        "(the trap's owner for a trap) and katana=true for the Katana attack; these are recorded for "
        "analysis, never shown. Don't tell() deaths to all. Tell each role-blocked player that they "
        "were role-blocked. Every player who used an ability gets a private result line, even when nothing "
        "else happened (e.g. 'You went on alert. 1 alert token left.'), stating any tokens they have left. "
        "Tell all Yakuza which actions each Yakuza performed but not the results; "
        "only the attacker learns whether the Katana attack succeeded. Update token counts for any "
        "tokens spent.\n\n"
        + role_notes(game)
    )
    before = snapshot(game.full_state())
    wills = {p.name: p.last_will for p in game.alive()}
    transcript = moderator.run_phase(instructions)
    if checker:
        checker.submit(game.day, instructions, before, snapshot(transcript), snapshot(game.full_state()))
    game.resolve_revenge()
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
                if word_count(msg) > YAKUZA_MESSAGE_WORDS:
                    msg = truncate_words(msg, YAKUZA_MESSAGE_WORDS)
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
    game.katana_holder = holder or game.katana_holder
    if target is not None:
        return {"attack": target, "holder": game.katana_holder, "attack_level": "Standard"}
    if majority(targets.count(None), len(yakuza)):
        return {"attack": None, "holder": game.katana_holder, "note": "the Yakuza agreed not to attack"}
    return {"attack": None, "holder": game.katana_holder, "note": "no majority on a target; no attack"}
