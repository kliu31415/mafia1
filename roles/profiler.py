"""Profiler: spends a token to learn three candidate roles for a player, one of them true."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import (Alignment, RecordedAction, RoleLogic, acted_tonight, as_chosen, register, seen_role,
                        tokens_left_text)

if TYPE_CHECKING:
    from state import Game, Player


def profile_candidates(game: Game, profiler: str, target: str) -> list[str]:
    """The target's true role and two decoys, three different roles, at least one Good and one not Good (so one
    result never settles alignment). One decoy is a role of another player alive at the start of the night (rules
    R10; not the Profiler's own seat), the other a role nobody in the game has (Kevin, Oct 11 2026: decoys only
    from roles in play named the Yakuza roles in game_20261010_150921_904458). Which one must be on the other side
    of Good / not Good is random: always the in-play one would make a Good target's list name a real Evil role.
    A draw with no fitting role falls back to every role on the script. Sorted, so the order doesn't show which is
    true."""
    from roles import ROLES
    from scripts import script_roles
    true = seen_role(game, game.player(target))
    every = sorted(script_roles(game))
    in_play = sorted({seen_role(game, p) for p in game.players if acted_tonight(game, p) and p.name != profiler})
    unused = [r for r in every if r not in {seen_role(game, p) for p in game.players}]

    def good(role: str) -> bool:
        return ROLES[role].alignment is Alignment.GOOD

    chosen = [true]

    def draw(pool: list[str], want_good: bool | None) -> None:
        def fits(r: str) -> bool:
            return r not in chosen and (want_good is None or good(r) == want_good)
        chosen.append(game.rng.choice([r for r in pool if fits(r)] or [r for r in every if fits(r)]))

    other_side = not good(true)
    if game.rng.random() < 0.5:
        draw(in_play, other_side)
        draw(unused, None)
    else:
        draw(unused, other_side)
        draw(in_play, None)
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
                             "at least one of the three is a Good role and at least one is not Good). "
                             f"{tokens_left_text(by, 'profile')}.")
