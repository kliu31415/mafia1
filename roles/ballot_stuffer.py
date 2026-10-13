"""Ballot Stuffer: at each trial vote, may spend a token so that vote counts twice."""

from __future__ import annotations

from typing import TYPE_CHECKING

from events import VOTE
from roles.base import DayAction, RoleLogic, register, spend_token, tokens_left_text

if TYPE_CHECKING:
    from state import Game, Player


@register("Ballot Stuffer")
class BallotStuffer(RoleLogic):
    def briefing(self, game: Game, p: Player) -> list[str]:
        return ["At each Guilty/Innocent trial vote you may spend a ballot token so that vote counts twice (never in "
                "nomination (Yes/No) votes). You choose when you vote; role-blocks don't stop it."]

    def trial_vote_option(self, game: Game, p: Player) -> DayAction | None:
        if not p.tokens.get("ballot"):
            return None
        return DayAction({"act": {"type": "boolean"}},
                         f"You may stuff the ballot: act true spends a ballot token so this vote counts twice "
                         f"({tokens_left_text(p, 'ballot')}); false keeps it one vote.")

    def trial_vote_weight(self, game: Game, p: Player, answer: dict) -> int:
        if not (answer.get("act") and p.tokens.get("ballot")):
            return 1
        spend_token(game, p.name, "ballot")
        game.emit(f"(Only you see this) You stuffed the ballot: your vote counts twice in this trial "
                  f"({tokens_left_text(p, 'ballot')}).", [p.name], cat=VOTE)
        return 2
