"""Sniper: on its own Day turns, takes an anonymous shot at a player with 1-3 tokens (rules R25). Code fires it when
the round ends: everyone hears the shot and its target, then the death or that the target survived; nobody learns
who shot."""

from __future__ import annotations

from typing import TYPE_CHECKING

from events import ANNOUNCEMENT
from roles.base import ATTACK_LEVELS, DayAction, RoleLogic, attack_kills, record_attack, register, tokens_left_text

if TYPE_CHECKING:
    from state import Game, Player

TOKEN = "sniper"
SHOT_DAY = "sniper_shot_day"  # game.role_state: Sniper -> the last Day they took a shot (one shot a Day)
HELD = "sniper_held"  # game.role_state: [shooter, target, attack] shots taken this round, fired at its end


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
            "The shot isn't fired at once: it waits until this round of turns ends (rules R25), so others may speak "
            "first, and you'll be told when it fires. Everyone then learns the target and whether they died, never "
            "who shot. If you die before then, it isn't fired; if your target dies first, it isn't fired and the "
            "tokens come back. Leave target null not to shoot.")

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
        game.role_state.setdefault(HELD, []).append([p.name, target, ATTACK_LEVELS[spend]])
        game.tell([p.name], f"You took a {ATTACK_LEVELS[spend]} shot at {target}. It will be fired when this round "
                  f"of turns ends, and you'll be told then. {tokens_left_text(p, TOKEN)}.")

    def at_round_end(self, game: Game) -> None:
        # All of a round's shots fire together (rules R25), so who fires is decided before any of them lands: two
        # Snipers shooting each other both fire (game_20261012_022615_186854). A Sniper who died since (hanged, say)
        # doesn't fire (Kevin, Oct 12 2026).
        held = [s for s in game.role_state.pop(HELD, []) if game.player(s[0]).alive]
        alive = set(game.alive_names())
        for shooter, target, attack in held:
            victim = game.player(target)
            if target not in alive:  # died this round (hanged, say): not fired, tokens back (Kevin, Oct 12 2026)
                me = game.player(shooter)
                me.tokens[TOKEN] = me.tokens.get(TOKEN, 0) + ATTACK_LEVELS.index(attack)
                game.tell([shooter], f"{target} died before your shot was fired, so it wasn't fired and its tokens "
                          f"came back. {tokens_left_text(me, TOKEN)}.")
                continue
            record_attack(game, shooter)  # an Attack, for results that count them (the Bloodhound's)
            game.log.write("day_shot", player=shooter, target=target, attack=attack, day=game.day)
            text = f"A shot rings out: someone shot at {target}."
            game.emit(text, cat=ANNOUNCEMENT, message=text)
            killed = attack_kills(attack, victim.info.defense)
            if killed:
                game.kill(target, "shot by the Sniper", by=shooter)
            else:
                text = f"{target} survived the shot."
                game.emit(text, cat=ANNOUNCEMENT, message=text)
            outcome = "it killed them" if killed else "they survived"
            game.tell([shooter], f"Your shot at {target} was just fired: {outcome}.")
