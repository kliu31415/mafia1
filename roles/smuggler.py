"""Smuggler: spends a token at night to swap two players, so every action aimed at one lands on the other."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RoleLogic, register, spend_token

if TYPE_CHECKING:
    from state import Game

TARGET_FIELDS = ("target", "second_target", "katana_vote_target")


@register("Smuggler")
class Smuggler(RoleLogic):
    night_note = ("Smuggler: code has already carried out each swap below (spent the token, redirected every other "
                  "action in the JSON and told the Smuggler and both swapped players), so resolve the actions as "
                  "given and tell none of them about the swap. Actions it moved keep the player's own choice in "
                  "`chosen_target` / `chosen_second_target`: word every private result with the player the "
                  "action's user chose, never the one it landed on, and in a list of players trade the swapped "
                  "pair's names (each where the other would be), so the swap stays hidden (rules R23). Give ops "
                  "the player an action landed on: code words its own results this way. The "
                  "Smuggler visits both swapped players (R6); it can't be role-blocked.")
    code_tells_user = True
    roleplayer_can_fake = False  # code carries out the swap and its notices

    def before_resolution(self, game: Game, actions: dict[str, dict]) -> None:
        for name, a in list(actions.items()):
            me = game.player(name)
            if me.role != self.role or not a.get("act"):
                continue
            x, y = a.get("target"), a.get("second_target")
            if me.tokens.get("swap", 0) < 1 or not x or not y or x == y:
                game.tell([name], "Your swap needs a token and two different players, so nothing happened.")
                continue
            left = spend_token(game, name, "swap")
            swap = {x: y, y: x}
            for other, b in actions.items():
                for key in TARGET_FIELDS:
                    if key != "katana_vote_target" and other == name:
                        continue  # the swap itself isn't moved; the Smuggler's Katana vote is (rules R23)
                    if b.get(key) in swap:
                        b.setdefault(f"chosen_{key}", b[key])
                        b[key] = swap[b[key]]
            game.role_state.setdefault("swaps", {}).setdefault(game.day, []).append([name, x, y])
            game.tell([name], f"You swapped {x} and {y}. You have {left} swap token{'s' * (left != 1)} left.")
            for q in (x, y):
                if q != name:
                    game.tell([q], "You were swapped with another player tonight: any action aimed at you "
                                   "landed on them instead.")
