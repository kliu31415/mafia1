"""Clerk: spends a token at night to rig the next day's trials."""

from roles.base import RoleLogic, register, token_user_error


@register("Clerk")
class Clerk(RoleLogic):
    night_note = "A Clerk's rig: use the rig_vote op (code executes tomorrow's accused regardless of the vote)."
    ops = {"rig_vote": ({"by"}, set(), "{op:'rig_vote', by}: the Clerk `by` spends a token; tomorrow's trials "
                                        "execute the accused regardless of the vote")}

    def check_op(self, game, change):
        return token_user_error(game, change["by"], "Clerk", "clerk")

    def apply_op(self, game, change):
        game.player(change["by"]).tokens["clerk"] -= 1
        game.rigged_day = game.day + 1
