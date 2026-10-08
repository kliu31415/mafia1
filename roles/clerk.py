"""Clerk: spends a token at night to rig the next day's trials."""

from roles.base import RoleLogic, register


@register("Clerk")
class Clerk(RoleLogic):
    night_note = "A Clerk's rig: use the rig_vote op (code executes tomorrow's accused regardless of the vote)."
    ops = {"rig_vote": (set(), set(), "{op:'rig_vote'}: tomorrow's trials execute the accused regardless of the "
                                       "vote (no player field)")}

    def apply_op(self, game, change):
        game.rigged_day = game.day + 1
