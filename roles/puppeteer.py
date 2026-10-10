"""Puppeteer: spends a token at night to chat as someone else the next day."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import Alignment, RoleLogic, register, spend_token, token_user_error

if TYPE_CHECKING:
    from state import Game


@register("Puppeteer")
class Puppeteer(RoleLogic):
    night_note = "A Puppeteer's puppet: use the puppet op (code swaps who chats tomorrow)."
    ops = {"puppet": ({"player", "by"}, set(), "{op:'puppet', player, by}: the Puppeteer `by` spends a "
                                                 "token; player is puppeted by them tomorrow")}

    def check_op(self, game: Game, change: dict) -> str | None:
        by = game.player(change["by"])
        if error := token_user_error(game, by.name, "Puppeteer", "puppet"):
            return error
        if change["player"] == by.name:
            return "a Puppeteer can't puppet themselves"
        if game.player(change["player"]).info.alignment is Alignment.EVIL:
            return "a Puppeteer can't puppet another Yakuza"
        return None

    def apply_op(self, game: Game, change: dict) -> None:
        spend_token(game, change["by"], "puppet")
        game.puppets_next[change["player"]] = change["by"]
