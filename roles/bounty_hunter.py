"""Bounty Hunter: three random targets; wins and leaves once two of them died by its attack or by hanging with its
Guilty vote; loses and leaves once that's out of reach. The moderator resolves its one Strong Attack."""

from __future__ import annotations

from typing import TYPE_CHECKING

from events import DEATH
from roles.base import RoleLogic, Status, join_names, logic, register

if TYPE_CHECKING:
    from state import Game, Player

ROLE = "Bounty Hunter"
TARGETS, NEEDED = 3, 2
BOUNTIES = "bounties"  # game.role_state: {hunter: {"targets": [...], "claimed": [...], "lost": [...]}}


def bounty(game: Game, name: str) -> dict:
    return game.role_state.setdefault(BOUNTIES, {}).setdefault(name, {"targets": [], "claimed": [], "lost": []})


def open_targets(b: dict) -> list[str]:
    return [t for t in b["targets"] if t not in b["claimed"] and t not in b["lost"]]


@register(ROLE)
class BountyHunter(RoleLogic):
    blocks_win = False
    night_note = ("A Bounty Hunter's attack is a Strong Attack that spends its attack token: pass by=<the Bounty "
                  "Hunter> on the kill op, since code credits its bounties from the killers. Code tells it which "
                  "bounties it claimed or lost and handles its win or loss; don't tell() it about bounties.")

    def setup(self, game: Game, p: Player) -> None:
        others = [q.name for q in game.players if q is not p]
        bounty(game, p.name)["targets"] = game.rng.sample(others, min(TARGETS, len(others)))

    def briefing(self, game: Game, p: Player) -> list[str]:
        return [f"Your targets are {join_names(bounty(game, p.name)['targets'])}. You win once {NEEDED} of them "
                "have died by your attack or by hanging with your Guilty vote."]

    def on_other_death(self, game: Game, me: Player, dead: Player, guilty_voters: list[str] | None) -> None:
        b = bounty(game, me.name)
        if dead.name not in open_targets(b):
            return
        if guilty_voters is not None:  # hanged: counts with our Guilty vote, as counted (a Fixer may reverse it)
            claimed = me.name in guilty_voters
        else:  # a leaver has no death record: lost
            claimed = me.name in (dead.death or {}).get("killers", [])
        (b["claimed"] if claimed else b["lost"]).append(dead.name)
        game.tell([me.name], f"Your bounty on {dead.name} is claimed." if claimed else
                  f"{dead.name} died other than by your attack or a hanging you voted Guilty in: that bounty is "
                  "lost.")
        if game.phase != "night":  # night deaths are simultaneous (R10): settled at the end of the night
            settle(game, me)

    def at_night_end(self, game: Game) -> None:
        for name, b in game.role_state.get(BOUNTIES, {}).items():
            me = game.player(name)
            if me.role != ROLE or me.status.get(Status.LEFT) or name in game.personal_winners:
                continue
            if not me.alive and died_tonight(game, me):
                # Killed tonight, so on_other_death skipped any target killed after it: deaths are simultaneous,
                # so its attack still claims a target who died tonight too.
                for t in open_targets(b):
                    if not (q := game.player(t)).alive and died_tonight(game, q):
                        b["claimed" if name in (q.death or {}).get("killers", []) else "lost"].append(t)
            if me.alive or died_tonight(game, me):
                settle(game, me)

    def at_dawn(self, game: Game) -> None:  # a target killed after at_night_end (e.g. by a curse)
        for name in game.role_state.get(BOUNTIES, {}):
            if (me := game.player(name)).alive and me.role == ROLE:
                settle(game, me)


def died_tonight(game: Game, p: Player) -> bool:
    d = p.death or {}
    return d.get("day") == game.day and d.get("phase") == "night"


def settle(game: Game, me: Player) -> None:
    """Win (and leave, if alive) once NEEDED bounties are claimed; lose and leave once that's out of reach."""
    b = bounty(game, me.name)
    won = len(b["claimed"]) >= NEEDED
    if not won and len(b["claimed"]) + len(open_targets(b)) >= NEEDED:
        return
    if won:
        game.personal_winners.append(me.name)
        game.log.write("bounty_won", player=me.name, claimed=b["claimed"], day=game.day, phase=game.phase)
    if not me.alive:  # a dead winner stays hidden like any death (R12); a dead loser needs nothing
        return
    me.alive = False  # leaves the game; not a death
    me.status[Status.LEFT] = True
    game.log.write("left", player=me.name, day=game.day, phase=game.phase)
    text = (f"{me.name} was the Bounty Hunter and " + ("claimed their bounties. They win" if won else
            "can no longer claim enough bounties. They lose") + " and leave the game."
            + (f" Their last will: \"{me.last_will}\"" if me.last_will else ""))  # rules R12
    if game.phase == "night":
        game.pending_announcements.append(text)
    else:
        game.emit(text, cat=DEATH)
    game.death_record.append(f"Day {game.day}: {me.name} (Bounty Hunter) {'won' if won else 'lost'} and left the game")
    for q in game.alive():  # leaving counts as a death for anyone targeting this one (an Executioner, ...)
        logic(q.role).on_other_death(game, q, me, None)
