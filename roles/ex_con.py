"""Ex-Con: Good, but appears Evil to alignment checks (Sheriff, Seer), and visits a random player each night."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RoleLogic, register

if TYPE_CHECKING:
    from state import Game, Player


@register("Ex-Con")
class ExCon(RoleLogic):
    night_note = ("The Ex-Con's random visit is drawn by code: it is in the night's actions as an automatic action "
                  "with its target (the Ex-Con isn't told whom). A role-block stops it (no visit). "
                  "Like a framed player, the Ex-Con has the Evil "
                  "alignment to every role that learns alignments (Sheriff, Seer); roles that learn visits or exact "
                  "roles see it as it is.")  # rules Ex-Con

    def automatic_action(self, game: Game, p: Player) -> dict | None:
        others = [q.name for q in game.alive() if q is not p]
        return {"act": True, "target": game.rng.choice(others), "details": "random visit"} if others else None
