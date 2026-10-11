"""Juror: each night names two players and learns how often they voted the same way, over the whole game."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RoleLogic, chosen_name, register, swap_partner, token_user_error

if TYPE_CHECKING:
    from state import Game


def agreement(game: Game, a: str, b: str) -> dict[str, tuple[int, int]]:
    """Rules (Juror): per stage ("trial", "nomination"), (votes a and b cast the same way, votes both cast), over
    every Day so far, leaving out votes on either of them. A doubled vote (Ballot Stuffer) is stored once."""
    counts = {"trial": [0, 0], "nomination": [0, 0]}
    for day in sorted(game.votes):
        for v in game.votes[day]:
            if v["nominee"] in (a, b) or a not in v["votes"] or b not in v["votes"]:
                continue
            c = counts[v["stage"]]
            c[0] += v["votes"][a] == v["votes"][b]
            c[1] += 1
    return {k: (same, n) for k, (same, n) in counts.items()}


def juror_text(a: str, b: str, counts: dict[str, tuple[int, int]]) -> str:
    parts = [f"{same} of {n} {stage} votes" for stage, (same, n) in counts.items() if n]
    if not parts:
        return f"Your jury check: {a} and {b} have no shared votes yet."
    return f"Your jury check: {a} and {b} voted the same way in " + " and ".join(parts) + "."


@register("Juror")
class Juror(RoleLogic):
    roleplayer_can_fake = False  # code counts the votes
    code_tells_user = True
    targets_anyone = True
    ops = {"jury": ({"player", "second", "by"}, set(),
                    "{op:'jury', player, second, by}: the Juror `by` compares two players' votes (code counts "
                    "them over the whole game and tells the Juror)")}
    night_note = ("A Juror who acted (and wasn't role-blocked) and named two different players other than "
                  "themselves (target and second_target; dead players allowed): use the jury op with those two "
                  "players; code tells the Juror the result. Don't tell() the Juror anything about it. It is an "
                  "Astral Visit, so it visits no one.")

    def check_op(self, game: Game, change: dict) -> str | None:
        by, a, b = change["by"], change["player"], change["second"]
        if error := token_user_error(game, by, self.role):
            return error
        if b not in {p.name for p in game.players}:
            return f"no player named {b!r}"
        if a == b:
            return "the Juror needs two different players"
        if by in (a, b) and swap_partner(game, by) is None:  # a swap can land the comparison on the Juror (R23)
            return "a Juror can't compare themselves"
        return None

    def apply_op(self, game: Game, change: dict) -> None:
        a, b = change["player"], change["second"]
        game.tell([change["by"]], juror_text(chosen_name(game, a), chosen_name(game, b), agreement(game, a, b)))
