"""Executioner: wins if their target is hanged."""

from roles.base import RoleLogic, Status, register


@register("Executioner")
class Executioner(RoleLogic):
    def setup(self, game, p):
        p.status[Status.TARGET] = game.rng.choice([q.name for q in game.players if q is not p])

    def briefing(self, game, p):
        return [f"Your target is {p.status[Status.TARGET]}."]
