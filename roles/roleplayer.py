"""Roleplayer: believes they have a random Investigative role; the moderator invents their results."""

from roles.base import RoleLogic, Status, register


@register("Roleplayer")
class Roleplayer(RoleLogic):
    night_note = ("Give the Roleplayer fake but plausible results for the role they believe they have (their "
                  "status 'fake_role').")

    def setup(self, game, p):
        from roles import ROLES
        p.status[Status.FAKE_ROLE] = game.rng.choice([r for r, i in ROLES.items() if i.category == "Investigative"])

    def shown_role(self, p):
        return p.status[Status.FAKE_ROLE]  # they're told the fake role, without an alignment
