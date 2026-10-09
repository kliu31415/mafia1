"""Ballot Stuffer: spends a token at night so their vote counts twice in the next day's trials."""

from roles.base import RoleLogic, register

NEXT = "ballots_next"  # game.role_state: Ballot Stuffers who spent a token tonight
TODAY = "ballots"  # game.role_state: Ballot Stuffers whose trial votes count twice today


@register("Ballot Stuffer")
class BallotStuffer(RoleLogic):
    night_note = ("A Ballot Stuffer who spent a token (and wasn't role-blocked): use the stuff_ballot op, which "
                  "spends the token; code doubles their trial votes tomorrow.")
    ops = {"stuff_ballot": ({"by"}, set(), "{op:'stuff_ballot', by}: the Ballot Stuffer `by` spends a token; their "
                                           "Guilty/Innocent votes count twice tomorrow")}

    def briefing(self, game, p):
        line = ("When you spend a token at night, your vote counts twice in every Guilty/Innocent trial vote the "
                "next Day, but never in nomination (Yes/No) votes.")
        if p.name in game.role_state.get(TODAY, []):
            line += " Today your trial votes count twice."
        return [line]

    def check_op(self, game, change):
        by = game.player(change["by"])
        if by.role != "Ballot Stuffer" or not by.alive:
            return f"{by.name} is not a living Ballot Stuffer"
        if by.tokens.get("ballot", 0) < 1:
            return f"{by.name} has no ballot token left"
        if by.name in game.role_state.get(NEXT, []):
            return f"{by.name} already stuffed tomorrow's ballots"
        return None

    def apply_op(self, game, change):
        game.player(change["by"]).tokens["ballot"] -= 1
        game.role_state.setdefault(NEXT, []).append(change["by"])

    def at_dawn(self, game):
        game.role_state[TODAY] = game.role_state.pop(NEXT, [])

    def trial_vote_weight(self, game, p):
        return 2 if p.name in game.role_state.get(TODAY, []) else 1
