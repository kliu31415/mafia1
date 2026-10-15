"""Vulture: wins alone once few enough players are left at the start of a day. Each night it may visit a player;
if they die that night, code tells it their role and it powers up: a higher threshold or more Defense, in turn."""

from __future__ import annotations

from typing import TYPE_CHECKING

from events import ANNOUNCEMENT
from roles.base import ATTACK_LEVELS, RecordedAction, RoleLogic, Status, register, seen_role

if TYPE_CHECKING:
    from state import Game, Player

VISITS = "vulture_visits"  # role_state: Vulture -> the player they visited tonight
POWER = "vulture_power"  # role_state: Vulture -> {"bonus": threshold raises, "defense": level earned}
START = 2  # rules (Vulture): the threshold before any power-up
# Rules (Vulture): the power-ups, in the order hits earn them; after these, each hit raises the threshold.
LADDER = ("count", "Standard", "count", "Strong")  # "count" raises the threshold by 1; the others are Defense levels


def cap(game: Game) -> int:
    """Rules (Vulture): the threshold never goes above max(floor(N/3), 2), N the number of players at the start."""
    return max(len(game.players) // 3, START)


def power(game: Game, name: str) -> dict:
    return game.role_state.setdefault(POWER, {}).setdefault(name, {"bonus": 0, "defense": "None"})


def threshold(game: Game, name: str) -> int:
    return START + power(game, name)["bonus"]


def power_up(game: Game, name: str) -> str:
    """Rules (Vulture): gives the first power-up the Vulture doesn't have yet and the cap allows; says what it was
    (or that nothing was left)."""
    state = power(game, name)
    counts = 0  # the threshold raises the ladder has given so far
    for step in [*LADDER, *["count"] * cap(game)]:
        if step == "count":
            counts += 1
            if state["bonus"] < counts and START + counts <= cap(game):
                state["bonus"] = counts
                return f"your threshold is now {threshold(game, name)} players"
        elif ATTACK_LEVELS.index(state["defense"]) < ATTACK_LEVELS.index(step):
            state["defense"] = step
            return f"you now have {step} Defense"
    return "you have every power-up already, so nothing changes"


@register("Vulture")
class Vulture(RoleLogic):
    roleplayer_can_fake = False  # code tells the result
    code_tells_user = True
    night_end_order = 3  # after every other night-end effect (a Cursed player's curse), so all tonight's deaths count
    action = RecordedAction("scavenge", "visits player (code checks at the end of the night whether they died)",
                            "code tells them the result at the end of the night", visit=True,
                            note="Record it whether or not the target dies.")

    def briefing(self, game: Game, p: Player) -> list[str]:
        return [f"You win if you are alive at the start of a Day with {threshold(game, p.name)} or fewer players "
                f"alive (counting yourself). Your threshold can rise to at most {cap(game)}."
                + (f" Your power-ups have given you {d} Defense." if (d := power(game, p.name)["defense"]) != "None"
                   else "")]

    def defense(self, game: Game, p: Player) -> str:
        earned = power(game, p.name)["defense"]
        return max(p.info.defense, earned, key=ATTACK_LEVELS.index)

    def tonight_note(self, game: Game) -> str:
        return "; ".join(f"{p.name} (Vulture) has {self.defense(game, p)} Defense from its power-ups"
                         for p in game.alive() if p.role == self.role and self.defense(game, p) != "None")

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        assert target
        game.role_state.setdefault(VISITS, {})[by.name] = target.name

    def at_night_end(self, game: Game) -> None:
        for name, target_name in sorted(game.role_state.pop(VISITS, {}).items()):
            me, target = game.player(name), game.player(target_name)
            if not me.alive or me.role != self.role:
                continue
            death = target.death
            died = (death and death["phase"] == "night" and death["day"] == game.day
                    and not target.status.get(Status.LEFT))
            if not died:
                game.tell([name], f"You visited {target_name}, who didn't die tonight, so you gained nothing.")
                continue
            # Rules (Vulture, Mortician): a cleaned body hides its role, as from a Coroner, but the hit still counts.
            role = ("their body was cleaned, so you learned nothing more" if target.status.get(Status.CLEANED)
                    else f"their role was {seen_role(game, target)}")
            game.tell([name], f"You visited {target_name}, who died tonight: {role}. {power_up(game, name)}.")

    def at_dawn(self, game: Game) -> None:
        for v in game.alive():
            if v.role == self.role and len(game.alive()) <= threshold(game, v.name):
                game.sole_winner = v.name
                text = f"{v.name} is the Vulture: only {len(game.alive())} players are left, so they win alone."
                game.emit(text, cat=ANNOUNCEMENT, message=text)
                return
