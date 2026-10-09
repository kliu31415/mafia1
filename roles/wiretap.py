"""Wiretap: a Yakuza who reads the contents of every Day private message. Core code adds living
Wiretaps to each PM's audience (Game.pm_listeners); this file only marks the role and briefs it."""

from roles.base import RoleLogic, register


@register("Wiretap")
class Wiretap(RoleLogic):
    hears_all_pms = True

    def briefing(self, game, p):
        return ["You read the contents of every private message sent during the Day, between any two players. "
                "Nobody else knows this, and role-blocks don't stop it."]
