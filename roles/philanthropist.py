"""Philanthropist: spends a token at night to hand another player a token of their own role's kind."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RoleLogic, register, spend_token, token_user_error

if TYPE_CHECKING:
    from state import Game


@register("Philanthropist")
class Philanthropist(RoleLogic):
    night_note = ("A Philanthropist who spent a token (and wasn't role-blocked): use the give_token op, which spends "
                  "it; code hands the recipient a token and tells them. Tell the Philanthropist nothing about it.")
    code_tells_user = True
    ops = {"give_token": ({"player", "by"}, set(), "{op:'give_token', player, by}: the Philanthropist `by` hands "
                                                   "player a token of their role's kind (spends a token)")}

    def check_op(self, game: Game, change: dict) -> str | None:
        by, to = game.player(change["by"]), game.player(change["player"])
        if error := token_user_error(game, by.name, "Philanthropist", "philanthropy"):
            return error
        if to is by:
            return "a Philanthropist hands tokens to other players only"
        return None

    def apply_op(self, game: Game, change: dict) -> None:
        spend_token(game, change["by"], "philanthropy")
        to = game.player(change["player"])
        # A Roleplayer's token kinds are their fake role's, so the gift keeps their cover.
        if kinds := sorted(to.tokens):
            kind = game.rng.choice(kinds)
            to.tokens[kind] += 1
            text = f"A Philanthropist handed you a {kind} token. You now have {to.tokens[kind]}."
        else:
            text = "A Philanthropist handed you a token, but you threw it away because you have no use for it."
        game.tell([to.name], text)
