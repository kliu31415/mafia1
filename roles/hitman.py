"""Hitman: a Neutral with a Basic Attack every night; wins and leaves once its attacks have killed 2 Good players,
loses and leaves as soon as one kills a player who isn't Good. The moderator resolves the attack; code counts the
kills (from each death's killers) and handles the win or loss."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import Alignment, RoleLogic, Status, leave_game, register
from roles.bounty_hunter import died_tonight

if TYPE_CHECKING:
    from state import Game, Player

ROLE = "Hitman"
NEEDED = 2  # rules (Hitman): Good players its attacks must kill
KILLS = "hitman_kills"  # game.role_state: {hitman: {"good": [...], "other": [...]}}


def kills(game: Game, name: str) -> dict:
    return game.role_state.setdefault(KILLS, {}).setdefault(name, {"good": [], "other": []})


@register(ROLE)
class Hitman(RoleLogic):
    blocks_win = False
    night_end_order = 2  # after other end-of-night deaths (a curse), so leaving comes last
    night_note = ("A Hitman's attack is a Basic Attack: pass by=<the Hitman> on the kill op, since code counts its "
                  "kills from the killers. Code tells it whether a kill counted and handles its win or loss; don't "
                  "tell() it about that.")

    def briefing(self, game: Game, p: Player) -> list[str]:
        return [f"You win once your attacks have killed {NEEDED} Good (Village) players, and lose as soon as one "
                "kills a player who isn't Good."]

    def at_night_end(self, game: Game) -> None:
        for me in game.players:
            if (me.role != ROLE or me.status.get(Status.LEFT) or me.name in game.personal_winners
                    or not (me.alive or died_tonight(game, me))):  # only kills made while it was alive count (R10)
                continue
            k = kills(game, me.name)
            if k["other"]:  # lost earlier (and left)
                continue
            # Only its own fatal attacks count, so a Grudge's revenge after its hanging (it's dead by then) doesn't.
            new = [q for q in game.players if not q.alive and not q.status.get(Status.LEFT) and died_tonight(game, q)
                   and me.name in (q.death or {}).get("killers", []) and q.name not in k["good"] + k["other"]]
            for q in new:
                good = q.info.alignment == Alignment.GOOD  # true alignment: a Turncoat is Good, a framed player too
                k["good" if good else "other"].append(q.name)
                game.tell([me.name], f"Your attack killed {q.name}, who was Good ({len(k['good'])} of {NEEDED})."
                          if good else f"Your attack killed {q.name}, who wasn't Good: you lose.")
            if new:
                settle(game, me, k)


def settle(game: Game, me: Player, k: dict) -> None:
    """Lose (and leave, if alive) after killing a non-Good player; win (and leave, if alive) after NEEDED Good."""
    won = not k["other"] and len(k["good"]) >= NEEDED
    if not won and not k["other"]:
        return
    if won:
        game.personal_winners.append(me.name)
    game.log.write("hitman_won" if won else "hitman_lost", player=me.name, good=k["good"], other=k["other"],
                   day=game.day)
    if not me.alive:  # a dead winner stays hidden like any death (R12); a dead loser needs nothing
        return
    leave_game(game, me, won)
    text = (f"{me.name} was the Hitman. They {'win' if won else 'lose'} and leave the game."
            + (f" Their last will: \"{me.last_will}\"" if me.last_will else ""))  # rules R12
    game.pending_announcements.append(text)  # at the end of the night: announced with the night's deaths
