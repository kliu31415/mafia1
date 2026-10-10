"""Profiler: spends a token to learn three candidate roles for a player, one of them true."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import Alignment, RoleLogic, acted_tonight, register, spend_token, token_user_error

if TYPE_CHECKING:
    from state import Game


def profile_candidates(game: Game, profiler: str, target: str) -> list[str]:
    """The target's true role and two decoys, three different roles, at least one Good and one not Good (so one
    result never settles alignment). Decoys are drawn from the roles of the other players alive at the start of the
    night (rules R10), not counting the Profiler's own seat, or from every role when those run out. Sorted, so the
    order doesn't show which is true."""
    from roles import ROLES
    true = game.player(target).role
    in_play = sorted({p.role for p in game.players if acted_tonight(game, p) and p.name != profiler} - {true})

    def good(role: str) -> bool:
        return ROLES[role].alignment is Alignment.GOOD

    def draw(pool: list[str], want_good: bool | None) -> str:
        options = [r for r in pool if want_good is None or good(r) == want_good]
        if not options:  # too few roles in play: any role of that kind
            options = [r for r in sorted(ROLES) if r not in chosen and (want_good is None or good(r) == want_good)]
        return game.rng.choice(options)

    chosen = [true]
    chosen.append(draw(in_play, not good(true)))  # the other side of Good / not Good
    chosen.append(draw([r for r in in_play if r not in chosen], None))
    return sorted(chosen)


@register("Profiler")
class Profiler(RoleLogic):
    roleplayer_can_fake = False  # code draws the decoys
    night_note = ("A Profiler who spent a token (and wasn't role-blocked): use the profile op, which spends the token; "
                  "code tells them the result and tokens left (don't tell() them). It is a visit to the target only.")
    code_tells_user = True
    ops = {"profile": ({"player", "by"}, set(), "{op:'profile', player, by}: the Profiler `by` profiles player (spends "
                                                "a token; code tells them three candidate roles, one true)")}

    def check_op(self, game: Game, change: dict) -> str | None:
        by, target = game.player(change["by"]), game.player(change["player"])
        if error := token_user_error(game, by.name, "Profiler", "profile"):
            return error
        if target is by or not acted_tonight(game, target):
            return "a Profiler profiles another player who was alive at the start of the night"
        return None

    def apply_op(self, game: Game, change: dict) -> None:
        by = game.player(change["by"])
        left = spend_token(game, by.name, "profile")
        a, b, c = profile_candidates(game, by.name, change["player"])
        game.tell([by.name], f"You profiled {change['player']}: their role is {a}, {b} or {c} (exactly one is true, "
                             f"and at least one of the three is a Good role and one is not). {left} profile "
                             f"token{'' if left == 1 else 's'} left.")
