"""Vulture: wins alone once few enough players are left at the start of a day. Each dawn, code tells it a role for
each new death: the true one half the time, otherwise a different random role."""

from __future__ import annotations

from typing import TYPE_CHECKING

from events import ANNOUNCEMENT
from roles.base import RoleLogic, Status, register

REPORTED = "vulture_reported"  # role_state: dead players the Vulture has already had a report on
TRUE_SHARE = 0.5  # rules (Vulture): the chance each report shows the true role


def threshold(game) -> int:
    """Rules (Vulture): max(floor(N/4), 2), N the number of players at the start."""
    return max(len(game.players) // 4, 2)

if TYPE_CHECKING:
    from state import Game, Player


@register("Vulture")
class Vulture(RoleLogic):
    def briefing(self, game: Game, p: Player) -> list[str]:
        return [f"You win if you are alive at the start of a Day with {threshold(game)} or fewer players alive "
                "(counting yourself)."]

    def at_dawn(self, game: Game) -> None:
        vultures = [p for p in game.alive() if p.role == "Vulture"]
        report_deaths(game, vultures)
        if vultures and len(game.alive()) <= threshold(game):
            game.sole_winner = vultures[0].name
            text = f"{vultures[0].name} is the Vulture: only {len(game.alive())} players are left, so they win alone."
            game.emit(text, cat=ANNOUNCEMENT, message=text)


def report_deaths(game: Game, vultures: list[Player]) -> None:
    """Rules (Vulture): a role for each player who died since the last report (not those who left), true with
    TRUE_SHARE chance, else a different role from the script's roles (exact-role check: a Roleplayer is one)."""
    from scripts import script_roles
    reported: list[str] = game.role_state.setdefault(REPORTED, [])
    new = [p for p in game.players if p.death and not p.status.get(Status.LEFT) and p.name not in reported]
    reported += [p.name for p in new]
    if not new:
        return
    for v in vultures:
        lines = []
        for p in new:
            fakes = sorted(r for r in script_roles(game) if r != p.role)
            role = p.role if game.rng.random() < TRUE_SHARE else game.rng.choice(fakes)
            lines.append(f"{p.name}: {role}")
        game.tell([v.name], "Your report on the dead (each role is the true one with 50% chance, otherwise a "
                            "different random role; you aren't told which): " + "; ".join(lines) + ".")
