"""Ballot Stuffer: spends a token at night so their vote counts twice in the next day's trials."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RecordedAction, RoleLogic, register

NEXT = "ballots_next"  # game.role_state: Ballot Stuffers who spent a token tonight
TODAY = "ballots"  # game.role_state: Ballot Stuffers whose trial votes count twice today

if TYPE_CHECKING:
    from state import Game, Player


@register("Ballot Stuffer")
class BallotStuffer(RoleLogic):
    action = RecordedAction("stuff_ballot", "has their Guilty/Innocent votes count twice tomorrow",
                            "code doubles their trial votes tomorrow", token="ballot", target="")

    def briefing(self, game: Game, p: Player) -> list[str]:
        line = ("When you spend a token at night, your vote counts twice in every Guilty/Innocent trial vote the "
                "next Day, but never in nomination (Yes/No) votes.")
        if game.phase == "day" and p.name in game.role_state.get(TODAY, []):
            line += " Today your trial votes count twice."
        return [line]

    def target_error(self, game: Game, by: Player, target: Player | None) -> str | None:
        return f"{by.name} already stuffed tomorrow's ballots" if by.name in game.role_state.get(NEXT, []) else None

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        game.role_state.setdefault(NEXT, []).append(by.name)

    def at_dawn(self, game: Game) -> None:
        game.role_state[TODAY] = game.role_state.pop(NEXT, [])

    def trial_vote_weight(self, game: Game, p: Player) -> int:
        return 2 if p.name in game.role_state.get(TODAY, []) else 1
