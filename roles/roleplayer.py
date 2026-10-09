"""Roleplayer: believes they have a random Investigative role; the moderator invents their results."""

from roles.base import RoleLogic, Status, register


@register("Roleplayer")
class Roleplayer(RoleLogic):
    night_note = ("Give the Roleplayer fake but plausible results for the role they believe they have (their "
                  "status 'fake_role'). Their own actions aren't visits and have no effect: no other role sees or "
                  "is affected by them (rules: Roleplayer).")

    # They must not be able to tell they aren't the real role: same tokens, alignment and night prompts.
    def setup(self, game, p):
        from roles import ROLES, logic
        fake = game.rng.choice([r for r, i in ROLES.items() if i.category == "Investigative"
                                and logic(r).roleplayer_can_fake])
        p.status[Status.FAKE_ROLE] = fake
        p.tokens = dict(ROLES[fake].tokens)

    def shown_role(self, p):
        from roles import ROLES
        return f"{p.status[Status.FAKE_ROLE]} ({ROLES[p.status[Status.FAKE_ROLE]].alignment.value})"

    def acts_at_night(self, p):
        from roles import ROLES
        return ROLES[p.status[Status.FAKE_ROLE]].acts_at_night
