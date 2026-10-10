"""Census Taker: spends a token to count the Good or the Evil players among a target and two random others."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import Alignment, RoleLogic, acted_tonight, register, spend_token, token_user_error

if TYPE_CHECKING:
    from state import Game, Player


def census_group(game: Game, taker: str, target: str) -> list[str]:
    """The target and two random others among players alive at the start of the night (rules R10), never the
    Census Taker; fewer when fewer are left. Listed in seat order, so the order doesn't show who was chosen."""
    others = [p.name for p in game.players if acted_tonight(game, p) and p.name not in (taker, target)]
    drawn = game.rng.sample(others, min(2, len(others)))
    return [p.name for p in game.players if p.name in {target, *drawn}]


def seen_alignment(game: Game, p: Player, framed: set[str]) -> Alignment:
    """p's alignment as alignment checks see it (rules R19), with Neutrals seen as Neutral (as by a Seer)."""
    if p.name == game.katana_holder and p.info.alignment is Alignment.EVIL:
        return Alignment.GOOD
    if p.name in framed or (p.info.alignment is Alignment.GOOD and p.info.sheriff_evil):  # framed, Ex-Con
        return Alignment.EVIL
    return p.info.alignment


@register("Census Taker")
class CensusTaker(RoleLogic):
    roleplayer_can_fake = False  # code draws the group and the count
    night_note = ("A Census Taker who spent a token (and wasn't role-blocked): use the census op, which spends the "
                  "token, with `framed` listing every player a Fabricator framed tonight (empty if none); code draws "
                  "the group and the count and tells them (don't tell() them). It is a visit to the target only.")
    code_tells_user = True
    ops = {"census": ({"player", "by", "framed"}, set(),
                      "{op:'census', player, by, framed}: the Census Taker `by` takes a census around player (spends a "
                      "token); framed = every player a Fabricator framed tonight, [] if none")}

    def check_op(self, game: Game, change: dict) -> str | None:
        by, target = game.player(change["by"]), game.player(change["player"])
        if error := token_user_error(game, by.name, "Census Taker", "census"):
            return error
        if target is by or not acted_tonight(game, target):
            return "a Census Taker counts around another player who was alive at the start of the night"
        framed = change["framed"]
        if not isinstance(framed, list) or not all(isinstance(n, str) for n in framed):
            return "framed must be a list of player names ([] if nobody was framed)"
        if unknown := [n for n in framed if n not in {p.name for p in game.players}]:
            return f"no player named {unknown[0]!r} in framed"
        return None

    def apply_op(self, game: Game, change: dict) -> None:
        by = game.player(change["by"])
        left = spend_token(game, by.name, "census")
        group = census_group(game, by.name, change["player"])
        kind = game.rng.choice([Alignment.GOOD, Alignment.EVIL])
        n = sum(seen_alignment(game, game.player(q), set(change["framed"])) is kind for q in group)
        names = ", ".join(group[:-1]) + " and " + group[-1] if len(group) > 1 else group[0]
        text = (f"Your census of {names} counted {kind.value} players (drawn at random this time): {n} of the "
                f"{len(group)} {'is' if n == 1 else 'are'} {kind.value}. Neutral players are never counted, as either "
                f"Good or Evil. {left} census token{'' if left == 1 else 's'} left.")
        game.tell([by.name], text)
