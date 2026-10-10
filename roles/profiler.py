"""Profiler: spends a token to learn three candidate roles for a player, one of them true."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import Alignment, RecordedAction, RoleLogic, acted_tonight, as_chosen, register, tokens_left_text

if TYPE_CHECKING:
    from state import Game, Player


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
    code_tells_user = True
    action = RecordedAction("profile", "profiles player (code tells them three candidate roles, one true)",
                            "code tells them the result and tokens left", token="profile", visit=True)

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        assert target
        a, b, c = profile_candidates(game, by.name, target.name)
        chosen, = as_chosen(game, target.name, [target.name])  # a swapped result doesn't show the swap (R23)
        game.tell([by.name], f"You profiled {chosen}: their role is {a}, {b} or {c} (exactly one is true, and "
                             "at least one of the three is a Good role and one is not). "
                             f"{tokens_left_text(by, 'profile')}.")
