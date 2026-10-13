"""Census Taker: each night may count the Good or the Evil players among a target and two random others."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import Alignment, RecordedAction, RoleLogic, acted_tonight, as_chosen, join_names, register

if TYPE_CHECKING:
    from state import Game, Player


def census_group(game: Game, taker: str, target: str) -> list[str]:
    """The target and two random others among players alive at the start of the night (rules R10), never the
    Census Taker; fewer when fewer are left. Listed in seat order, so the order doesn't show who was chosen."""
    others = [p.name for p in game.players if acted_tonight(game, p) and p.name not in (taker, target)]
    drawn = game.rng.sample(others, min(2, len(others)))
    return [p.name for p in game.players if p.name in {target, *drawn}]


@register("Census Taker")
class CensusTaker(RoleLogic):
    roleplayer_can_fake = False  # code draws the group and the count
    code_tells_user = True
    action = RecordedAction("census", "takes a census around player",
                            "code draws the group and the count and tells them", visit=True)

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        assert target
        group = census_group(game, by.name, target.name)
        kind = game.rng.choice([Alignment.GOOD, Alignment.EVIL])
        n = sum(game.player(q).info.alignment is kind for q in group)  # true alignment (rules R19)
        shown = as_chosen(game, target.name, group)  # rules R23
        text = (f"Your census of {join_names(shown)} counted {kind.value} players (drawn at random this time): {n} of "
                f"the {len(group)} {'is' if n == 1 else 'are'} {kind.value}. It counts true alignment, so frames and "
                "disguises (the Katana holder, Notorious) don't change it, and a Turncoat counts as Good. "
                "Neutral players are never counted, as either Good or Evil.")
        game.tell([by.name], text)
