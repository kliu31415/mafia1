"""Veteran: goes on alert with a token, attacking everyone who visits. The moderator resolves it."""

from roles.base import RoleLogic, register


@register("Veteran")
class Veteran(RoleLogic):
    night_note = ("Veteran on alert (spent an alert token; set_tokens): Standard Defense, can't be role-blocked, and "
                  "a Strong Attack on every player who visited them tonight, of any faction, including a "
                  "role-blocker and the Katana holder if it attacked them. Astral Visits aren't hit. Not a visit. Tell "
                  "the Veteran whether anyone visited and, if so, how many and whether each attack succeeded (e.g. "
                  "'2 players visited you: your attack killed one and failed on the other'), never who they were.")

    def briefing(self, game, p):
        return ["To go on alert, set act=true and tokens_to_spend=1; no target is needed."]
