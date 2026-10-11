"""Scrutineer: each night may count the Guilty votes of a target and two random others in the Day's trials."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RecordedAction, RoleLogic, as_chosen, chosen_name, join_names, register

if TYPE_CHECKING:
    from state import Game, Player


def day_trials(game: Game) -> list[dict]:
    """The trial votes of the Day before this night, in order."""
    return [v for v in game.votes.get(game.day, []) if v["stage"] == "trial"]


def trial_voters(game: Game) -> list[str]:
    """Everyone who voted in one of the Day's trials (with no abstentions, everyone alive that Day), in seat
    order."""
    voted = {n for v in day_trials(game) for n in v["votes"]}
    return [p.name for p in game.players if p.name in voted]


def scrutiny_text(game: Game, scrutineer: str, target: str) -> str:
    """Rules (Scrutineer): the target and two random other voters of the Day's trials, never the Scrutineer, and
    how many of them voted Guilty in each trial. A doubled vote (Ballot Stuffer) is stored once."""
    trials = day_trials(game)
    if not trials:
        return f"Your scrutiny of {chosen_name(game, target)}: there were no trials during the Day."
    others = [n for n in trial_voters(game) if n not in (scrutineer, target)]
    drawn = game.rng.sample(others, min(2, len(others)))
    group = [p.name for p in game.players if p.name in {target, *drawn}]
    counts = [f"{sum(bool(v['votes'].get(n)) for n in group)} in the trial of {v['nominee']}" for v in trials]
    return (f"Your scrutiny of {join_names(as_chosen(game, target, group))}: the number of them who voted Guilty was "
            + "; ".join(counts) + ".")


@register("Scrutineer")
class Scrutineer(RoleLogic):
    roleplayer_can_fake = False  # code draws the group and counts the votes
    code_tells_user = True
    action = RecordedAction("scrutinize", "scrutinizes player's trial votes",
                            "code draws two others and tells them how many of the three voted Guilty in each of the "
                            "Day's trials", note="It is an Astral Visit, so it visits no one.")

    def target_error(self, game: Game, by: Player, target: Player | None) -> str | None:
        assert target
        if day_trials(game) and target.name not in trial_voters(game):
            return f"{target.name} didn't vote in the Day's trials"
        return None

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        assert target
        game.tell([by.name], scrutiny_text(game, by.name, target.name))
