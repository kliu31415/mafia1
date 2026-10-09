"""Prosecutor: spends a token at night to send someone straight to trial the next day."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RoleLogic, register, token_user_error

if TYPE_CHECKING:
    from state import Game


@register("Prosecutor")
class Prosecutor(RoleLogic):
    night_note = "A Prosecutor's prosecution: use the prosecute op (code runs the trial when the next day starts)."
    ops = {"prosecute": ({"player", "by"}, set(), "{op:'prosecute', player, by}: the Prosecutor `by` spends a "
                                                   "token; player goes to trial when the next day starts")}

    def check_op(self, game: Game, change: dict) -> str | None:
        return token_user_error(game, change["by"], "Prosecutor", "prosecutor")

    def apply_op(self, game: Game, change: dict) -> None:
        game.player(change["by"]).tokens["prosecutor"] -= 1
        if change["player"] not in game.prosecutions:  # two Prosecutors on one player: one trial
            game.prosecutions.append(change["player"])
