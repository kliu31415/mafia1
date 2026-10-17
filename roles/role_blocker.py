"""Party Animal and Pharmacist: role-blocks are moderator-handled; code keeps a role-blocker off the player it chose
the night before (rules R9), by leaving them out of its target choices."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RoleLogic, register

if TYPE_CHECKING:
    from state import Game, Player


class RoleBlocker(RoleLogic):
    def barred_targets(self, game: Game, p: Player) -> dict[str, str]:
        # Kevin, Oct 17 2026: per blocker, so a failed block reveals nothing new. In 110 logged games every repeat
        # block was its blocker's own, mostly a Pharmacist keeping a Medic or Sheriff blocked night after night.
        last = game.night_actions.get(game.day - 1, {}).get(p.name) or {}
        target = last.get("target") if last.get("act") else None
        if not target or not game.player(target).alive:
            return {}
        return {target: "you chose them last night, and a role-blocker can't choose the same player two nights in "
                        "a row (rules R9)"}


@register("Party Animal")
class PartyAnimal(RoleBlocker):
    pass


@register("Pharmacist")
class Pharmacist(RoleBlocker):
    pass
