"""Accountant: learns a player's total token count at the end of the night. The moderator resolves it;
this file only adds the night note."""

from roles.base import RoleLogic, register


@register("Accountant")
class Accountant(RoleLogic):
    night_note = ("Accountant: tell them their target's total token count (all kinds added up, not which kinds) "
                  "after this night's set_tokens changes. A Roleplayer always shows 0 (rules R19).")
