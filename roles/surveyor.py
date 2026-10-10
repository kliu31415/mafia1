"""Surveyor: spends a token to learn the role of a random player among a target and their neighbors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import (RecordedAction, RoleLogic, as_chosen, join_names, neighbor_group, register,
                        tokens_left_text)

if TYPE_CHECKING:
    from state import Game, Player


@register("Surveyor")
class Surveyor(RoleLogic):
    roleplayer_can_fake = False  # code draws the result
    code_tells_user = True
    action = RecordedAction("survey", "surveys player (code picks the group and tells them one random role in it)",
                            "code tells them the result and tokens left", token="survey", visit=True)

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        assert target
        group = neighbor_group(game, by.name, target.name)
        role = game.player(game.rng.choice(group)).role
        shown = as_chosen(game, target.name, group)  # rules R23
        text = (f"You surveyed {join_names(shown)}. One of them, chosen at random, has the role {role}."
                if len(group) > 1 else f"You surveyed {shown[0]}, the only player in the group: their role is "
                f"{role}.")
        game.tell([by.name], f"{text} {tokens_left_text(by, 'survey')}.")
