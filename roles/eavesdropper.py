"""Eavesdropper: picks a player at night and reads their private messages the next day."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RoleLogic, register

NEXT = "eavesdrops_next"  # game.role_state: Eavesdropper -> target, recorded tonight for the next day
TODAY = "eavesdrops"  # game.role_state: Eavesdropper -> target, today

if TYPE_CHECKING:
    from state import Game, Player


@register("Eavesdropper")
class Eavesdropper(RoleLogic):
    roleplayer_can_fake = False  # live PMs
    night_note = ("An Eavesdropper's target (a visit; nothing if role-blocked): use the eavesdrop op (code shows "
                  "them the target's private messages tomorrow, and tells them so at dawn: don't tell() them).")
    code_tells_user = True
    ops = {"eavesdrop": ({"player", "by"}, set(), "{op:'eavesdrop', player, by}: the Eavesdropper `by` reads "
                                                    "player's private messages tomorrow")}

    def check_op(self, game: Game, change: dict) -> str | None:
        by = game.player(change["by"])
        if by.role != "Eavesdropper" or not by.alive:
            return f"{by.name} is not a living Eavesdropper"
        if change["player"] == by.name:
            return "an Eavesdropper can't eavesdrop on themselves"
        return None

    def apply_op(self, game: Game, change: dict) -> None:
        game.role_state.setdefault(NEXT, {})[change["by"]] = change["player"]

    def at_dawn(self, game: Game) -> None:
        game.role_state[TODAY] = game.role_state.pop(NEXT, {})
        for me, target in game.role_state[TODAY].items():
            if game.player(me).alive and not game.player(target).alive:
                game.emit(f"{target} died, so you have no one to eavesdrop on today.", [me])
            elif game.player(me).alive:
                game.emit(f"You are eavesdropping on {target} today: you'll read every private message they send "
                          "or receive.", [me])

    def hears_pm(self, game: Game, me: Player, speaker: str, to: str) -> bool:
        return game.role_state.get(TODAY, {}).get(me.name) in (speaker, to)
