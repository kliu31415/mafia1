"""Seer: learns about two random players each night, or two chosen ones by spending a token."""

from roles.base import RoleLogic, register


@register("Seer")
class Seer(RoleLogic):
    night_note = ("The Seer learns about two random living players other than themself each night (random_choice), "
                  "unless they spent a token to choose them.")
