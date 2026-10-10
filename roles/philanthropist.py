"""Philanthropist: spends a token at night to hand another player a token of their own role's kind."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RecordedAction, RoleLogic, register

if TYPE_CHECKING:
    from state import Game, Player


@register("Philanthropist")
class Philanthropist(RoleLogic):
    code_tells_user = True
    action = RecordedAction("give_token", "hands player a token of their role's kind",
                            "code hands the recipient a token and tells them", token="philanthropy")

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        assert target
        # A Roleplayer's token kinds are their fake role's, so the gift keeps their cover.
        if kinds := sorted(target.tokens):
            kind = game.rng.choice(kinds)
            target.tokens[kind] += 1
            text = f"A Philanthropist handed you a {kind} token. You now have {target.tokens[kind]}."
        else:
            text = "A Philanthropist handed you a token, but you threw it away because you have no use for it."
        game.tell([target.name], text)
