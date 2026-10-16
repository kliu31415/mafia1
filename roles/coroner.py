"""Coroner: spends a token to learn a dead player's role."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RecordedAction, RoleLogic, Status, random_role, register, seen_role, tokens_left_text

if TYPE_CHECKING:
    from state import Game, Player


@register("Coroner")
class Coroner(RoleLogic):
    roleplayer = "code"  # a random role (the true one if it is public)
    code_tells_user = True
    action = RecordedAction("examine", "examines dead player (code tells them the dead player's role)",
                            "code tells them the role and tokens left", token="coroner", target="dead",
                            note="The target must have died before the night began. It is an Astral Visit, not a "
                                 "visit (R6): nothing that reacts to visits sees it.")

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        assert target
        self.tell_result(game, by, target, seen_role(game, target))

    def fake_carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        assert target
        self.tell_result(game, by, target, random_role(game, target))  # a clean was announced, so it shows too

    @staticmethod
    def tell_result(game: Game, by: Player, target: Player, role: str) -> None:
        cleaned = target.status.get(Status.CLEANED)  # rules: Mortician
        found = ("their body was cleaned by a Mortician, so you learned nothing more" if cleaned
                 else f"their role was {role}")
        game.tell([by.name], f"You examined {target.name}: {found}. {tokens_left_text(by, 'coroner')}.")
