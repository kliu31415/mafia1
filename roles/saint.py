"""Saint: an Outsider whose hanging loses the game for the Village at once (the Yakuza win)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from events import DEATH
from roles.base import RoleLogic, register

if TYPE_CHECKING:
    from state import Game, Player

HANGED = "saint_hanged"  # game.role_state: the hanged Saint, whose hanging decided the game
WINNER = "Yakuza"  # rules (Saint): the faction that wins when the Saint is hanged


@register("Saint")
class Saint(RoleLogic):
    def briefing(self, game: Game, p: Player) -> list[str]:
        return ["If you are hanged, the Village loses at once and the Yakuza win. Other deaths do nothing special."]

    def on_death(self, game: Game, p: Player, guilty_voters: list[str] | None) -> None:
        if guilty_voters is None or HANGED in game.role_state:  # rules (Saint): only a hanging
            return
        game.role_state[HANGED] = p.name
        game.log.write("saint_hanged", player=p.name, day=game.day)
        # Revealed even with hidden flips, like a Jester's win: everyone must see why the game ended.
        text = f"{p.name} was the Saint: hanging them loses the game for the Village, and the Yakuza win."
        game.emit(text, cat=DEATH)
        game.death_record.append(f"Day {game.day}: {p.name} (Saint) was hanged, so the Yakuza win")

    def decides_game(self, game: Game) -> str | None:
        return WINNER if HANGED in game.role_state else None
