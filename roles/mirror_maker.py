"""Mirror Maker: spends a token to place a mirror on a player for the night. The mirror stops every non-Divine attack
on them, after any protection that acts before all others (a fox charm) and before traps and Defense, and reflects
each stopped attack that was a visit back at its attacker, same level and cause. The moderator lists the attacks on
the mirrored player; code picks the ones the mirror stops (never one a charm already took), says which come back at
whom, and tells the Mirror Maker how many it stopped. Designed with Kevin, Oct 15 2026: a reflected kill reads with
the original cause, not "Mirror", so a Mirror death doesn't publicly mark its victim as an attacker."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import (CATCHABLE, STOPPED, RoleLogic, acted_tonight, attacks_error, join_names, register, spend_token,
                        tokens_left_text, token_user_error)

if TYPE_CHECKING:
    from state import Game

TOKEN = "mirror"
OP = "mirror"
# game.role_state, until the end of the night: {"on": {player: [Mirror Makers]}, "stopped": {player: attacks the
# mirrors on them stopped}, "reflected": {attacker: [Mirror Makers whose mirror reflected an attack at them]}}
TONIGHT = "mirrors_tonight"


def tonight(game: Game) -> dict:
    return game.role_state.setdefault(TONIGHT, {"on": {}, "stopped": {}, "reflected": {}})


@register("Mirror Maker")
class MirrorMaker(RoleLogic):
    code_tells_user = True
    roleplayer = "never"  # code tells the result
    night_note = (
        f"Mirror Maker: a Mirror Maker who acted on another player (and wasn't role-blocked) placed a mirror on them "
        f"(it spends a token). Resolve it right after any fox charm (Kitsune) and before traps and Defense: use the "
        f"{OP} op with every non-Divine Attack on the mirrored player tonight (work them all out first, including "
        "attacks other actions set off, such as a Veteran's alert or an Enforcer's attack), each as {by, attack (its "
        "level), cause (how its kill would be announced), visit (true if it was a visit by its attacker, false if "
        "Astral or not a visit, e.g. a Veteran's alert or a trap's hit-back)}, [] if none. Don't list the attacks "
        "code reflects (below). Code says which attacks the mirror stops (all of them, except one a fox charm already "
        "swallowed): treat each as stopped (its attacker and target are told as for any failed attack, R3; its visit "
        "still happened), so traps and Medics on that player have nothing left to stop. For each stopped visit, code "
        "says it is reflected: resolve it as an Attack of the same level on its attacker (an Astral Visit, never "
        "reflected again: a mirror on the attacker just stops it), against their Defense, protection, traps and "
        "charms as usual. If it kills, kill with exactly the stopped attack's cause, by the Mirror Maker, katana "
        "false (a reflected Katana attack reads as a Katana death); a survivor is told they were attacked by that "
        "cause's role (R3), never by a Mirror Maker. Several mirrors on one player: one op each, every one listing "
        "all the attacks; they stop the attacks together. Code tells the Mirror Maker its result; don't tell() it.")
    ops = {
        OP: ({"by", "player", "attacks"}, set(),
             "{op:'mirror', by, player, attacks:[{by, attack, cause, visit}]}: the Mirror Maker `by` placed a mirror "
             "on player (spends a token); attacks = every non-Divine Attack on them tonight; code says which it "
             "stops and reflects"),
    }

    def check_op(self, game: Game, change: dict) -> str | None:
        by, target = game.player(change["by"]), game.player(change["player"])
        if error := token_user_error(game, by.name, self.role, TOKEN):
            return error
        if any(by.name in makers for makers in tonight(game)["on"].values()):
            return f"{by.name}'s mirror is already recorded tonight"
        if target.name == by.name:
            return "a Mirror Maker can't place a mirror on themselves"
        if not acted_tonight(game, target):
            return f"{target.name} wasn't alive at the start of the night"
        return attacks_error(game, change["attacks"], visit=True)

    def apply_op(self, game: Game, change: dict) -> str | None:
        by, target = change["by"], change["player"]
        spend_token(game, by, TOKEN)
        state = tonight(game)
        first = target not in state["on"]
        state["on"].setdefault(target, []).append(by)
        # The attacks a mirror can stop, less those another protection (a fox charm) or mirror already stopped tonight;
        # the shared STOPPED store also keeps a later trap from stopping them again (roles.base.stop_one_attack)
        store = game.role_state.get(STOPPED)
        if not store or store.get("night") != game.day:
            store = game.role_state[STOPPED] = {"night": game.day}
        done = store.setdefault(target, [])
        left = [a for a in change["attacks"] if a["attack"] in CATCHABLE]
        for key in list(done):  # each attack already stopped takes one matching attack out
            left = next(([a for a in left if a is not m] for m in left if [m["by"], m["attack"]] == key), left)
        done.extend([a["by"], a["attack"]] for a in left)
        # rules: Mirror Maker (several mirrors on one player stop the attacks together: each Mirror Maker counts them)
        reflected_here = state["reflected"].get(target, []) if first else []
        state["stopped"][target] = state["stopped"].get(target, 0) + len(left) + len(reflected_here)
        game.log.write("mirror", player=by, target=target, attacks=change["attacks"], stopped=left, day=game.day)
        lines = []
        if reflected_here:
            lines.append(f"{by}'s mirror on {target} also stops what {join_names(reflected_here)}'s mirror reflected "
                         f"back at {target}: treat it as stopped, not reflected again.")
        if not left:
            return " ".join(lines + [f"{by}'s mirror on {target} stopped no other attack: resolve as usual."])
        lines.append(f"{by}'s mirror on {target} stops these attacks: treat them as stopped.")
        for a in left:
            what = f"{a['by']}'s {a['attack']} Attack ('{a['cause']}')"
            if not a["visit"]:
                lines.append(f"{what} wasn't a visit, so it isn't reflected.")
            elif a["by"] in state["reflected"].get(target, []):
                lines.append(f"{what} is a reflected attack, so it isn't reflected again.")
            else:
                state["reflected"].setdefault(a["by"], []).append(by)
                lines.append(f"{what} is reflected: {a['by']} is dealt a {a['attack']} Attack (an Astral Visit). "
                             + self.reflection_text(game, by, a))
        return " ".join(lines)

    @staticmethod
    def reflection_text(game: Game, by: str, attack: dict) -> str:
        attacker = attack["by"]
        if attacker in tonight(game)["on"]:  # their own mirror stops it, without reflecting it again
            tonight(game)["stopped"][attacker] += 1
            return f"{attacker} has a mirror tonight too: it stops this reflected attack, which goes no further."
        return (f"Resolve it against {attacker}'s Defense, protection, traps and charms as usual (if {attacker} has a "
                f"mirror tonight, it just stops it); if it kills, kill with cause '{attack['cause']}' and by '{by}' "
                f"(katana false); if not, {attacker} is told they were attacked by the {attack['cause']} (R3).")

    def at_night_end(self, game: Game) -> None:
        state = game.role_state.pop(TONIGHT, None)
        if not state:
            return
        for target, makers in state["on"].items():
            n = state["stopped"].get(target, 0)
            for maker in makers:
                game.tell([maker], f"Your mirror on {target} stopped {n} attack{'' if n == 1 else 's'} tonight. "
                          f"You have {tokens_left_text(game.player(maker), TOKEN)}.")
