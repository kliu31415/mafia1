"""The night phase: Yakuza chat, night actions, the Katana vote, then moderator resolution."""

import json

from players import BOOL, Players, STR, name_enum, night_action_schema, nullable, obj, truncate_words, word_count
from roles import Alignment
from state import Game, majority
from moderator import Moderator


YAKUZA_CHAT_ROUNDS = 3
YAKUZA_MESSAGE_WORDS = 200  # Yakuza chat is free but each message is capped at this length


def run_night(game: Game, players: Players, moderator: Moderator) -> None:
    game.phase = "night"
    game.emit(f"Night {game.day} begins.")
    if len(game.yakuza()) > 1:
        yakuza_chat(game, players, YAKUZA_CHAT_ROUNDS,
                    "Discuss tonight's plan: who holds the Katana, who it attacks, and your other actions.")

    actors = [p for p in game.alive() if p.info.acts_at_night or p.info.alignment is Alignment.EVIL]
    jobs = []
    for p in actors:
        task = (f"It is Night {game.day}. Choose your night action for your role, following the rules. "
                "Set act=false to do nothing. Fill only the fields your role needs.")
        if p.info.alignment is Alignment.EVIL:
            task += " Also vote on who should hold the Katana and who the Katana should attack (or null)."
        jobs.append((p, task, night_action_schema(game, p), {"act": False}))
    actions = dict(zip([p.name for p in actors], players.ask_many(jobs)))
    game.log.write("night_actions", day=game.day, actions=actions, roles={p.name: p.role for p in actors})

    katana = tally_katana(game, actions)
    yakuza = game.yakuza()
    if katana["attack"] is None and len(yakuza) > 1:
        # No majority: show the votes, one more round of chat, then a Katana-only revote.
        votes = "; ".join(f"{y.name}: holder {actions[y.name].get('katana_vote_holder')}, target "
                          f"{actions[y.name].get('katana_vote_target')}" for y in yakuza)
        game.emit(f"The Katana vote had no majority, so there would be no attack. Votes: {votes}.",
                  [y.name for y in yakuza])
        yakuza_chat(game, players, 1, "Agree on the Katana holder and target before the revote.")
        names = game.alive_names()
        revote_schema = obj(thoughts=STR, katana_vote_holder=name_enum([y.name for y in yakuza]),
                            katana_vote_target=nullable(name_enum(names)))
        outs = players.ask_many([(y, "Revote on the Katana holder and the Katana target (or null).",
                                  revote_schema, {"katana_vote_holder": y.name, "katana_vote_target": None})
                                 for y in yakuza])
        for y, out in zip(yakuza, outs):
            actions[y.name].update(katana_vote_holder=out["katana_vote_holder"],
                                   katana_vote_target=out["katana_vote_target"])
        katana = tally_katana(game, actions)
    game.log.write("katana", day=game.day, result=katana)
    moderator.run_phase(
        f"Resolve Night {game.day}. Submitted night actions (JSON, keyed by player):\n"
        f"{json.dumps(actions, indent=1)}\n\nKatana vote result: {json.dumps(katana)}\n\n"
        "Resolve all actions simultaneously per the rules (visits, role-blocks, attack vs defense, "
        "investigation results, Katana appearing Not Evil, Fabricator framing, etc). Use apply_changes "
        "for deaths and token/status changes, tell() for each private result, and end_phase when done. "
        "Deaths you apply are announced publicly at dawn automatically, including the kill's cause, so "
        "make the cause just the source as the rules allow it to be known (e.g. 'Katana', 'Vigilante', "
        "'Serial Killer', 'Trap'); don't tell() deaths to all. Tell each role-blocked player that they "
        "were role-blocked. "
        "Jester/Executioner revenge attacks are handled by code after you finish. Tell all Yakuza which "
        "actions each Yakuza performed but not the results; only the attacker learns whether the "
        "Katana attack succeeded.\n\n"
        "Don't forget effects that happen without a submitted action, using random_choice for anything "
        "random: the Seer's two random players each night (unless they spent a token to choose); the "
        "Ex-Con's random visit; the Fortune Teller's two numbers about tonight's visits (tell them now; "
        "they read them at the start of the day); Trapper traps that persist across nights (track them "
        "with set_status); Arsonist douses (set_status 'doused'); and a Roleplayer's fake but plausible "
        "results for the role they believe they have (their status 'fake_role'). Use the prosecute, "
        "rig_vote and puppet ops for Prosecutor, Clerk and Puppeteer actions, and update token counts."
    )
    game.resolve_revenge()
    game.day += 1


def yakuza_chat(game: Game, players: Players, rounds: int, topic: str) -> None:
    """Free Yakuza chat in seat order. Ends early once everyone says they're ready."""
    yakuza = game.yakuza()
    names = [y.name for y in yakuza]
    schema = obj(thoughts=STR, message=nullable(STR), ready=BOOL)
    for rnd in range(1, rounds + 1):
        ready = []
        for y in yakuza:
            out = players.ask(
                y, f"It is Night {game.day}. Yakuza chat, round {rnd} of at most {rounds}. {topic} "
                f"Send a message (max {YAKUZA_MESSAGE_WORDS} words; longer is truncated) or null. Set "
                "ready=true if you have nothing more to discuss; chat ends when everyone is ready.",
                schema, {"thoughts": "", "message": None, "ready": True})
            if msg := out.get("message"):
                if word_count(msg) > YAKUZA_MESSAGE_WORDS:
                    msg = truncate_words(msg, YAKUZA_MESSAGE_WORDS)
                game.emit(f"{y.name} (Yakuza chat): {msg}", names)
            ready.append(out.get("ready", True))
        if all(ready):
            return


def tally_katana(game: Game, actions: dict[str, dict]) -> dict:
    yakuza = [y.name for y in game.yakuza()]
    if not yakuza:
        return {"attack": None, "holder": game.katana_holder}
    holders = [actions.get(y, {}).get("katana_vote_holder") for y in yakuza]
    targets = [actions.get(y, {}).get("katana_vote_target") for y in yakuza]
    holder = next((h for h in set(holders) if h and majority(holders.count(h), len(yakuza))), None)
    target = next((t for t in set(targets) if t and majority(targets.count(t), len(yakuza))), None)
    if holder is None or target is None:
        return {"attack": None, "holder": game.katana_holder, "note": "no majority agreement; no attack"}
    game.katana_holder = holder
    return {"attack": target, "holder": holder, "attack_level": "Standard"}
