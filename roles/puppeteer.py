"""Puppeteer: spends a token at night to chat as someone else the next day."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RecordedAction, RoleLogic, register

if TYPE_CHECKING:
    from state import Game, Player


@register("Puppeteer")
class Puppeteer(RoleLogic):
    # Any player (Kevin, Oct 11 2026): a Yakuza or the Puppeteer itself is only ever puppeted by a Smuggler's swap
    # (R23), so refusing it would make the swap's moved action fail. Puppeting yourself changes nothing.
    action = RecordedAction("puppet", "puppets player tomorrow", "code swaps who chats tomorrow", token="puppet",
                            target="any")

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        assert target
        if target is not by:  # puppeting yourself changes nothing (the token is still spent)
            game.puppets_next[target.name] = by.name
