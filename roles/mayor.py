"""Mayor: once per game, on one of its own Day speaking turns, reveals itself; the moderator's announcement is true.
From then on its Guilty/Innocent trial votes count twice (Kevin, Oct 15 2026)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from events import ANNOUNCEMENT
from roles.base import DayAction, RoleLogic, register

if TYPE_CHECKING:
    from state import Game, Player

REVEALED = "mayor_revealed"  # game.role_state: names of Mayors who revealed themselves


def revealed(game: Game, p: Player) -> bool:
    return p.name in game.role_state.get(REVEALED, [])


@register("Mayor")
class Mayor(RoleLogic):
    def public_role(self, game: Game, p: Player) -> bool:
        return revealed(game, p)  # the announcement is true

    def briefing(self, game: Game, p: Player) -> list[str]:
        return ["Once per game, on one of your own Day speaking turns, you may reveal yourself as the Mayor: everyone "
                "is told right after that turn, and it is true. From then on each of your Guilty/Innocent trial votes "
                "counts twice (nomination votes stay one each)."]

    def day_action(self, game: Game, p: Player) -> DayAction | None:
        if revealed(game, p):
            return None
        return DayAction({"act": {"type": "boolean"}},
                         "As the Mayor you may reveal yourself this turn (once per game): act true, and right after "
                         "this turn everyone is told that you are the Mayor, which is true. From then on each of your "
                         "Guilty/Innocent trial votes counts twice. Revealing makes you a likely target for the "
                         "Yakuza. Leave act false to stay hidden.")

    def carry_out_day_action(self, game: Game, p: Player, answer: dict) -> None:
        # Not after R25's random delay: the reveal names its user, so there is nothing to hide (rules: Mayor).
        if not answer.get("act") or revealed(game, p):
            return
        game.role_state.setdefault(REVEALED, []).append(p.name)
        game.log.write("mayor_revealed", player=p.name, day=game.day)
        text = (f"{p.name} reveals that they are the Mayor, and the moderator confirms it. From now on each of their "
                "trial votes counts twice.")
        game.emit(text, cat=ANNOUNCEMENT, message=text)
        game.tell([p.name], "You revealed yourself as the Mayor: from now on each of your trial votes counts twice.")

    def trial_vote_weight(self, game: Game, p: Player, answer: dict) -> int:
        return 2 if revealed(game, p) else 1
