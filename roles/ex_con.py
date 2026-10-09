"""Ex-Con: Good, but appears Evil to alignment checks (Sheriff, Seer), and visits a random player each night."""

from roles.base import RoleLogic, register


@register("Ex-Con")
class ExCon(RoleLogic):
    night_note = ("The Ex-Con visits a random player each night (random_choice). Like a framed player, the Ex-Con "
                  "has the Evil alignment to every role that learns alignments (Sheriff, Seer); roles that "
                  "learn visits or exact roles see it as it is.")  # rules Ex-Con
