"""Cardinal: a Divine Attack on a random Good player at the beginning of the day after they die."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import Alignment, RoleLogic, register

CURSES = "cardinal_curses"  # game.role_state key: dead Cardinals whose curse strikes at the next dawn

if TYPE_CHECKING:
    from state import Game, Player


@register("Cardinal")
class Cardinal(RoleLogic):
    def on_death(self, game: Game, p: Player, guilty_voters: list[str] | None) -> None:
        game.role_state.setdefault(CURSES, []).append(p.name)

    def at_dawn(self, game: Game) -> None:
        for cardinal in game.role_state.pop(CURSES, []):
            good = [q.name for q in game.alive() if q.info.alignment is Alignment.GOOD]
            if good:
                victim = game.rng.choice(good)
                game.log.write("cardinal", victim=victim)
                game.kill(victim, "Cardinal's curse", by=cardinal)  # by: for deaths-by-role analysis
