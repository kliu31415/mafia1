"""Prosecutor: spends a token at night to send someone straight to trial the next day."""

from roles.base import RoleLogic, register


@register("Prosecutor")
class Prosecutor(RoleLogic):
    night_note = "A Prosecutor's prosecution: use the prosecute op (code runs the trial when the next day starts)."
