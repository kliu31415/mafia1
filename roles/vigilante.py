"""Vigilante: shoots with 1-3 tokens. The moderator resolves the shot; code tells a Vigilante whose shot killed the
victim's role."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RoleLogic, acted_tonight, register, seen_role

if TYPE_CHECKING:
    from state import Game


@register("Vigilante")
class Vigilante(RoleLogic):
    night_note = ("A Vigilante whose shot kills is told the victim's role by code (pass by=<the Vigilante> on the "
                  "kill op); tell them only whether the attack succeeded and how many tokens they have left.")

    def at_night_end(self, game: Game) -> None:
        # At the end of the night, not at the kill: a Vigilante killed earlier in tonight's resolution still learns
        # (R10: op order doesn't matter), which an on_other_death hook, run only for the living, would miss.
        for me in game.players:
            if me.role != self.role or not acted_tonight(game, me):
                continue
            for dead in game.players:
                died = dead.death or {}
                if (died.get("day"), died.get("phase")) == (game.day, "night") and me.name in died.get("killers", []):
                    # rules, Vigilante: an exact-role result (R19), so a Roleplayer shows as Roleplayer
                    game.tell([me.name], f"Your shot killed {dead.name}. Their role was {seen_role(game, dead)}.")
