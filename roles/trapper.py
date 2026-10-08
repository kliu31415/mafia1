"""Trapper: sets traps that persist across nights."""

from roles.base import RoleLogic, register


@register("Trapper")
class Trapper(RoleLogic):
    night_note = "Trapper traps persist across nights; track them with set_status."
