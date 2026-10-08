"""Fortune Teller: learns two numbers about each night's visits."""

from roles.base import RoleLogic, register


@register("Fortune Teller")
class FortuneTeller(RoleLogic):
    night_note = ("Tell the Fortune Teller their two numbers about tonight's visits now; they read them at the "
                  "start of the day.")
