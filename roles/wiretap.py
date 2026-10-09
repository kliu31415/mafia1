"""Wiretap: a Yakuza who reads the contents of every Day private message (Game.pm_listeners)."""

from roles.base import RoleLogic, register


@register("Wiretap")
class Wiretap(RoleLogic):
    def hears_pm(self, game, me, speaker, to):
        return True

    def briefing(self, game, p):
        return ["You read the contents of every private message sent during the Day, between any two players. "
                "Nobody else knows this, and role-blocks don't stop it."]
