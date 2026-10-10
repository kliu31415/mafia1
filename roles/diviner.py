"""Diviner: gives a Yakuza target Strong Defense, or learns a role drawn from a target and their neighbors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RoleLogic, acted_tonight, register, token_user_error
from roles.surveyor import survey_group

TARGET_CHANCE = 0.6  # the rest is split evenly among the target's neighbors in the group

if TYPE_CHECKING:
    from state import Game


@register("Diviner")
class Diviner(RoleLogic):
    night_note = ("A Diviner (not role-blocked) who picked a Yakuza: that player has Strong Defense tonight, and the "
                  "Diviner gets no result. One who picked anyone else: use the divine op; code draws the role and "
                  "tells them. It is a visit to the target only.")
    code_tells_user = True
    ops = {"divine": ({"player", "by"}, set(), "{op:'divine', player, by}: the Diviner `by` divines a non-Yakuza "
                                               "player (code picks the group and tells them one role drawn from it)")}

    def check_op(self, game: Game, change: dict) -> str | None:
        by, target = game.player(change["by"]), game.player(change["player"])
        if error := token_user_error(game, by.name, "Diviner"):
            return error
        if not acted_tonight(game, target):
            return f"{target.name} wasn't alive at the start of the night"
        if target.info.category == "Yakuza":
            return f"{target.name} is Yakuza: they get Strong Defense tonight, and the Diviner gets no result"
        return None

    def apply_op(self, game: Game, change: dict) -> None:
        by = game.player(change["by"])
        target = change["player"]
        group = survey_group(game, by.name, target)  # rules: Diviner, the same group as the Surveyor's
        others = [n for n in group if n != target]
        weights = [TARGET_CHANCE if n == target else (1 - TARGET_CHANCE) / len(others) for n in group]
        role = game.player(game.rng.choices(group, weights)[0]).role
        names = ", ".join(group[:-1]) + " and " + group[-1] if len(group) > 1 else group[0]
        text = (f"You divined {target}; the group was {names}. The role drawn is {role} ({TARGET_CHANCE:.0%} chance "
                f"it is {target}'s, otherwise one of the others')." if others
                else f"You divined {target}, the only player in the group: their role is {role}.")
        game.tell([by.name], text)
