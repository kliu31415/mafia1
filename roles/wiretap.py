"""Wiretap: a Yakuza who reads the contents of every Day private message (Game.pm_listeners)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RoleLogic, register

if TYPE_CHECKING:
    from state import Game, Player


@register("Wiretap")
class Wiretap(RoleLogic):
    def hears_pm(self, game: Game, me: Player, speaker: str, to: str) -> bool:
        return True

    def briefing(self, game: Game, p: Player) -> list[str]:
        return ["You read the contents of every private message sent during the Day, between any two players. "
                "Nobody else knows this, and role-blocks don't stop it."]
