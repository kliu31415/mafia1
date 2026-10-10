"""Seer: learns about two random players each night, or two chosen ones by spending a token."""

from roles.base import RoleLogic, register


@register("Seer")
class Seer(RoleLogic):
    night_note = ("The Seer learns about two random players other than themself each night (random_choice) "
                  "from those alive when the night began, including anyone who died that night (rules R10), "
                  "unless they spent a token to choose them. A chosen pair visits both players; the random pair "
                  "isn't a visit. A role-blocked Seer gets no pair at all.")
