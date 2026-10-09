"""Philanthropist: spends a token at night to hand another player a token of their own role's kind."""

from events import RESULT
from roles.base import RoleLogic, register


@register("Philanthropist")
class Philanthropist(RoleLogic):
    night_note = ("A Philanthropist who spent a token (and wasn't role-blocked): use the give_token op, which spends "
                  "it; code hands the recipient a token and tells them. Tell the Philanthropist nothing about it.")
    ops = {"give_token": ({"player", "by"}, set(), "{op:'give_token', player, by}: the Philanthropist `by` hands "
                                                   "player a token of their role's kind (spends a token)")}

    def check_op(self, game, change):
        by, to = game.player(change["by"]), game.player(change["player"])
        if by.role != "Philanthropist":
            return f"{by.name} is not a Philanthropist"
        if by.tokens.get("philanthropy", 0) < 1:
            return f"{by.name} has no philanthropy token left"
        if to is by:
            return "a Philanthropist hands tokens to other players only"
        return None

    def apply_op(self, game, change):
        game.player(change["by"]).tokens["philanthropy"] -= 1
        to = game.player(change["player"])
        # A Roleplayer's token kinds are their fake role's, so the gift keeps their cover.
        if kinds := sorted(to.tokens):
            kind = game.rng.choice(kinds)
            to.tokens[kind] += 1
            text = f"A Philanthropist handed you a {kind} token. You now have {to.tokens[kind]}."
        else:
            text = "A Philanthropist handed you a token, but you threw it away because you have no use for it."
        game.emit(f"Moderator (private): {text}", [to.name], cat=RESULT, message=text)
