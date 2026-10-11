"""Accountant: learns a player's total token count at the end of the night, after the night's token changes (a
Magpie's steal included). The moderator records the audit; code tells the count."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RecordedAction, RoleLogic, register, true_tokens

if TYPE_CHECKING:
    from state import Game, Player

TONIGHT = "accountant_audits"  # game.role_state: {day: [(accountant, target)]}, told at the end of the night


@register("Accountant")
class Accountant(RoleLogic):
    code_tells_user = True
    night_end_order = 1  # after every token change of the night (a Magpie's steal)
    action = RecordedAction("audit", "audits player",
                            "code tells them the target's total token count at the end of the night", visit=True,
                            note="Record it before or after this night's set_tokens changes: either is fine.")

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        assert target
        game.role_state.setdefault(TONIGHT, {}).setdefault(game.day, []).append((by.name, target.name))

    def at_night_end(self, game: Game) -> None:
        # rules, Accountant: the true total (R19), so a Roleplayer shows 0; before any role change at dawn
        for name, target in game.role_state.get(TONIGHT, {}).pop(game.day, []):
            n = sum(true_tokens(game.player(target)).values())
            game.tell([name], f"Your audit: {target} has {n} token{'' if n == 1 else 's'} in total.")
