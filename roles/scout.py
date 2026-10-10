"""Scout: learns, every night, up to three players (possibly themselves) no visit chain links that night."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RoleLogic, acted_tonight, join_names, register, visit_groups

if TYPE_CHECKING:
    from state import Game


@register("Scout")
class Scout(RoleLogic):
    roleplayer_can_fake = False  # code draws the names from the recorded visits
    night_note = ("Code tells the Scout their result every night from your record_visits list; don't tell() them "
                  "anything about it.")

    def at_night_end(self, game: Game) -> None:
        users = [p for p in game.players if p.role == self.role and acted_tonight(game, p)]
        if not users:
            return
        groups = visit_groups(game)
        if groups is None:  # the moderator didn't record_visits (logged as visits_missing)
            game.log.error("scout_no_visits", f"night {game.day}: no visits were recorded, so the Scout got no "
                           "result", day=game.day, players=[p.name for p in users])
            return
        group_of = {n: tuple(g) for g in groups for n in g}
        for p in users:
            # A random player, then their group is set aside, so a group comes up in proportion to its size.
            pool = list(group_of)  # the Scout too (Kevin: simpler)
            names: list[str] = []
            while pool and len(names) < 3:
                names.append(game.rng.choice(pool))
                pool = [n for n in pool if group_of[n] != group_of[names[-1]]]
            names.sort(key=lambda n: game.player(n).seat)
            if len(names) == 3:
                text = f"Tonight {join_names(names)} were each in a different visit group."
            elif len(names) == 2:
                text = f"The players were in only 2 visit groups tonight; one from each: {join_names(names)}."
            else:
                text = f"The players were all in one visit group tonight, including {names[0]}."
            game.tell([p.name], text)
