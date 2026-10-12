"""Bloodhound: each night learns how many attacks three players have made this game; a token picks one of them."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import (CODE_ATTACKS, RecordedAction, RoleLogic, acted_tonight, as_chosen, join_names, register,
                        tokens_left_text)

if TYPE_CHECKING:
    from state import Game, Player

ATTACKS = "attacks"  # game.role_state: night -> the attacker of each attack that night (the moderator's attacks op)
TRACKS = "bloodhound_tracks"  # game.role_state: Bloodhound -> the player they track tonight


def attack_count(game: Game, names: list[str]) -> int:
    """Attacks made by these players over the game so far, tonight's included (the moderator's attacks op, and
    attacks code made, such as a Cursed player's curse)."""
    return sum(a in names for key in (ATTACKS, CODE_ATTACKS) for night in game.role_state.get(key, {}).values()
               for a in night)


@register("Bloodhound")
class Bloodhound(RoleLogic):
    roleplayer_can_fake = False  # code draws the group and counts
    night_end_order = 1  # after a Cursed player's curse, which counts as an attack tonight
    code_tells_user = True
    action = RecordedAction(
        "track", "tracks player (code puts them in tonight's group of three)",
        "code tells them the result at the end of the night", token="scent", visit=True,
        note="Also, every night while the game has a Bloodhound, use the attacks op once with the attacker of every "
        "Attack that happened tonight, fatal or not: the Katana holder for the Katana, a Vigilante's shot, the "
        "Serial Killer, a Veteran's alert for each visitor it hits, a Trapper's trap, an Arsonist's ignite, a "
        "Ritualist's attack (one entry per attack; repeats allowed; [] if there were none). Leave out role-blocked "
        "attackers, Jester revenge and a Cursed player's curse (code handles those). Code counts them for the "
        "Bloodhound's result, which it also gives on nights with no token.")

    def check_op(self, game: Game, change: dict) -> str | None:
        if change["op"] != ATTACKS:
            return super().check_op(game, change)
        names = {p.name for p in game.players}
        attackers = change["attackers"]
        if not isinstance(attackers, list) or not all(isinstance(a, str) for a in attackers):
            return "attackers must be a list of player names"
        for a in attackers:
            if a not in names:  # a dead player is fine: a Trapper's trap lasts after the Trapper dies
                return f"no player named {a!r}"
        return None

    def apply_op(self, game: Game, change: dict) -> str | None:
        if change["op"] != ATTACKS:
            return super().apply_op(game, change)
        game.role_state.setdefault(ATTACKS, {})[game.day] = list(change["attackers"])  # a resend replaces it
        game.log.write("attacks", day=game.day, attackers=change["attackers"])
        return None

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        assert target
        game.role_state.setdefault(TRACKS, {})[by.name] = target.name  # told at the end of the night

    def at_night_end(self, game: Game) -> None:
        tracks = game.role_state.pop(TRACKS, {})
        users = [p for p in game.players if p.role == self.role and acted_tonight(game, p)]
        if not users:
            return
        if game.day not in game.role_state.get(ATTACKS, {}):
            game.log.error("attacks_missing", f"night {game.day}: the moderator didn't record attacks (attacks op), "
                           "so the Bloodhound's count leaves tonight out", day=game.day)
        for p in users:
            target = tracks.get(p.name)
            others = [q.name for q in game.players if acted_tonight(game, q) and q.name not in (p.name, target)]
            drawn = game.rng.sample(others, min(3 - (target is not None), len(others)))
            group = [q.name for q in game.players if q.name in {*drawn, *([target] if target else [])}]
            shown = as_chosen(game, target, group) if target else group  # rules R23
            n = attack_count(game, group)
            text = (f"Your Bloodhound check of {join_names(shown)}: together they have made {n} "
                    f"attack{'' if n == 1 else 's'} this game, tonight's included.")
            if target:
                text += f" {tokens_left_text(p, 'scent')}."
            game.tell([p.name], text)


Bloodhound.ops[ATTACKS] = ({"attackers"}, set(), "{op:'attacks', attackers}: every attack tonight, by its attacker "
                           "(see the Bloodhound's note)")
