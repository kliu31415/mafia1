"""Auditor: each night may audit a player, learning how they voted in that Day's nominations and trials."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RecordedAction, RoleLogic, register

if TYPE_CHECKING:
    from state import Game, Player


def audit_text(game: Game, audited: str) -> str:
    """Rules (Auditor): every Yes/No and Guilty/Innocent vote `audited` cast during the Day before this night, in
    order."""
    lines = []
    for v in game.votes.get(game.day, []):
        if audited not in v["votes"]:
            continue
        yes = v["votes"][audited]
        if v["stage"] == "nomination":
            lines.append(f"{'Yes' if yes else 'No'} on the nomination of {v['nominee']}")
        else:
            lines.append(f"{'Guilty' if yes else 'Innocent'} in the trial of {v['nominee']}")
    if not lines:
        return f"Your audit: {audited} cast no nomination or trial votes during the Day."
    return f"Your audit of {audited}'s votes during the Day, in order: " + "; ".join(lines) + "."


@register("Auditor")
class Auditor(RoleLogic):
    roleplayer_can_fake = False  # code reads the votes
    code_tells_user = True
    action = RecordedAction("audit", "audits player", "code tells them the player's votes from the Day", visit=True)

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        assert target
        game.tell([by.name], audit_text(game, target.name))
