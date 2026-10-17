"""Werewolf: on even nights (the full moon) rampages at a player's house, a Strong Attack on them and on everyone who
visits them, or at home, on everyone who visits the Werewolf. The moderator records the rampage with the rampage op
after record_visits; code lists the attacks it deals from the recorded visits, and the moderator resolves them as usual.
Designed with Kevin, Oct 15 2026 (Town of Salem 2's rampage): a home rampage isn't a visit and isn't an Attack of the
Werewolf's own choosing (Enforcer), like a Veteran's alert; hits on visitors aren't visits."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RoleLogic, acted_tonight, join_names, register, token_user_error

if TYPE_CHECKING:
    from state import Game, Player

OP = "rampage"
TONIGHT = "rampages_tonight"  # game.role_state: {"night": day, "by": [Werewolves whose rampage is recorded tonight]}


def full_moon(game: Game) -> bool:
    """rules: Werewolf (it acts only on even-numbered Nights)."""
    return game.day % 2 == 0


@register("Werewolf")
class Werewolf(RoleLogic):
    night_note = (
        f"Werewolf: on even-numbered Nights only, a Werewolf who acted (and wasn't role-blocked) rampages: at its "
        f"target's house (a visit to them; put it in record_visits) or, with no target or itself as target, at home "
        f"(not a visit). Call record_visits first, then the {OP} op ({{op:'{OP}', by, player}}, player left out for a "
        "home rampage): code lists the Strong Attacks it deals, cause 'Werewolf', from the recorded visits: on the "
        "target (a visit) and on every other player who visited the target (or, at home, the Werewolf) tonight, of "
        "any faction (not visits; Astral Visits aren't visits, so they aren't hit). Resolve each like any attack "
        "(Defense, Medics, charms, traps, mirrors: give the visit flag code gives). An Enforcer counts a rampage at a "
        "player's house, its hits on visitors included, as an Attack of the Werewolf's own choosing; a home rampage "
        "doesn't count. Tell the Werewolf how many players it attacked and how many of those attacks killed (an "
        "attack a mirror reflects back at the Werewolf isn't one of them), never who the visitors were (e.g. 'Your "
        "rampage attacked 3 players and killed 2 of them').")
    ops = {
        OP: ({"by"}, {"player"},
             f"{{op:'{OP}', by, player}}: the Werewolf `by` rampaged at player's house, or at home if player is left "
             "out or is `by`; needs record_visits first; code lists the attacks it deals"),
    }

    def acts_at_night(self, game: Game, p: Player) -> bool:
        return full_moon(game)

    def briefing(self, game: Game, p: Player) -> list[str]:
        return ["To rampage at a player's house, set act=true and target to them; to rampage at home, set act=true "
                "and leave target empty. You are asked for an action only on even-numbered Nights."]

    def check_op(self, game: Game, change: dict) -> str | None:
        by = game.player(change["by"])
        if error := token_user_error(game, by.name, self.role):
            return error
        if not full_moon(game):
            return f"Night {game.day} isn't an even-numbered Night: a Werewolf can't rampage"
        state = game.role_state.get(TONIGHT)
        if state and state["night"] == game.day and by.name in state["by"]:
            return f"{by.name}'s rampage is already recorded tonight"
        visits = game.night_visits.get(game.day)
        if visits is None:
            return "call record_visits with tonight's visits first: the rampage's victims come from them"
        target = change.get("player") or by.name
        if not acted_tonight(game, game.player(target)):
            return f"{target} wasn't alive at the start of the night"
        if target != by.name and [by.name, target] not in visits:
            return (f"record_visits has no visit by {by.name} to {target}: a rampage at a player's house is a "
                    "visit, so call record_visits again with it first")
        return None

    def apply_op(self, game: Game, change: dict) -> str | None:
        by = change["by"]
        target = change.get("player") or by
        state = game.role_state.get(TONIGHT)
        if not state or state["night"] != game.day:
            state = game.role_state[TONIGHT] = {"night": game.day, "by": []}
        state["by"].append(by)
        visits = game.night_visits[game.day]
        visitors = list(dict.fromkeys(v for v, t in visits if t == target and v not in (by, target)))
        home = target == by
        game.log.write("rampage", player=by, target=None if home else target, visitors=visitors, day=game.day)
        hits = [] if home else [f"{target} (a visit)"]
        if visitors:
            hits.append(f"{join_names(visitors)} (visitors; not visits)")
        where = "at home" if home else f"at {target}'s house"
        if not hits:
            return (f"{by}'s rampage {where}: nobody visited, so it attacks no one. Tell {by} its rampage attacked "
                    "nobody.")
        return (f"{by}'s rampage {where} deals a Strong Attack, cause 'Werewolf', by {by}, to: {'; '.join(hits)}. "
                f"Resolve each like any attack, then tell {by} how many players it attacked "
                f"({len(visitors) + (0 if home else 1)}) and how many of those attacks killed, never who the visitors "
                "were.")
