"""Fixer: spends a token at night so one player's Guilty/Innocent votes count as the opposite the next Day."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RecordedAction, RoleLogic, register

NEXT = "fixed_next"  # game.role_state: players whose trial votes a Fixer reversed tonight
TODAY = "fixed"  # game.role_state: players whose trial votes count reversed today

if TYPE_CHECKING:
    from state import Game, Player


@register("Fixer")
class Fixer(RoleLogic):
    action = RecordedAction("fix", "fixes player's Guilty/Innocent votes tomorrow",
                            "code counts the player's trial votes tomorrow as the opposite; nobody is told",
                            token="fixer", visit=True)

    def briefing(self, game: Game, p: Player) -> list[str]:
        return ["When you spend a token on a player at night, every Guilty/Innocent vote they cast the next Day "
                "counts as the opposite. Nobody is told, not even them, and their nomination votes are unchanged."]

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        assert target
        game.role_state.setdefault(NEXT, []).append(target.name)  # rules R21: still happens if the Fixer dies

    def at_dawn(self, game: Game) -> None:
        game.role_state[TODAY] = game.role_state.pop(NEXT, [])

    def reverses_trial_vote(self, game: Game, voter: Player) -> bool:
        return voter.name in game.role_state.get(TODAY, [])
