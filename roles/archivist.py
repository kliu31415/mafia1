"""Archivist: once per game, sees the roles of a random three quarters of the other players alive when the night
began (those who died that night count)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RecordedAction, RoleLogic, acted_tonight, register

SHARE = 0.75  # rules: floor(0.75 * N) of the other players alive when the night began

if TYPE_CHECKING:
    from state import Game, Player


@register("Archivist")
class Archivist(RoleLogic):
    roleplayer_can_fake = False  # code draws the sample
    code_tells_user = True
    action = RecordedAction("archive", "consults the archive; code draws and tells the roles at once",
                            "code shows them the sampled roles at once, as a night result", token="archive",
                            target="")

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        # Told at once, like other night results. The sample is everyone alive when the night began, so it's
        # the same whether the moderator applies the night's kills before or after this op.
        others = [p for p in game.players if p is not by and acted_tonight(game, p)]
        drawn = game.rng.sample(others, int(len(others) * SHARE))
        roles = ", ".join(p.role for p in drawn) or "none"  # in the order drawn: the rule says random order
        game.tell([by.name], f"The archive shows {len(drawn)} of the roles of the {len(others)} other players who "
                             f"were alive when the night began (including any who died tonight): {roles}.")
