"""Surveyor: spends a token to learn the role of a random player among a target and their neighbors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RoleLogic, acted_tonight, register, spend_token, token_user_error


def survey_group(game, surveyor: str, target: str) -> list[str]:
    """The target and their nearest neighbor on each side (rules R11), among players alive at the start of the
    night other than the Surveyor, without repeats: [left, target, right], shorter in small games."""
    circle = [p.name for p in game.players if acted_tonight(game, p) and p.name != surveyor]
    i = circle.index(target)
    group = [circle[i - 1], target, circle[(i + 1) % len(circle)]]
    return list(dict.fromkeys(group))

if TYPE_CHECKING:
    from state import Game


@register("Surveyor")
class Surveyor(RoleLogic):
    roleplayer_can_fake = False  # code draws the result
    night_note = ("A Surveyor who spent a token (and wasn't role-blocked): use the survey op, which spends the token; "
                  "code tells them the result and tokens left (don't tell() them). It is a visit to the target only.")
    code_tells_user = True
    ops = {"survey": ({"player", "by"}, set(), "{op:'survey', player, by}: the Surveyor `by` surveys player (spends a "
                                               "token; code picks the group and tells them one random role in it)")}

    def check_op(self, game: Game, change: dict) -> str | None:
        by, target = game.player(change["by"]), game.player(change["player"])
        if error := token_user_error(game, by.name, "Surveyor", "survey"):
            return error
        if target is by or not acted_tonight(game, target):
            return "a Surveyor surveys another player who was alive at the start of the night"
        return None

    def apply_op(self, game: Game, change: dict) -> None:
        by = game.player(change["by"])
        left = spend_token(game, by.name, "survey")
        group = survey_group(game, by.name, change["player"])
        role = game.player(game.rng.choice(group)).role
        names = ", ".join(group[:-1]) + " and " + group[-1] if len(group) > 1 else group[0]
        text = (f"You surveyed {names}. One of them, chosen at random, has the role {role}." if len(group) > 1
                else f"You surveyed {names}, the only player in the group: their role is {role}.")
        text += f" {left} survey token{'' if left == 1 else 's'} left."
        game.tell([by.name], text)
