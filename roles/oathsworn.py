"""Oathsworn: a Yakuza with one oath token, never more. It marks a player at night (a visit); if the Oathsworn is dead
when the next Night begins, that Night the marked player and every other player who visits them are dealt a Divine
Attack (Astral Visits). Code says at the start of that Night whether the mark fires; after record_visits the
moderator's fulfil_oath op lists the attacks from the recorded visits (like the Werewolf's rampage), and the
moderator resolves them. Designed with Kevin, Oct 15 2026: one token (Stocked can't add one, RoleInfo.token_cap)
makes a wrong bet cost the role its ability; any death counts, not only a hanging."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RecordedAction, RoleLogic, join_names, register

if TYPE_CHECKING:
    from state import Game, Player

ROLE = "Oathsworn"
OP = "fulfil_oath"
CAUSE = "a blood oath"
MARKS = "oathsworn_marks"  # game.role_state: [[oathsworn, target, night], ...], marks not yet settled
FIRING = "oathsworn_firing"  # game.role_state: {"night": day, "pending": {oathsworn: target}, "done": [oathsworn]}


def firing(game: Game) -> dict:
    """Tonight's firing oaths (set by tonight_note as the night's resolution begins)."""
    state = game.role_state.get(FIRING)
    return state if state and state["night"] == game.day else {"night": game.day, "pending": {}, "done": []}


@register(ROLE)
class Oathsworn(RoleLogic):
    action = RecordedAction("swear", "marks player with its oath token (a visit)",
                            "nothing happens tonight; code says at the start of the next Night whether the mark fires",
                            token="oath", visit=True)
    night_note = (
        "Oathsworn: an Oathsworn who spent its token (and wasn't role-blocked) marks its target: use the swear op, "
        "which spends the token; it is a visit to the target only, and nothing else happens that night (nobody is "
        "told). On the next Night, if the Oathsworn is dead when the Night begins, code says so in tonight's notes: "
        f"call record_visits first, then the {OP} op ({{op:'{OP}', by: <the dead Oathsworn>}}): code lists the "
        f"Divine Attacks, cause '{CAUSE}', on the marked player and on every other player who visited them tonight "
        "(Astral Visits, not visits; Astral visitors aren't hit). Divine Attacks beat every Defense and ignore "
        "protection, traps, charms, mirrors and Narrow Escape, so each one kills.")

    def briefing(self, game: Game, p: Player) -> list[str]:
        return ["To mark a player, set act=true and target to them: it spends your only oath token, and you can "
                "never get another. If you are dead when the next Night begins, they and everyone who visits them "
                "that Night are dealt a Divine Attack, Yakuza included, so tell your teammates not to visit them. If "
                "you are still alive then, the mark lapses."]

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        assert target
        game.role_state.setdefault(MARKS, []).append([by.name, target.name, game.day])  # rules R21: survives its user
        game.log.write("oathsworn_mark", player=by.name, target=target.name, day=game.day)

    def tonight_note(self, game: Game) -> str:
        """rules (Oathsworn): a mark made last night fires tonight iff the Oathsworn is dead as this Night begins."""
        marks = game.role_state.get(MARKS, [])
        due = [m for m in marks if m[2] < game.day]
        game.role_state[MARKS] = [m for m in marks if m[2] >= game.day]
        state: dict = {"night": game.day, "pending": {}, "done": []}
        lines = []
        for who, target, night in due:
            if night != game.day - 1:
                continue
            fires = not game.player(who).alive and game.player(target).alive
            game.log.write("oathsworn_fires" if fires else "oathsworn_lapses", player=who, target=target, day=game.day)
            if fires:
                state["pending"][who] = target
                lines.append(f"{who}, an Oathsworn, is dead, so the mark it made last night on {target} fires "
                             f"tonight: call record_visits, then the {OP} op with by={who}; it needs no action, so "
                             "no role-block stops it. Never say who the Oathsworn was.")
        game.role_state[FIRING] = state
        return "\n- ".join(lines)

    def check_op(self, game: Game, change: dict) -> str | None:
        if change["op"] != OP:
            return super().check_op(game, change)
        by = change["by"]
        state = firing(game)
        if by not in state["pending"]:
            return f"{by} has no Oathsworn mark firing tonight (code lists it in tonight's notes)"
        if by in state["done"]:
            return f"{by}'s oath is already recorded tonight"
        if game.night_visits.get(game.day) is None:
            return "call record_visits with tonight's visits first: the oath's victims come from them"
        return None

    def apply_op(self, game: Game, change: dict) -> str | None:
        if change["op"] != OP:
            return super().apply_op(game, change)
        by = change["by"]
        state = game.role_state[FIRING]
        target = state["pending"][by]
        state["done"].append(by)
        visits = game.night_visits[game.day]
        visitors = list(dict.fromkeys(v for v, t in visits if t == target and v not in (by, target)))
        game.log.write("oath_fulfilled", player=by, target=target, visitors=visitors, day=game.day)
        hit = f"{target}" + (f" and on {join_names(visitors)}, who visited them tonight" if visitors else
                             " (nobody else visited them tonight)")
        return (f"{by}'s oath deals a Divine Attack, cause '{CAUSE}', by {by}, on {hit}. These are Astral Visits "
                "(not visits). Nothing stops a Divine Attack, so kill each of them (one kill op per player, naming "
                "every fatal cause).")

    def at_night_end(self, game: Game) -> None:
        state = firing(game)
        if missed := [o for o in state["pending"] if o not in state["done"]]:
            game.log.error("oathsworn_missed", f"night {game.day}: the moderator didn't use the {OP} op for "
                           f"{join_names(missed)}, so their oath didn't happen", day=game.day)


Oathsworn.ops = {**Oathsworn.ops, OP: ({"by"}, set(),
                                       f"{{op:'{OP}', by}}: the dead Oathsworn `by`'s mark fires tonight (only when "
                                       "tonight's notes say so); needs record_visits first; code lists the Divine "
                                       "Attacks it deals")}
