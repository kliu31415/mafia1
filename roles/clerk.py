"""Clerk: spends a token at night to rig the next day's trials."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RecordedAction, RoleLogic, register

if TYPE_CHECKING:
    from state import Game, Player


@register("Clerk")
class Clerk(RoleLogic):
    action = RecordedAction("rig_vote", "rigs tomorrow's trials to execute the accused regardless of the vote",
                            "code executes tomorrow's accused regardless of the vote", token="clerk", target="")

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        game.rigged_day = game.day + 1
