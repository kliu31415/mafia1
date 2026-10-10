"""Arsonist: douses players, then ignites them all at once. Code tells doused players who aren't Good."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import Alignment, RoleLogic, Status, register

if TYPE_CHECKING:
    from state import Game

TOLD = "arsonist_told_doused"  # role_state: players told they're doused, until an ignite clears their douse


@register("Arsonist")
class Arsonist(RoleLogic):
    night_note = ("Track Arsonist douses with set_status key 'doused' value true. An ignite uses up every douse: "
                  "clear 'doused' on everyone it hit, survivors included (rules: Arsonist). Don't tell anyone they "
                  "were doused: code tells the doused players who should know.")

    def at_night_end(self, game: Game) -> None:
        """Rules, Arsonist: a doused player who isn't Good learns it at the end of the night it happens."""
        from roles import ROLES
        told: list[str] = game.role_state.setdefault(TOLD, [])
        doused = {p.name for p in game.players if p.status.get(Status.DOUSED)}
        told[:] = [n for n in told if n in doused]  # an ignite cleared these, so a new douse is news again
        for p in game.alive():
            if p.name in doused and p.name not in told and ROLES[p.role].alignment is not Alignment.GOOD:
                told.append(p.name)
                game.tell([p.name], "An Arsonist doused you tonight. You stay doused until the Arsonist ignites.")
