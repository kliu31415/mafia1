"""Informant: a Yakuza who sees how every player voted in each secret trial (day.run_trial)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RoleLogic, register

if TYPE_CHECKING:
    from state import Game, Player


@register("Informant")
class Informant(RoleLogic):
    def sees_trial_votes(self, game: Game, me: Player) -> bool:
        return True

    def briefing(self, game: Game, p: Player) -> list[str]:
        return ["You see how every player voted in each Guilty/Innocent trial, right after the vote. Nobody else "
                "knows this, the other Yakuza aren't told the votes, and role-blocks don't stop it."]
