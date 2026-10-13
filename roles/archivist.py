"""Archivist: once per game, is shown N roles, where N is the number of other players alive when the night began
(those who died that night count): the real roles of a random half of them plus fakes drawn from every
role in the rules, mixed in random order."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RecordedAction, RoleLogic, acted_tonight, register, seen_role

SHARE = 0.5  # rules: floor(0.5 * N) of the N roles shown are real

if TYPE_CHECKING:
    from state import Game, Player


def archive_roles(game: Game, by: Player) -> tuple[int, int, list[str]]:
    """(N, how many are real, the N roles shown in random order). The real ones are the roles of randomly chosen
    other players alive when the night began; each fake is any role on the game's script (scripts.py), in play or
    not, except a second copy of a unique role (rules R2)."""
    from roles import ROLES
    from scripts import script_roles
    others = [p for p in game.players if p is not by and acted_tonight(game, p)]
    shown = [seen_role(game, p) for p in game.rng.sample(others, int(len(others) * SHARE))]
    real = len(shown)
    every_role = sorted(script_roles(game))
    while len(shown) < len(others):
        fake = game.rng.choice([r for r in every_role if not (ROLES[r].unique and r in shown)])
        shown.append(fake)
    game.rng.shuffle(shown)  # the rule says random order: fakes aren't at the end
    return len(others), real, shown


@register("Archivist")
class Archivist(RoleLogic):
    roleplayer_can_fake = False  # code draws the sample
    code_tells_user = True
    action = RecordedAction("archive", "consults the archive; code draws and tells the roles at once",
                            "code shows them the drawn roles at once, as a night result", token="archive",
                            target="")

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        # Told at once, like other night results. The sample is everyone alive when the night began, so it's
        # the same whether the moderator applies the night's kills before or after this op.
        n, real, shown = archive_roles(game, by)
        roles = ", ".join(shown) or "none"
        game.tell([by.name], f"The archive shows {n} roles, one for each of the {n} other players who were alive "
                             f"when the night began (including any who died tonight): {real} of them are the real "
                             f"roles of {real} of those players, the other {n - real} are fakes, all in random "
                             f"order: {roles}.")
