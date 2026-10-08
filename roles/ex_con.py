"""Ex-Con: Good, but appears Evil to the Sheriff, and visits a random player each night."""

from roles.base import RoleLogic, register


@register("Ex-Con")
class ExCon(RoleLogic):
    night_note = "The Ex-Con visits a random player each night (random_choice)."
