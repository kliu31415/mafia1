"""Ballot Stuffer: spends a token at night so their vote counts twice in the next day's trials."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RoleLogic, register

NEXT = "ballots_next"  # game.role_state: Ballot Stuffers who spent a token tonight
TODAY = "ballots"  # game.role_state: Ballot Stuffers whose trial votes count twice today

if TYPE_CHECKING:
    from state import Game, Player


@register("Ballot Stuffer")
class BallotStuffer(RoleLogic):
    night_note = ("A Ballot Stuffer who spent a token (and wasn't role-blocked): use the stuff_ballot op, which "
                  "spends the token; code doubles their trial votes tomorrow.")
    ops = {"stuff_ballot": ({"by"}, set(), "{op:'stuff_ballot', by}: the Ballot Stuffer `by` spends a token; their "
                                           "Guilty/Innocent votes count twice tomorrow")}

    def briefing(self, game: Game, p: Player) -> list[str]:
        line = ("When you spend a token at night, your vote counts twice in every Guilty/Innocent trial vote the "
                "next Day, but never in nomination (Yes/No) votes.")
        if game.phase == "day" and p.name in game.role_state.get(TODAY, []):
            line += " Today your trial votes count twice."
        return [line]

    def check_op(self, game: Game, change: dict) -> str | None:
        by = game.player(change["by"])
        if by.role != "Ballot Stuffer" or not by.alive:
            return f"{by.name} is not a living Ballot Stuffer"
        if by.tokens.get("ballot", 0) < 1:
            return f"{by.name} has no ballot token left"
        if by.name in game.role_state.get(NEXT, []):
            return f"{by.name} already stuffed tomorrow's ballots"
        return None

    def apply_op(self, game: Game, change: dict) -> None:
        game.player(change["by"]).tokens["ballot"] -= 1
        game.role_state.setdefault(NEXT, []).append(change["by"])

    def at_dawn(self, game: Game) -> None:
        game.role_state[TODAY] = game.role_state.pop(NEXT, [])

    def trial_vote_weight(self, game: Game, p: Player) -> int:
        return 2 if p.name in game.role_state.get(TODAY, []) else 1
