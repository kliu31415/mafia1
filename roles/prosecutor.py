"""Prosecutor: spends a token at night to send someone straight to trial the next day."""

from roles.base import RoleLogic, register


@register("Prosecutor")
class Prosecutor(RoleLogic):
    night_note = "A Prosecutor's prosecution: use the prosecute op (code runs the trial when the next day starts)."
    ops = {"prosecute": ({"player"}, set(), "{op:'prosecute', player}: they go to trial when the next day starts")}

    def apply_op(self, game, change):
        if change["player"] not in game.prosecutions:  # two Prosecutors on one player: one trial
            game.prosecutions.append(change["player"])
