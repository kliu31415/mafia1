"""Surveyor: spends a token to learn the role of a random player among a target and their neighbors."""

from events import RESULT
from roles.base import RoleLogic, register


def alive_at_night_start(game, p) -> bool:
    """Night actions resolve simultaneously (rules R10), so players killed earlier in tonight's resolution count."""
    return p.alive or (p.death is not None and p.death["day"] == game.day and p.death["phase"] == "night")


def survey_group(game, surveyor: str, target: str) -> list[str]:
    """The target and their nearest neighbor on each side (rules R11), among players alive at the start of the
    night other than the Surveyor, without repeats: [left, target, right], shorter in small games."""
    circle = [p.name for p in game.players if alive_at_night_start(game, p) and p.name != surveyor]
    i = circle.index(target)
    group = [circle[i - 1], target, circle[(i + 1) % len(circle)]]
    return list(dict.fromkeys(group))


@register("Surveyor")
class Surveyor(RoleLogic):
    roleplayer_can_fake = False  # code draws the result
    night_note = ("A Surveyor who spent a token (and wasn't role-blocked): use the survey op, which spends the token; "
                  "code tells them the result. It is a visit to the target only.")
    ops = {"survey": ({"player", "by"}, set(), "{op:'survey', player, by}: the Surveyor `by` surveys player (spends a "
                                               "token; code picks the group and tells them one random role in it)")}

    def check_op(self, game, change):
        by, target = game.player(change["by"]), game.player(change["player"])
        if by.role != "Surveyor" or not alive_at_night_start(game, by):
            return f"{by.name} is not a Surveyor who was alive tonight"
        if by.tokens.get("survey", 0) < 1:
            return f"{by.name} has no survey token left"
        if target is by or not alive_at_night_start(game, target):
            return "a Surveyor surveys another player who was alive at the start of the night"
        return None

    def apply_op(self, game, change):
        by = game.player(change["by"])
        by.tokens["survey"] -= 1
        group = survey_group(game, by.name, change["player"])
        role = game.player(game.rng.choice(group)).role
        names = ", ".join(group[:-1]) + " and " + group[-1] if len(group) > 1 else group[0]
        text = (f"You surveyed {names}. One of them, chosen at random, has the role {role}." if len(group) > 1
                else f"You surveyed {names}, the only player in the group: their role is {role}.")
        game.emit(f"Moderator (private): {text}", [by.name], cat=RESULT, message=text)
