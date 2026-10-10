"""Vigilante: shoots with 1-3 tokens. The moderator resolves the shot; code tells a Vigilante whose shot killed the
victim's role."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RoleLogic, register

if TYPE_CHECKING:
    from state import Game, Player


@register("Vigilante")
class Vigilante(RoleLogic):
    night_note = ("A Vigilante whose shot kills is told the victim's role by code (pass by=<the Vigilante> on the "
                  "kill op); tell them only whether the attack succeeded and how many tokens they have left.")

    def on_other_death(self, game: Game, me: Player, dead: Player, guilty_voters: list[str] | None) -> None:
        # rules, Vigilante: an exact-role result (R19), so a Roleplayer shows as Roleplayer
        if me.name in (dead.death or {}).get("killers", []):
            game.tell([me.name], f"Your shot killed {dead.name}. Their role was {dead.role}.")
