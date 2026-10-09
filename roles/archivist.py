"""Archivist: once per game, sees the roles of a random three quarters of the other players alive when the night
began (those who died that night count)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from events import RESULT
from roles.base import RoleLogic, register

SHARE = 0.75  # rules: floor(0.75 * N) of the other players alive when the night began

if TYPE_CHECKING:
    from state import Game


@register("Archivist")
class Archivist(RoleLogic):
    roleplayer_can_fake = False  # code draws the sample
    night_note = ("An Archivist who spent their token (and wasn't role-blocked): use the archive op, which spends "
                  "the token; code shows them the sampled roles at once, as a night result.")
    ops = {"archive": ({"by"}, set(), "{op:'archive', by}: the Archivist `by` consults the archive (spends their "
                                      "token; code draws and tells the roles at once)")}

    def check_op(self, game: Game, change: dict) -> str | None:
        by = game.player(change["by"])
        if by.role != "Archivist" or not by.alive:
            return f"{by.name} is not a living Archivist"
        if by.tokens.get("archive", 0) < 1:
            return f"{by.name} has no archive token left"
        return None

    def apply_op(self, game: Game, change: dict) -> None:
        # Told at once, like other night results. The sample is everyone alive when the night began, so it's
        # the same whether the moderator applies the night's kills before or after this op.
        by = game.player(change["by"])
        by.tokens["archive"] -= 1
        others = [p for p in game.players if p is not by and (p.alive or died_tonight(game, p))]
        drawn = game.rng.sample(others, int(len(others) * SHARE))
        roles = ", ".join(sorted(p.role for p in drawn)) or "none"
        text = (f"The archive shows {len(drawn)} of the roles of the {len(others)} other players who were alive "
                "when the night began (including any who died tonight): " + roles + ".")
        game.emit(f"Moderator (private): {text}", [by.name], cat=RESULT, message=text)

def died_tonight(game, p) -> bool:
    """Rules (Archivist): N counts players who died this night."""
    return bool(p.death) and p.death["day"] == game.day and p.death["phase"] == "night"
