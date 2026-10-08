"""The hooks a role can implement, and the registry core code looks roles up in.

Core code (state.py, players.py, day.py, night.py) calls these hooks at fixed points without naming
any role, so a role's code-handled effects live in one file under roles/. Roles without a file get
the defaults, which do nothing; the LLM moderator resolves their abilities from the rules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from state import Game, Player


class Status:
    """Player.status keys that code reads. The moderator may also set its own keys (e.g. doused)."""

    LEFT = "left"  # left the game (a winning Executioner); not a death
    CLEANED = "cleaned"  # Mortician: the death reveal hides role and will
    TARGET = "target"  # Executioner's target
    FAKE_ROLE = "fake_role"  # the role a Roleplayer believes they have


class RoleLogic:
    """Defaults for every hook. Subclass it in roles/<role>.py and decorate with @register."""

    def setup(self, game: Game, p: Player) -> None:
        """After seats and the Katana are assigned. Use game.rng for anything random."""

    def shown_role(self, p: Player) -> str:
        """The role the player is told they have."""
        return f"{p.role} ({p.info.alignment.value})"

    def briefing(self, game: Game, p: Player) -> list[str]:
        """Extra sentences for the player's role briefing (shown in every prompt)."""
        return []


LOGIC: dict[str, RoleLogic] = {}
DEFAULT = RoleLogic()


def register(role: str):
    def wrap(cls: type[RoleLogic]) -> type[RoleLogic]:
        LOGIC[role] = cls()
        return cls
    return wrap


def logic(role: str) -> RoleLogic:
    return LOGIC.get(role, DEFAULT)
