"""Jester: wins if hanged, then a Divine Attack hits a random Guilty voter (Game.resolve_revenge)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from events import DEATH
from roles.base import RoleLogic, register

if TYPE_CHECKING:
    from state import Game, Player


@register("Jester")
class Jester(RoleLogic):
    blocks_win = False
    night_note = "Jester revenge attacks are carried out by code after you finish; don't resolve them."

    def on_death(self, game: Game, p: Player, guilty_voters: list[str] | None) -> None:
        if guilty_voters is not None:
            game.personal_winners.append(p.name)
            game.pending_revenge.append((p.name, guilty_voters))
            if game.rule_settings["flips"] != "role":  # a role that wins by leaving is revealed (Kevin, Oct 10)
                game.emit(f"{p.name} was the Jester: being hanged wins them the game.", cat=DEATH)
                game.death_record.append(f"Day {game.day}: {p.name} (Jester) won by being hanged")
