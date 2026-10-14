"""Diviner: gives a Yakuza target Strong Defense, or learns a role drawn from a target and their neighbors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import (RecordedAction, RoleLogic, join_names, neighbor_group, register,
                        seen_role)

TARGET_CHANCE = 0.6  # the rest is split evenly among the target's neighbors in the group

if TYPE_CHECKING:
    from state import Game, Player


@register("Diviner")
class Diviner(RoleLogic):
    code_tells_user = True
    action = RecordedAction("divine", "divines a non-Yakuza player (code picks the group and tells them one role "
                            "drawn from it)", "code draws the role and tells them", target="any", visit=True,
                            note="If they picked a Yakuza, don't use the op: that player has Strong Defense "
                            "tonight, and the Diviner gets no result.")

    def target_error(self, game: Game, by: Player, target: Player | None) -> str | None:
        if target and target.info.category == "Yakuza":
            return f"{target.name} is Yakuza: they get Strong Defense tonight, and the Diviner gets no result"
        return None

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        assert target
        group = neighbor_group(game, by.name, target.name)  # rules: Diviner
        others = [n for n in group if n != target.name]
        weights = [TARGET_CHANCE if n == target.name else (1 - TARGET_CHANCE) / len(others) for n in group]
        role = seen_role(game, game.player(game.rng.choices(group, weights)[0]))
        name = target.name
        text = (f"You divined {name}; the group was {join_names(group)}. The role "
                f"drawn is {role} ({TARGET_CHANCE:.0%} chance it is {name}'s, otherwise one of the others')."
                if others else f"You divined {name}, the only player in the group: their role is {role}.")
        game.tell([by.name], text)
