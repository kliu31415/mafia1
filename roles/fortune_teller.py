"""Fortune Teller: learns two numbers about each night's visits."""

from roles.base import RoleLogic, register


@register("Fortune Teller")
class FortuneTeller(RoleLogic):
    night_note = ("Tell the Fortune Teller their two numbers about tonight's visits now, as a night result, each "
                  "labeled (e.g. '4 players were visited; 3 players visited someone'). "
                  "Self-visits count in both numbers, and a player who visits several players (e.g. a Katana holder "
                  "also using their own action) counts once as a visitor.")
