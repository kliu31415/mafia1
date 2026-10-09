"""Veteran: goes on alert with a token, attacking everyone who visits. The moderator resolves it."""

from roles.base import RoleLogic, register


@register("Veteran")
class Veteran(RoleLogic):
    night_note = ("Veteran on alert (spent an alert token; set_tokens): Standard Defense, can't be role-blocked, and "
                  "a Strong Attack on every player who visited them tonight, of any faction, including a "
                  "role-blocker and the Katana holder if it attacked them. Astral Visits aren't hit. Not a visit.")

    def briefing(self, game, p):
        return ["To go on alert, set act=true and tokens_to_spend=1; no target is needed."]
