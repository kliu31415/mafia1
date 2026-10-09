"""Jester: wins if hanged, then a Divine Attack hits a random Guilty voter (Game.resolve_revenge)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RoleLogic, register

if TYPE_CHECKING:
    from state import Game, Player


@register("Jester")
class Jester(RoleLogic):
    blocks_win = False
    night_note = "Jester revenge attacks are carried out by code after you finish; don't resolve them."

    def on_death(self, game: Game, p: Player, guilty_voters: list[str] | None) -> None:
        if guilty_voters is not None:
            game.personal_winners.append(p.name)
            game.pending_revenge.append((p.name, guilty_voters))
