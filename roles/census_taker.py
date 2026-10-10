"""Census Taker: each night may count the Good or the Evil players among a target and two random others."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import Alignment, RoleLogic, acted_tonight, register, token_user_error

if TYPE_CHECKING:
    from state import Game


def census_group(game: Game, taker: str, target: str) -> list[str]:
    """The target and two random others among players alive at the start of the night (rules R10), never the
    Census Taker; fewer when fewer are left. Listed in seat order, so the order doesn't show who was chosen."""
    others = [p.name for p in game.players if acted_tonight(game, p) and p.name not in (taker, target)]
    drawn = game.rng.sample(others, min(2, len(others)))
    return [p.name for p in game.players if p.name in {target, *drawn}]


@register("Census Taker")
class CensusTaker(RoleLogic):
    roleplayer_can_fake = False  # code draws the group and the count
    night_note = ("A Census Taker who acted (and wasn't role-blocked): use the census op; code draws "
                  "the group and the count and tells them (don't tell() them). It is a visit to the target only.")
    code_tells_user = True
    ops = {"census": ({"player", "by"}, set(),
                      "{op:'census', player, by}: the Census Taker `by` takes a census around player")}

    def check_op(self, game: Game, change: dict) -> str | None:
        by, target = game.player(change["by"]), game.player(change["player"])
        if error := token_user_error(game, by.name, "Census Taker"):
            return error
        if target is by or not acted_tonight(game, target):
            return "a Census Taker counts around another player who was alive at the start of the night"
        return None

    def apply_op(self, game: Game, change: dict) -> None:
        by = game.player(change["by"])
        group = census_group(game, by.name, change["player"])
        kind = game.rng.choice([Alignment.GOOD, Alignment.EVIL])
        n = sum(game.player(q).info.alignment is kind for q in group)  # true alignment (rules R19)
        names = ", ".join(group[:-1]) + " and " + group[-1] if len(group) > 1 else group[0]
        text = (f"Your census of {names} counted {kind.value} players (drawn at random this time): {n} of the "
                f"{len(group)} {'is' if n == 1 else 'are'} {kind.value}. It counts true alignment, so frames and "
                "disguises (the Katana holder, the Ex-Con) don't change it. Neutral players are never counted, as "
                "either Good or Evil.")
        game.tell([by.name], text)
