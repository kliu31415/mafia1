"""Ritualist: guesses a player's exact role with a token; the moderator resolves the attack or the exposure."""

from __future__ import annotations

from roles.base import RoleLogic, register


@register("Ritualist")
class Ritualist(RoleLogic):
    night_note = ("Ritualist who spent tokens (and wasn't role-blocked): compare the guessed role with the target's "
                  "exact role (a Roleplayer is a Roleplayer). Right: deal the Attack (1 token Standard, 2 Divine). "
                  "Wrong: no Attack; announce it with tell(['all'], '<name> is a Ritualist.') tonight, which is read "
                  "out at the start of the next Day, even if the Ritualist dies tonight. Astral Visit.")
