"""Roleplayer: believes they have a random Investigative role; the moderator invents their results."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RoleLogic, Status, register

if TYPE_CHECKING:
    from state import Game, Player


@register("Roleplayer")
class Roleplayer(RoleLogic):
    # Kevin, Oct 13 2026: random rather than "usually false but plausible", which players couldn't weigh and which
    # mostly gave anti-information (game_20261012_135656_913688).
    night_note = ("Give the Roleplayer random results for the role they believe they have (their status "
                  "'fake_role'): draw each result with random_choice from the results that role could get tonight "
                  "(e.g. Evil or Not Evil; CORRECT or WRONG; Same or Different; a number of visitors from 0 to the "
                  "players alive; a random living player, or nobody), ignoring what really happened. Their own "
                  "actions aren't visits and have no effect: no other role sees or is affected by them (rules: "
                  "Roleplayer).")

    # They must not be able to tell they aren't the real role: same tokens, alignment and night prompts.
    def setup(self, game: Game, p: Player) -> None:
        from roles import ROLES, logic
        from scripts import script_roles
        options = [r for r, i in ROLES.items() if i.category == "Investigative" and logic(r).roleplayer_can_fake]
        on_script = [r for r in options if r in script_roles(game)]  # a fake role off the script would give it away
        fake = game.rng.choice(on_script or options)
        p.status[Status.FAKE_ROLE] = fake
        p.tokens = dict(ROLES[fake].tokens)

    def shown_role(self, p: Player) -> str:
        from roles import ROLES
        return f"{p.status[Status.FAKE_ROLE]} ({ROLES[p.status[Status.FAKE_ROLE]].alignment.value})"

    def acts_at_night(self, game: Game, p: Player) -> bool:
        from roles import ROLES
        return ROLES[p.status[Status.FAKE_ROLE]].acts_at_night
