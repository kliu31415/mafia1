"""Archivist: once per game, sees the roles of a random three quarters of the other players alive when the night
began (those who died that night count)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RoleLogic, acted_tonight, register, spend_token, token_user_error

SHARE = 0.75  # rules: floor(0.75 * N) of the other players alive when the night began

if TYPE_CHECKING:
    from state import Game


@register("Archivist")
class Archivist(RoleLogic):
    roleplayer_can_fake = False  # code draws the sample
    night_note = ("An Archivist who spent their token (and wasn't role-blocked): use the archive op, which spends "
                  "the token; code shows them the sampled roles at once, as a night result (don't tell() them).")
    code_tells_user = True
    ops = {"archive": ({"by"}, set(), "{op:'archive', by}: the Archivist `by` consults the archive (spends their "
                                      "token; code draws and tells the roles at once)")}

    def check_op(self, game: Game, change: dict) -> str | None:
        return token_user_error(game, change["by"], "Archivist", "archive")

    def apply_op(self, game: Game, change: dict) -> None:
        # Told at once, like other night results. The sample is everyone alive when the night began, so it's
        # the same whether the moderator applies the night's kills before or after this op.
        by = game.player(change["by"])
        spend_token(game, by.name, "archive")
        others = [p for p in game.players if p is not by and acted_tonight(game, p)]
        drawn = game.rng.sample(others, int(len(others) * SHARE))
        roles = ", ".join(p.role for p in drawn) or "none"  # in the order drawn: the rule says random order
        text = (f"The archive shows {len(drawn)} of the roles of the {len(others)} other players who were alive "
                "when the night began (including any who died tonight): " + roles + ".")
        game.tell([by.name], text)
