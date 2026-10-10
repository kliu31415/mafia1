"""Cartographer: learns the sizes of each night's visit groups; with a token, the names in one player's group."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import (RecordedAction, RoleLogic, acted_tonight, as_chosen, join_names, register,
                        tokens_left_text, visit_groups)

if TYPE_CHECKING:
    from state import Game, Player

MAPS = "cartographer_maps"  # game.role_state: Cartographer -> the player whose group they map tonight


@register("Cartographer")
class Cartographer(RoleLogic):
    roleplayer_can_fake = False  # code works out the groups from the recorded visits
    code_tells_user = True
    action = RecordedAction("map", "maps player's visit group (code tells them its names at the end of the night)",
                            "code tells them the names in that player's group, from your record_visits list",
                            token="map", target="any",
                            note="It is an Astral Visit: don't put it in record_visits. Code also tells every "
                            "Cartographer the sizes of tonight's groups, with or without a token, even if "
                            "role-blocked.")

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        assert target
        game.role_state.setdefault(MAPS, {})[by.name] = target.name  # told once the visits are in

    def at_night_end(self, game: Game) -> None:
        maps = game.role_state.pop(MAPS, {})
        users = [p for p in game.players if p.role == self.role and acted_tonight(game, p)]
        if not users:
            return
        groups = visit_groups(game)
        if groups is None:  # the moderator didn't record_visits (logged as visits_missing); a spent token stays spent
            game.log.error("cartographer_no_visits", f"night {game.day}: no visits were recorded, so the "
                           "Cartographer got no result", day=game.day, players=[p.name for p in users])
            return
        sizes = ", ".join(str(len(g)) for g in groups)
        for p in users:
            text = f"Tonight's visit groups have sizes {sizes}."
            if (target := maps.get(p.name)) is not None:
                group = next(g for g in groups if target in g)
                chosen, = as_chosen(game, target, [target])  # rules R23
                text += (f" You mapped {chosen}: their group is {join_names(as_chosen(game, target, group))}."
                         if len(group) > 1 else f" You mapped {chosen}: their group is just themselves.")
                text += f" {tokens_left_text(p, 'map')}."
            game.tell([p.name], text)
