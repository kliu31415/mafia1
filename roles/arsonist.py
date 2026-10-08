"""Arsonist: douses players, then ignites them all at once."""

from roles.base import RoleLogic, register


@register("Arsonist")
class Arsonist(RoleLogic):
    night_note = "Track Arsonist douses with set_status key 'doused'."
