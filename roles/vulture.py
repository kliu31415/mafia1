"""Vulture: wins alone once few enough players are left at the start of a day."""

from events import ANNOUNCEMENT
from roles.base import RoleLogic, register


def threshold(game) -> int:
    """Rules (Vulture): max(floor(N/4), 2), N the number of players at the start."""
    return max(len(game.players) // 4, 2)


@register("Vulture")
class Vulture(RoleLogic):
    def briefing(self, game, p):
        return [f"You win if you are alive at the start of a Day with {threshold(game)} or fewer players alive "
                "(counting yourself)."]

    def at_dawn(self, game):
        vultures = [p for p in game.alive() if p.role == "Vulture"]
        if vultures and len(game.alive()) <= threshold(game):
            game.sole_winner = vultures[0].name
            text = f"{vultures[0].name} is the Vulture: only {len(game.alive())} players are left, so they win alone."
            game.emit(text, cat=ANNOUNCEMENT, message=text)
