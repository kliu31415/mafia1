"""Medic: protection is moderator-handled; the briefing spells out what each choice costs."""

from roles.base import RoleLogic, register


@register("Medic")
class Medic(RoleLogic):
    def briefing(self, game, p):
        # Players kept misreading the self-protection cost in the rules text.
        return ["Token costs (set tokens_to_spend to match): another player with Standard Defense costs 0 tokens, "
                "with Strong Defense 1; yourself with Standard Defense costs 1 token, with Strong Defense 2."]
