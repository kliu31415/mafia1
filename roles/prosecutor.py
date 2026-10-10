"""Prosecutor: spends a token at night to send someone straight to trial the next day."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RecordedAction, RoleLogic, register

if TYPE_CHECKING:
    from state import Game, Player


@register("Prosecutor")
class Prosecutor(RoleLogic):
    action = RecordedAction("prosecute", "prosecutes player, who goes to trial when the next day starts",
                            "code runs the trial when the next day starts", token="prosecutor", target="any")

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        assert target
        if target.name not in game.prosecutions:  # two Prosecutors on one player: one trial
            game.prosecutions.append(target.name)
