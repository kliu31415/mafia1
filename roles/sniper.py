"""Sniper: on its own Day turns, takes an anonymous shot at a player with 1-3 tokens (rules R25). Code fires it after
a random delay of 0 to n-1 more Day speaking turns (n players alive): everyone hears the shot and its target, then the
death or that the target survived; nobody learns who shot."""

from __future__ import annotations

from typing import TYPE_CHECKING

from events import ANNOUNCEMENT
from roles.base import (ATTACK_LEVELS, DayAction, RoleLogic, attack_kills, logic, record_attack, register,
                        tokens_left_text)

if TYPE_CHECKING:
    from state import Game, Player

TOKEN = "sniper"
SHOT_DAY = "sniper_shot_day"  # game.role_state: Sniper -> the last Day they took a shot (one shot a Day)
HELD = "sniper_held"  # game.role_state: [shooter, target, attack, turns left] shots waiting to be fired


@register("Sniper")
class Sniper(RoleLogic):
    def day_action(self, game: Game, p: Player) -> DayAction | None:
        from players import name_enum, nullable
        tokens = p.tokens.get(TOKEN, 0)
        if not tokens or game.role_state.get(SHOT_DAY, {}).get(p.name) == game.day:
            return None
        others = [n for n in game.alive_names() if n != p.name]
        return DayAction(
            {"target": nullable(name_enum(others)), "tokens_to_spend": {"type": "integer"}},
            f"As the Sniper you may also take a shot at one player this turn (once a Day): set target, and "
            f"tokens_to_spend to 1, 2 or 3 for a Basic, Standard or Strong Attack ({tokens_left_text(p, TOKEN)}). "
            "The shot waits a random number of speaking turns, from none (it fires right after this turn) to one less "
            "than the number of living players (rules R25), so others may speak first; you'll be told when it fires. "
            "Everyone then learns the target and whether they died, never who shot. If you die before then, it isn't "
            "fired; if your target dies first, it isn't fired, the tokens come back and you may shoot again that Day. "
            "Leave target null not to shoot.")

    def carry_out_day_action(self, game: Game, p: Player, answer: dict) -> None:
        target, spend = answer.get("target"), answer.get("tokens_to_spend")
        if not target:
            return
        tokens = p.tokens.get(TOKEN, 0)
        if not isinstance(spend, int) or not 1 <= spend <= min(3, tokens):
            game.emit(f"(Program note: your shot at {target} wasn't taken: tokens_to_spend must be 1 to "
                      f"{min(3, tokens)}.)", [p.name])
            game.log.write("day_action_refused", player=p.name, target=target, tokens=spend)
            return
        p.tokens[TOKEN] = tokens - spend
        game.role_state.setdefault(SHOT_DAY, {})[p.name] = game.day
        # Rules R25: a random delay of 0 to n-1 more non-trial speaking turns (Kevin, Oct 12 2026), counted from the end
        # of this one, so even an immediate shot isn't pinned on whoever just spoke.
        delay = game.rng.randint(0, len(game.alive_names()) - 1)
        game.role_state.setdefault(HELD, []).append([p.name, target, ATTACK_LEVELS[spend], delay])
        game.log.write("day_shot_taken", player=p.name, target=target, attack=ATTACK_LEVELS[spend], delay=delay)
        game.tell([p.name], f"You took a {ATTACK_LEVELS[spend]} shot at {target}. It will be fired after a random "
                  f"number of speaking turns (possibly right after this one), and you'll be told then. "
                  f"{tokens_left_text(p, TOKEN)}.")

    def after_day_turn(self, game: Game, p: Player) -> None:
        due: list[list] = []
        waiting: list[list] = []
        for shot in game.role_state.pop(HELD, []):
            (due if shot[3] == 0 else waiting).append(shot)
            shot[3] -= 1
        if waiting:
            game.role_state[HELD] = waiting
        fire_all(game, due)

    def at_day_end(self, game: Game) -> None:
        # The Day ended (a hanging, say) before these were due: they fire now, before Night (Oct 12 2026).
        fire_all(game, game.role_state.pop(HELD, []), day_over=True)


def fire_all(game: Game, shots: list[list], day_over: bool = False) -> None:
    """Fires shots due at the same moment one at a time, in random order (rules R25; one can kill a Sniper whose shot
    is next), stopping once one decides the game, as the Day does (check_winner)."""
    game.rng.shuffle(shots)  # Kevin, Oct 12 2026: not the order they were taken
    for shooter, target, attack, _ in shots:
        if game.check_winner() is not None:
            game.log.write("day_shot_dropped", player=shooter, target=target, reason="game over")
            continue
        fire(game, shooter, target, attack, day_over)


def fire(game: Game, shooter: str, target: str, attack: str, day_over: bool = False) -> None:
    """Fires a held shot: dropped if its shooter died since (rules R25), refunded if its target did."""
    me, victim = game.player(shooter), game.player(target)
    if not me.alive:
        game.log.write("day_shot_dropped", player=shooter, target=target)
        return
    if not victim.alive:  # died since the shot was taken (hanged, say): not fired, tokens back (Kevin, Oct 12 2026)
        me.tokens[TOKEN] = me.tokens.get(TOKEN, 0) + ATTACK_LEVELS.index(attack)
        # The shot never happened, so it doesn't use up the Day's shot (rules: Sniper; Kevin, Oct 12 2026).
        game.role_state.get(SHOT_DAY, {}).pop(shooter, None)
        again = "" if day_over else " You may take another shot today."
        game.tell([shooter], f"{target} died before your shot was fired, so it wasn't fired and its tokens came "
                  f"back.{again} {tokens_left_text(me, TOKEN)}.")
        return
    record_attack(game, shooter)  # an Attack, for results that count them (the Bloodhound's)
    game.log.write("day_shot", player=shooter, target=target, attack=attack, day=game.day)
    text = f"A shot rings out: someone shot at {target}."
    game.emit(text, cat=ANNOUNCEMENT, message=text)
    killed = attack_kills(attack, logic(victim.role).defense(game, victim))
    if killed:
        game.kill(target, "shot by the Sniper", by=shooter)
    else:
        text = f"{target} survived the shot."
        game.emit(text, cat=ANNOUNCEMENT, message=text)
    outcome = "it killed them" if killed else "they survived"
    game.tell([shooter], f"Your shot at {target} was just fired: {outcome}.")
