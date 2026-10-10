"""Cardinal: a Divine Attack on a random Good player at the end of the night they die, or of the night after
the Day they die."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import Alignment, RoleLogic, register

CURSES = "cardinal_curses"  # game.role_state key: dead Cardinals whose curse strikes at the end of the night

if TYPE_CHECKING:
    from state import Game, Player


@register("Cardinal")
class Cardinal(RoleLogic):
    # The moderator drew and killed a curse victim itself during the night in game_20261009_212707_751277,
    # and code then dealt the real curse at dawn: two victims.
    night_note = ("A Cardinal who died today or dies tonight: code deals their Divine Attack on a random Good "
                  "player after your resolution, at the end of the night. Don't draw or kill a victim yourself.")

    def on_death(self, game: Game, p: Player, guilty_voters: list[str] | None) -> None:
        game.role_state.setdefault(CURSES, []).append(p.name)

    def at_night_end(self, game: Game) -> None:
        # Kevin, Oct 10: the curse ends the night rather than starting the Day, so it plainly counts as a night
        # death (stall rule R14, wills R13). A Cardinal the curse kills curses in turn, the same night.
        while curses := game.role_state.pop(CURSES, []):
            for cardinal in curses:
                good = [q.name for q in game.alive() if q.info.alignment is Alignment.GOOD]
                if good:
                    victim = game.rng.choice(good)
                    game.log.write("cardinal", victim=victim)
                    game.kill(victim, "Cardinal's curse", by=cardinal)  # by: for deaths-by-role analysis
