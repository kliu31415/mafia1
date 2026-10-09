"""Eavesdropper: picks a player at night and reads their private messages the next day."""

from roles.base import RoleLogic, register

NEXT = "eavesdrops_next"  # game.role_state: Eavesdropper -> target, recorded tonight for the next day
TODAY = "eavesdrops"  # game.role_state: Eavesdropper -> target, today


@register("Eavesdropper")
class Eavesdropper(RoleLogic):
    roleplayer_can_fake = False  # live PMs
    night_note = ("An Eavesdropper's target (a visit; nothing if role-blocked): use the eavesdrop op (code shows "
                  "them the target's private messages tomorrow).")
    ops = {"eavesdrop": ({"player", "by"}, set(), "{op:'eavesdrop', player, by}: the Eavesdropper `by` reads "
                                                    "player's private messages tomorrow")}

    def check_op(self, game, change):
        by = game.player(change["by"])
        if by.role != "Eavesdropper" or not by.alive:
            return f"{by.name} is not a living Eavesdropper"
        if change["player"] == by.name:
            return "an Eavesdropper can't eavesdrop on themselves"
        return None

    def apply_op(self, game, change):
        game.role_state.setdefault(NEXT, {})[change["by"]] = change["player"]

    def at_dawn(self, game):
        game.role_state[TODAY] = game.role_state.pop(NEXT, {})
        for me, target in game.role_state[TODAY].items():
            if game.player(me).alive:
                game.emit(f"You are eavesdropping on {target} today: you'll read every private message they send "
                          "or receive.", [me])

    def hears_pm(self, game, me, speaker, to):
        return game.role_state.get(TODAY, {}).get(me.name) in (speaker, to)
