"""Puppeteer: spends a token at night to chat as someone else the next day."""

from roles.base import RoleLogic, register


@register("Puppeteer")
class Puppeteer(RoleLogic):
    night_note = "A Puppeteer's puppet: use the puppet op (code swaps who chats tomorrow)."
    ops = {"puppet": ({"player", "by"}, set(), "{op:'puppet', player, by}: player is puppeted by the Puppeteer "
                                                 "`by` tomorrow")}

    def check_op(self, game, change):
        by = game.player(change["by"])
        if by.role != "Puppeteer" or not by.alive:
            return f"{by.name} is not a living Puppeteer"
        if change["player"] == by.name:
            return "a Puppeteer can't puppet themselves"
        return None

    def apply_op(self, game, change):
        game.puppets_next[change["player"]] = change["by"]
