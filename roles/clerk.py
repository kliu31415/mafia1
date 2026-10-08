"""Clerk: spends a token at night to rig the next day's trials."""

from roles.base import RoleLogic, register


@register("Clerk")
class Clerk(RoleLogic):
    night_note = "A Clerk's rig: use the rig_vote op (code executes tomorrow's accused regardless of the vote)."
