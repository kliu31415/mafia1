"""Trapper: sets traps that persist across nights."""

from roles.base import RoleLogic, Status, register


@register("Trapper")
class Trapper(RoleLogic):
    night_note = ("Trapper traps persist across nights: set_status key 'trapped_by' to the Trapper's name on "
                  "the trapped player, and set it to null when the trap is used up, replaced or removed (a Trapper "
                  "removes it by acting with no target). Trapping the player the trap is already on isn't allowed: "
                  "it has no effect and the trap stays armed. "
                  "If several non-Village players visit a trapped player the same night, "
                  "random_choice picks the one hit.")

    def briefing(self, game, p):
        # Trappers lost track of whether their trap still stood (game_20261009_121338_61703).
        trapped = [q.name for q in game.players if q.status.get(Status.TRAPPED_BY) == p.name]
        # Kevin, Oct 10: re-trapping the same player is not allowed; removing the trap is.
        return [f"Your trap is on {trapped[0]} and hasn't gone off yet. You can't trap {trapped[0]} again; to remove "
                "the trap without placing a new one, act with no target." if trapped else "You have no trap set."]
