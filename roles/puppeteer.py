"""Puppeteer: spends a token at night to chat as someone else the next day."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import Alignment, RecordedAction, RoleLogic, register

if TYPE_CHECKING:
    from state import Game, Player


@register("Puppeteer")
class Puppeteer(RoleLogic):
    action = RecordedAction("puppet", "puppets player tomorrow", "code swaps who chats tomorrow", token="puppet")

    def target_error(self, game: Game, by: Player, target: Player | None) -> str | None:
        return "a Puppeteer can't puppet another Yakuza" if target and target.info.alignment is Alignment.EVIL \
            else None

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        assert target
        game.puppets_next[target.name] = by.name
