"""Eavesdropper: picks a player at night and reads their private messages the next day."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RecordedAction, RoleLogic, chosen_name, register

NEXT = "eavesdrops_next"  # game.role_state: Eavesdropper -> target, recorded tonight for the next day
MOVED = "eavesdrops_moved"  # game.role_state: Eavesdropper -> the player they chose, when a swap moved it (R23)
TODAY = "eavesdrops"  # game.role_state: Eavesdropper -> target, today

if TYPE_CHECKING:
    from state import Game, Player


@register("Eavesdropper")
class Eavesdropper(RoleLogic):
    roleplayer_can_fake = False  # live PMs
    code_tells_user = True
    action = RecordedAction("eavesdrop", "reads player's private messages tomorrow",
                            "code shows them the target's private messages tomorrow and tells them so at dawn",
                            visit=True)

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        assert target
        game.role_state.setdefault(NEXT, {})[by.name] = target.name
        if (chosen := chosen_name(game, target.name)) != target.name:  # rules R23: told at dawn, so it isn't a bug
            game.role_state.setdefault(MOVED, {})[by.name] = chosen

    def at_dawn(self, game: Game) -> None:
        game.role_state[TODAY] = game.role_state.pop(NEXT, {})
        moved = game.role_state.pop(MOVED, {})
        for me, target in game.role_state[TODAY].items():
            if me in moved and game.player(me).alive:
                game.emit(f"A swap moved your eavesdropping from {moved[me]} to {target} last night (rules R23).",
                          [me])
            if game.player(me).alive and not game.player(target).alive:
                game.emit(f"{target} died, so you have no one to eavesdrop on today.", [me])
            elif game.player(me).alive:
                game.emit(f"You are eavesdropping on {target} today: you'll read every private message they send "
                          "or receive.", [me])

    def hears_pm(self, game: Game, me: Player, speaker: str, to: str) -> bool:
        return game.role_state.get(TODAY, {}).get(me.name) in (speaker, to)
