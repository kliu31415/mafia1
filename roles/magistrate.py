"""Magistrate: once per game, on one of its own Day speaking turns, calls a second session (rules R25 delay): from then
on that Day, the first hanging doesn't end the Day (R4). A call still waiting when a hanging happens takes effect
right then, so the delay never wastes it (Kevin, Oct 17 2026)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from events import ANNOUNCEMENT
from roles.base import DayAction, RoleLogic, register

if TYPE_CHECKING:
    from state import Game, Player

TOKEN = "session"
PENDING = "magistrate_pending"  # game.role_state: [caller, turns left] calls waiting for their delay (rules R25)
OPEN = "magistrate_open"  # game.role_state: the Day whose next hanging won't end it


def announce(game: Game) -> None:
    text = ("Someone has called a second session: today the first execution doesn't end the Day. The one after it "
            "does, as usual.")
    game.emit(text, cat=ANNOUNCEMENT, message=text)


@register("Magistrate")
class Magistrate(RoleLogic):
    def day_action(self, game: Game, p: Player) -> DayAction | None:
        if not p.tokens.get(TOKEN, 0) or game.role_state.get(PENDING) or game.role_state.get(OPEN) == game.day:
            return None
        return DayAction({"act": {"type": "boolean"}},
                         "As the Magistrate you may call a second session this turn (once per game): act true. After a "
                         "random number of speaking turns (possibly right after this one; rules R25) everyone is told, "
                         "never by whom, that today the first execution doesn't end the Day, so a second player can be "
                         "hanged today. If a hanging happens before then, your call takes effect at that moment and "
                         "the Day goes on. If you die before it takes effect, it doesn't; if the Day ends with no "
                         "hanging before it takes effect, you get the token back. Leave act false not to call one.")

    def carry_out_day_action(self, game: Game, p: Player, answer: dict) -> None:
        if not answer.get("act") or self.day_action(game, p) is None:
            return
        p.tokens[TOKEN] -= 1
        # Rules R25: a random delay of 0 to n-1 more speaking turns, counted from the end of this one.
        delay = game.rng.randint(0, len(game.alive_names()) - 1)
        game.role_state[PENDING] = [[p.name, delay]]
        game.log.write("session_called", player=p.name, day=game.day, delay=delay)
        game.tell([p.name], "You called a second session. It takes effect after a random number of speaking turns "
                  "(possibly right after this one), or at once if a hanging happens first; you'll be told.")

    def after_day_turn(self, game: Game, p: Player) -> None:
        calls = game.role_state.get(PENDING)
        if not calls:
            return
        caller, left = calls[0]
        if left > 0:
            calls[0][1] = left - 1
            return
        self.take_effect(game, caller, announced=True)

    def take_effect(self, game: Game, caller: str, announced: bool) -> bool:
        """Opens the session for today unless the caller died since the call (rules R25). Returns whether it did."""
        del game.role_state[PENDING]
        if not game.player(caller).alive:
            game.log.write("session_dropped", player=caller, day=game.day)
            return False
        game.role_state[OPEN] = game.day
        game.log.write("session_open", player=caller, day=game.day)
        if announced:
            announce(game)
        game.tell([caller], "Your second session has taken effect.")
        return True

    def hanging_keeps_day_going(self, game: Game) -> bool:
        if calls := game.role_state.get(PENDING):  # still waiting: it takes effect now (Kevin, Oct 17 2026)
            if not self.take_effect(game, calls[0][0], announced=False):
                return False
        if game.role_state.get(OPEN) != game.day:
            return False
        del game.role_state[OPEN]
        text = ("A second session was called today, so this execution doesn't end the Day. The next execution will, "
                "as usual.")
        game.emit(text, cat=ANNOUNCEMENT, message=text)
        return True

    def at_day_end(self, game: Game) -> None:
        game.role_state.pop(OPEN, None)
        calls = game.role_state.pop(PENDING, None)
        if calls and game.player(caller := calls[0][0]).alive:  # never took effect: the token comes back
            game.player(caller).tokens[TOKEN] = game.player(caller).tokens.get(TOKEN, 0) + 1
            game.log.write("session_refunded", player=caller, day=game.day)
            game.tell([caller], "The Day ended before your second session took effect, so you got your token back.")
