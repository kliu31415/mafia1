"""Trapper: sets a trap that persists across nights. From the night after it's placed, it stops one non-Divine attack
on the trapped player and deals the attacker a Strong Attack if that attack was a visit. The moderator places and
removes traps (status) and lists the attacks on a trapped player; code checks the trap is armed, picks the attack it
stops, uses the trap up and tells the Trapper."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RoleLogic, Status, attacks_error, register, stop_one_attack

if TYPE_CHECKING:
    from state import Game, Player

SPRING = "spring_trap"
ARMED = "armed_traps"  # game.role_state: trapped player -> Trapper, traps standing at the end of the last night
WENT_OFF = "traps_went_off"  # game.role_state: Trapper -> trapped player, traps that went off tonight


@register("Trapper")
class Trapper(RoleLogic):
    code_tells_user = True
    night_note = (
        "Trapper traps persist across nights: set_status key 'trapped_by' to the Trapper's name on the trapped player "
        "when a Trapper places a trap (a new trap replaces its old one at once: set the old player's key to null, "
        "before any spring_trap, so the old trap doesn't act tonight), and to null when a Trapper removes it by "
        "acting with no target. Trapping the player the trap is already on isn't allowed: it has no effect and the "
        "trap stays. A trap is armed from the night after it's placed: if "
        f"anyone made a non-Divine Attack on a trapped player tonight, use the {SPRING} op with every such attack "
        "still standing, each as {by, attack (its level), cause (how its kill would be announced), visit (true if "
        "it was a visit by its attacker, false if Astral or not a visit, e.g. a Veteran's alert or a trap's "
        "hit-back)}. Resolve it right after any protection that acts before all others (a fox charm: leave out the "
        "attack it swallowed) and before Defense (Medic, ...). Code picks the "
        "attack the trap stops and clears the trap: treat that attack as stopped (its attacker and target are told "
        "as for any failed attack, R3; its visit still happened), and code says whether the trap hits its attacker "
        "back. Code tells the Trapper that the trap went off; don't tell() them about it.")
    ops = {
        SPRING: ({"player", "attacks"}, set(),
                 "{op:'spring_trap', player, attacks:[{by, attack, cause, visit}]}: the attacks still standing on a "
                 "trapped player tonight; code says which one the trap stops and whether it hits back"),
    }

    def briefing(self, game: Game, p: Player) -> list[str]:
        # Trappers lost track of whether their trap still stood (game_20261009_121338_61703).
        trapped = [q.name for q in game.players if q.status.get(Status.TRAPPED_BY) == p.name]
        # Kevin, Oct 10: re-trapping the same player is not allowed; removing the trap is.
        return [f"Your trap is on {trapped[0]} and hasn't gone off yet. You can't trap {trapped[0]} again; to remove "
                "the trap without placing a new one, act with no target." if trapped else "You have no trap set."]

    def check_op(self, game: Game, change: dict) -> str | None:
        target = game.player(change["player"])
        trapper = game.role_state.get(ARMED, {}).get(target.name)
        if not trapper:
            return f"{target.name} has no armed trap (a trap is armed from the night after it's placed)"
        if target.status.get(Status.TRAPPED_BY) != trapper:
            return f"{trapper}'s trap on {target.name} was already used up, replaced or removed"
        return attacks_error(game, change["attacks"], visit=True)

    def apply_op(self, game: Game, change: dict) -> str | None:
        target = game.player(change["player"])
        trapper = game.role_state[ARMED][target.name]
        if target.status.get(Status.TRAPPED_BY) != trapper:  # replaced or removed earlier in this same batch
            return (f"{trapper}'s trap on {target.name} was replaced or removed tonight, so it didn't act. Resolve as "
                    "usual.")
        stopped = stop_one_attack(game, target.name, change["attacks"])  # rules: Trapper (one at random)
        game.log.write("trap", trapper=trapper, target=target.name, attacks=change["attacks"], stopped=stopped,
                       day=game.day)
        if not stopped:
            return (f"No non-Divine attack on {target.name} that wasn't already stopped: {trapper}'s trap stays "
                    "armed. Resolve as usual.")
        target.status.pop(Status.TRAPPED_BY, None)
        game.role_state.setdefault(WENT_OFF, {})[trapper] = target.name
        if stopped["visit"]:  # Kevin, Oct 12 2026: whatever the attacker's faction
            back = (f"The trap hits {stopped['by']} back with a Strong Attack by {trapper}: resolve it against "
                    f"{stopped['by']}'s Defense like any attack; if it kills, kill with cause 'Trapper' and by "
                    f"'{trapper}'.")
        else:
            back = f"That attack wasn't a visit, so the trap doesn't hit {stopped['by']} back."
        return (f"{trapper}'s trap on {target.name} stopped {stopped['by']}'s {stopped['attack']} Attack "
                f"('{stopped['cause']}') and is used up. {back} Resolve every other attack on {target.name} normally.")

    def at_night_end(self, game: Game) -> None:
        for trapper in game.role_state.pop(WENT_OFF, {}):
            if game.player(trapper).alive:
                game.tell([trapper], "Your trap went off tonight and is used up.")
        armed = {q.name: q.status[Status.TRAPPED_BY] for q in game.players
                 if q.alive and q.status.get(Status.TRAPPED_BY)}
        if armed or ARMED in game.role_state:
            game.role_state[ARMED] = armed
