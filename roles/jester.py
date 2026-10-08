"""Jester: wins if hanged, then a Divine Attack hits a random Guilty voter (Game.resolve_revenge)."""

from roles.base import RoleLogic, register


@register("Jester")
class Jester(RoleLogic):
    blocks_win = False
    night_note = "Jester revenge attacks are carried out by code after you finish; don't resolve them."

    def on_death(self, game, p, guilty_voters):
        if guilty_voters is not None:
            game.personal_winners.append(p.name)
            game.pending_revenge.append((p.name, guilty_voters))
