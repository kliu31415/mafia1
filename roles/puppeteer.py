"""Puppeteer: spends a token at night to chat as someone else the next day."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RecordedAction, RoleLogic, note_swap_move, register

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
        note_swap_move(game, by, target, "puppeting")  # rules R23: told at dawn
        if target is not by:  # puppeting yourself changes nothing (the token is still spent)
            game.puppets_next[target.name] = by.name

    def on_death(self, game: Game, p: Player, guilty_voters: list[str] | None) -> None:
        # Killed mid-Day (a Sniper shot): a dead player can't act, so its puppets speak for themselves from now on, as
        # when the Puppeteer dies overnight (rules R21).
        if game.phase != "day":
            return
        freed = [puppet for puppet, by in game.puppets.items() if by == p.name]
        for puppet in freed:
            del game.puppets[puppet]
        if freed:
            game.log.write("puppeting_lapsed", player=p.name, puppets=freed)
