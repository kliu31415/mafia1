"""Trapper: sets a trap that persists across nights. From the night after it's placed, it stops one non-Divine attack
on the trapped player and deals the attacker a Strong Attack if that attack was a visit. The moderator records where a
Trapper places (or removes) its trap and lists the attacks on a trapped player; code keeps the traps, checks which are
armed, picks the attacks they stop, uses them up and tells the Trappers. Several Trappers may trap one player (Kevin,
Oct 12 2026): their traps act one at a time in random order, each stopping a different attack, as fox charms do."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import (RoleLogic, Status, acted_tonight, attacks_error, chosen_name, note_swap_move, register,
                        stop_one_attack, token_user_error)

if TYPE_CHECKING:
    from state import Game, Player

SET, SPRING = "set_trap", "spring_trap"
TRAPS = "traps"  # game.role_state: Trapper -> the player its trap is on, until it's used up, replaced or removed
ARMED = "armed_traps"  # game.role_state: Trapper -> trapped player, traps standing at the end of the last night
WENT_OFF = "traps_went_off"  # game.role_state: Trappers whose trap went off tonight


def traps(game: Game) -> dict[str, str]:
    """The standing traps. A checkpoint from before several traps could share a player kept each one as the
    trapped player's `trapped_by` status (a Trapper's name); those are read once into TRAPS."""
    if TRAPS not in game.role_state:
        game.role_state[TRAPS] = {by: q.name for q in game.players
                                  if isinstance(by := q.status.get(Status.TRAPPED_BY), str)}
        if ARMED in game.role_state:  # was trapped player -> Trapper
            game.role_state[ARMED] = {by: name for name, by in game.role_state[ARMED].items()}
        show_traps(game)
    return game.role_state[TRAPS]


def show_traps(game: Game) -> None:
    """Each trapped player's `trapped_by` status lists the Trappers whose traps are on them, so the moderator's
    state shows the traps; TRAPS is what counts."""
    on: dict[str, list[str]] = {}
    for by, name in game.role_state.get(TRAPS, {}).items():
        on.setdefault(name, []).append(by)
    for q in game.players:
        if q.name in on:
            q.status[Status.TRAPPED_BY] = sorted(on[q.name])
        else:
            q.status.pop(Status.TRAPPED_BY, None)


@register("Trapper")
class Trapper(RoleLogic):
    code_tells_user = True
    night_note = (
        f"Trapper: traps persist across nights and code keeps them. For each Trapper who acted (and wasn't "
        f"role-blocked), use the {SET} op before any {SPRING}: player = where its trap goes, or null if it acted "
        "with no target (that removes its trap). A new trap replaces its old one at once, so the old one doesn't act "
        "tonight. Trapping the player its trap is already on isn't allowed (the trap stays): code refuses it. A trap "
        "is armed from the night after it's placed (trapped_by status lists the traps on a player). If anyone made a "
        f"non-Divine Attack on a player with an armed trap tonight, use the {SPRING} op once for that player with "
        "every such attack still standing, each as {by, attack (its level), cause (how its kill would be announced), "
        "visit (true if it was a visit by its attacker, false if Astral or not a visit, e.g. a Veteran's alert or a "
        "trap's hit-back)}. Resolve it right after any protection that acts before all others (a fox charm: leave out "
        "the attack it swallowed) and before Defense (Medic, ...). Code has every armed trap on that player act in "
        "random order, each stopping a different attack, and uses them up: treat each stopped attack as stopped (its "
        "attacker and target are told as for any failed attack, R3; its visit still happened), and code says whether "
        "each trap hits its attacker back. Code tells the Trappers their results; don't tell() them about traps.")
    ops = {
        SET: ({"by"}, {"player"},
              "{op:'set_trap', by, player|null}: the Trapper `by` places its trap on player (replacing its old one), "
              "or removes it (null)"),
        SPRING: ({"player", "attacks"}, set(),
                 "{op:'spring_trap', player, attacks:[{by, attack, cause, visit}]}: the attacks still standing on a "
                 "player with an armed trap tonight; code says which ones the traps stop and whether they hit back"),
    }

    def briefing(self, game: Game, p: Player) -> list[str]:
        # Trappers lost track of whether their trap still stood (game_20261009_121338_61703).
        on = traps(game).get(p.name)
        # Kevin, Oct 10: re-trapping the same player is not allowed; removing the trap is.
        # Mallory (game_20261012_135656_913688) couldn't tell the two "nothing" answers apart: spell out both.
        return [f"Your trap is on {on} and hasn't gone off yet. You can't trap {on} again. To keep it there, don't "
                "act (act false). To remove it without placing a new one, act with no target (act true, target "
                "null). To move it, act on another player." if on else "You have no trap set."]

    def check_op(self, game: Game, change: dict) -> str | None:
        if change["op"] == SET:
            if error := token_user_error(game, change["by"], self.role):
                return error
            if change.get("player") is None:
                return None if change["by"] in traps(game) else f"{change['by']} has no trap to remove"
            target = game.player(change["player"])
            if not acted_tonight(game, target):
                return f"{target.name} wasn't alive at the start of the night"
            chosen = chosen_name(game, target.name)
            if chosen == change["by"]:
                return "a Trapper can't trap themselves"
            if traps(game).get(change["by"]) == chosen:
                return (f"{change['by']}'s trap is already on {chosen}: trapping them again isn't allowed and the "
                        "trap stays (record nothing)")
            return None
        target = game.player(change["player"])
        if not self.armed_on(game, target.name):
            return (f"{target.name} has no armed trap (a trap is armed from the night after it's placed, and one "
                    "already used up, replaced or removed doesn't act)")
        return attacks_error(game, change["attacks"], visit=True)

    @staticmethod
    def armed_on(game: Game, name: str) -> list[str]:
        """Trappers whose trap was armed on `name` when the night began and still stands there."""
        standing = traps(game)  # first: it converts an older checkpoint's ARMED too
        return sorted(by for by, on in game.role_state.get(ARMED, {}).items() if on == name and standing.get(by) == on)

    def apply_op(self, game: Game, change: dict) -> str | None:
        if change["op"] == SET:
            by, name = change["by"], change.get("player")
            if name is None:
                traps(game).pop(by, None)
                game.log.write("trap_set", trapper=by, target=None, day=game.day)
                show_traps(game)
                return f"{by}'s trap is removed."
            traps(game)[by] = name
            note_swap_move(game, game.player(by), game.player(name), "trap")  # rules R23: told at dawn
            game.log.write("trap_set", trapper=by, target=name, day=game.day)
            show_traps(game)
            return f"{by}'s trap is now on {name} (armed from tomorrow night); any old trap of theirs is gone."
        target = game.player(change["player"])
        armed = self.armed_on(game, target.name)
        if not armed:  # replaced or removed earlier in this same batch
            return f"The trap on {target.name} was replaced or removed tonight, so it didn't act. Resolve as usual."
        game.rng.shuffle(armed)  # rules: Trapper (several traps act one at a time, in random order)
        lines = []
        for trapper in armed:
            stopped = stop_one_attack(game, target.name, change["attacks"])  # rules: Trapper (one at random)
            game.log.write("trap", trapper=trapper, target=target.name, attacks=change["attacks"], stopped=stopped,
                           day=game.day)
            if not stopped:
                lines.append(f"No non-Divine attack on {target.name} left to stop: {trapper}'s trap stays armed.")
                continue
            del traps(game)[trapper]
            game.role_state.setdefault(WENT_OFF, []).append(trapper)
            if stopped["visit"]:  # Kevin, Oct 12 2026: whatever the attacker's faction
                back = (f"The trap hits {stopped['by']} back with a Strong Attack by {trapper}: resolve it against "
                        f"{stopped['by']}'s Defense like any attack; if it kills, kill with cause 'Trapper' and by "
                        f"'{trapper}'.")
            else:
                back = f"That attack wasn't a visit, so the trap doesn't hit {stopped['by']} back."
            lines.append(f"{trapper}'s trap on {target.name} stopped {stopped['by']}'s {stopped['attack']} Attack "
                         f"('{stopped['cause']}') and is used up. {back}")
        show_traps(game)
        return " ".join(lines) + f" Resolve every other attack on {target.name} normally."

    def at_night_end(self, game: Game) -> None:
        for trapper in game.role_state.pop(WENT_OFF, []):
            if game.player(trapper).alive:
                game.tell([trapper], "Your trap went off tonight and is used up.")
        standing = {by: on for by, on in traps(game).items() if game.player(on).alive}
        if standing != traps(game):  # a trap on a player who died is gone
            game.role_state[TRAPS] = standing
            show_traps(game)
        if standing or ARMED in game.role_state:
            game.role_state[ARMED] = dict(standing)
