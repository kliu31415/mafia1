"""Kitsune: each night lays a fox charm that swallows one non-Divine attack on a player, before any other protection;
it keeps the swallowed attack and must release it on a later night, at the same level and with the same cause. Code
picks the swallowed attack, keeps the charge and tells the Kitsune; the moderator resolves the attacks themselves."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import (RoleLogic, acted_tonight, attacks_error, chosen_name, register, spend_token, stop_one_attack,
                        swap_partner, token_user_error)

if TYPE_CHECKING:
    from state import Game, Player

TOKEN = "kitsune"  # charming yourself spends one
CHARM, RELEASE = "kitsune_charm", "kitsune_release"
CHARGE = "kitsune_charge"  # game.role_state: Kitsune -> {"attack": level, "cause": its announced cause}, until released
TONIGHT = "kitsune_tonight"  # game.role_state: Kitsune -> what it did tonight, for its result at the end of the night


def charge_text(charge: dict) -> str:
    return f"a {charge['attack']} Attack announced as '{charge['cause']}'"


@register("Kitsune")
class Kitsune(RoleLogic):
    code_tells_user = True
    roleplayer_can_fake = False  # code keeps the charge
    night_note = (
        "Kitsune: a Kitsune with no swallowed attack who acted (and wasn't role-blocked) laid a fox charm on its "
        f"target. Resolve the charm FIRST, before any other protection (Medic, Trapper, ...): use the {CHARM} op "
        "with every non-Divine Attack on the charmed player tonight, each as {by, attack (its level), cause (how its "
        "kill would be announced, e.g. 'Katana', 'Serial Killer')}, [] if none. Code picks the one the charm "
        "swallows and says which: treat it as stopped (its attacker and target are told as for any failed attack, "
        "R3; its visit still happened), then resolve the other attacks normally. Several charms on one player: one "
        f"{CHARM} op each, every one listing all the attacks; code has them act in random order, each swallowing a "
        f"different attack. A Kitsune holding a swallowed attack can't charm; if it acted with a target (and wasn't "
        f"role-blocked), use the {RELEASE} op: code says the attack's level and cause, and you resolve it like any "
        "attack by the Kitsune on that target (a visit). "
        "If it kills, kill with exactly that cause, by the Kitsune, katana false; a survivor is told they were "
        "attacked by that cause's role (R3), never by a Kitsune. Code tells the Kitsune its results; don't tell() it "
        "about the charm or the release.")
    ops = {
        CHARM: ({"by", "player", "attacks"}, set(),
                "{op:'kitsune_charm', by, player, attacks:[{by, attack, cause}]}: the Kitsune `by` charmed player "
                "(themselves: spends a token); attacks = every non-Divine Attack on them tonight; code says which one "
                "the charm swallowed"),
        RELEASE: ({"by", "player"}, set(),
                  "{op:'kitsune_release', by, player}: the Kitsune `by` releases its swallowed attack on player; code "
                  "says its level and cause"),
    }

    def briefing(self, game: Game, p: Player) -> list[str]:
        charge = game.role_state.get(CHARGE, {}).get(p.name)
        if charge:
            return [f"You hold a swallowed attack: {charge_text(charge)}. You can't lay a charm until you release it. "
                    "To release it, name a target (not yourself); to keep holding it, don't act. It's lost if you "
                    "die."]
        return ["You hold no swallowed attack: each night you may lay your fox charm on another player (on yourself "
                "it costs your kitsune token; set tokens_to_spend to 1)."]

    def on_death(self, game: Game, p: Player, guilty_voters: list[str] | None) -> None:
        if game.phase == "day":  # at night the charge waits for the end of the night: a release tonight still acts
            game.role_state.get(CHARGE, {}).pop(p.name, None)

    def check_op(self, game: Game, change: dict) -> str | None:
        by, target = game.player(change["by"]), game.player(change["player"])
        charge = game.role_state.get(CHARGE, {}).get(by.name)
        if error := token_user_error(game, by.name, self.role):
            return error
        if done := game.role_state.get(TONIGHT, {}).get(by.name):  # one action a night: a charm or a release
            return f"{by.name}'s {done[0][0]} is already recorded tonight"
        if not acted_tonight(game, target):
            return f"{target.name} wasn't alive at the start of the night"
        if change["op"] == RELEASE:
            if not charge:
                return f"{by.name} holds no swallowed attack to release"
            if target is by and not swap_partner(game, by.name):
                return "a Kitsune can't release its attack on itself"
            return None
        if charge:
            return f"{by.name} holds a swallowed attack, so it can't charm until it releases it ({RELEASE})"
        if target is by and not swap_partner(game, by.name) and by.tokens.get(TOKEN, 0) < 1:
            return f"{by.name} has no {TOKEN} token left to charm themselves"
        return attacks_error(game, change["attacks"])

    def apply_op(self, game: Game, change: dict) -> str | None:
        by, target = game.player(change["by"]), game.player(change["player"])
        tonight = game.role_state.setdefault(TONIGHT, {}).setdefault(by.name, [])
        if change["op"] == RELEASE:
            charge = game.role_state[CHARGE].pop(by.name)
            tonight.append([RELEASE, target.name, charge, chosen_name(game, target.name)])
            game.log.write("kitsune_release", player=by.name, target=target.name, **charge, day=game.day)
            return (f"{by.name}'s released attack on {target.name} is {charge_text(charge)}: resolve it against "
                    f"{target.name}'s Defense like any attack. If it kills, kill with cause '{charge['cause']}' and by "
                    f"'{by.name}' (katana false); if not, {target.name} is told they were attacked by the "
                    f"{charge['cause']} (R3).")
        if target is by and not swap_partner(game, by.name):
            spend_token(game, by.name, TOKEN)
        # rules: Kitsune (one at random). Several charms on one player: each picks at random among the attacks the
        # earlier ones left, the same as acting in random order
        swallowed = stop_one_attack(game, target.name, change["attacks"])
        if swallowed:
            charge = {"attack": swallowed["attack"], "cause": swallowed["cause"].strip()}
            game.role_state.setdefault(CHARGE, {})[by.name] = charge
        tonight.append([CHARM, target.name, swallowed and game.role_state[CHARGE][by.name],
                        chosen_name(game, target.name)])
        game.log.write("kitsune_charm", player=by.name, target=target.name, attacks=change["attacks"],
                       swallowed=swallowed, day=game.day)
        if not swallowed:
            return f"{by.name}'s charm on {target.name} swallowed nothing (no non-Divine attack): resolve as usual."
        return (f"{by.name}'s charm on {target.name} swallowed {swallowed['by']}'s {swallowed['attack']} Attack "
                f"('{swallowed['cause']}'): it is stopped; resolve every other attack on {target.name} normally.")

    def at_night_end(self, game: Game) -> None:
        for name, done in game.role_state.pop(TONIGHT, {}).items():
            me = game.player(name)
            for op, target, charge, chosen in done:  # results name the chosen player, not a swap's (rules R23)
                if op == CHARM:
                    game.tell([name], f"Your fox charm on {chosen} swallowed {charge_text(charge)}."
                              + (" Release it on a later night (you can't charm until you do)." if me.alive else "")
                              if charge else f"Your fox charm on {chosen} swallowed no attack tonight.")
                    continue
                death = game.player(target).death
                killed = bool(death and death["day"] == game.day and name in death["killers"])
                if killed and death and charge["cause"].lower() not in death["cause"].lower():
                    game.log.error("kitsune_cause", f"night {game.day}: {target} died to {name}'s released attack "
                                   f"with cause {death['cause']!r}, not {charge['cause']!r}", day=game.day)
                game.tell([name], f"Your released attack on {chosen} " + ("killed them." if killed else
                                                                          "didn't kill them."))
        for name in list(game.role_state.get(CHARGE, {})):  # a dead Kitsune's swallowed attack is gone
            if not game.player(name).alive:
                del game.role_state[CHARGE][name]
