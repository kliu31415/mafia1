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
                  "actions aren't visits and have no effect: no other role sees or is affected by them, so never put "
                  "them in record_visits (rules: Roleplayer). Exception: for a role whose results code gives (named "
                  "in tonight's notes), handle them as a real user of that role and don't invent anything.")

    # They must not be able to tell they aren't the real role: same tokens, alignment and night prompts.
    def setup(self, game: Game, p: Player) -> None:
        from roles import ROLES, logic
        from scripts import script_roles
        options = [r for r, i in ROLES.items() if i.category == "Investigative" and logic(r).roleplayer != "never"]
        on_script = [r for r in options if r in script_roles(game)]  # a fake role off the script would give it away
        fake = game.rng.choice(on_script or options)
        p.status[Status.FAKE_ROLE] = fake
        p.tokens = dict(ROLES[fake].tokens)

    def believed_role(self, p: Player) -> str:
        return p.status.get(Status.FAKE_ROLE) or p.role  # none before setup (or in tests that skip it)

    def tonight_note(self, game: Game) -> str:
        from roles import logic
        coded = [f"{p.name} believes they are a {fake}" for p in game.players if p.role == self.role
                 and (fake := self.believed_role(p)) != p.role and logic(fake).roleplayer == "code"]
        if not coded:
            return ""
        return (f"Roleplayers whose results code gives: {'; '.join(coded)}. Use that role's op for them exactly as "
                "for a real user, and its night note's other steps; code gives them a random result. Don't tell() "
                "them a result, and don't put their actions in record_visits (they aren't visits).")

    def shown_role(self, p: Player) -> str:
        from roles import ROLES
        return f"{p.status[Status.FAKE_ROLE]} ({ROLES[p.status[Status.FAKE_ROLE]].alignment.value})"

    def acts_at_night(self, game: Game, p: Player) -> bool:
        from roles import ROLES
        return ROLES[p.status[Status.FAKE_ROLE]].acts_at_night
