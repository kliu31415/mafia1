"""The hooks a role can implement, and the registry core code looks roles up in.

Core code (state.py, players.py, day.py, night.py) calls these hooks at fixed points without naming
any role, so a role's code-handled effects live in one file under roles/. Roles without a file get
the defaults, which do nothing; the LLM moderator resolves their abilities from the rules.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from state import Game, Player


class Alignment(str, Enum):
    GOOD = "Good"  # the Village faction
    EVIL = "Evil"  # the Yakuza faction
    NEUTRAL = "Neutral"  # each Neutral player is their own faction


class Status:
    """Player.status keys that code reads. The moderator may also set its own keys (e.g. doused)."""

    LEFT = "left"  # left the game (a winning Executioner); not a death
    CLEANED = "cleaned"  # Mortician: the death reveal hides role and will
    TARGET = "target"  # Executioner's target
    FAKE_ROLE = "fake_role"  # the role a Roleplayer believes they have
    SET_AT_SETUP = (TARGET, FAKE_ROLE)  # role hooks read these directly, so the moderator can't change them


class RoleLogic:
    """Defaults for every hook. Subclass it in roles/<role>.py and decorate with @register.
    Per-game state a role needs goes in game.role_state, keyed by something role-specific."""

    blocks_win: bool = True  # False for Neutrals the win check ignores (rules: "if we ignore Jesters...")
    # False for roles whose results code delivers (live PMs, random samples), which the moderator can't fake
    # for a Roleplayer who believes they have the role.
    roleplayer_can_fake: bool = True
    # Reminder for the moderator's night resolution, for effects with no submitted action or that
    # need a special op. Included when anyone in the game has (or had) the role.
    night_note: str = ""
    # Extra apply_changes ops for the moderator, offered only when someone in the game has the role:
    # op -> (required fields, optional fields, description shown in the tool). apply_op carries them out.
    ops: dict[str, tuple[set[str], set[str], str]] = {}

    def setup(self, game: Game, p: Player) -> None:
        """After seats and the Katana are assigned. Use game.rng for anything random."""

    def shown_role(self, p: Player) -> str:
        """The role the player is told they have."""
        return f"{p.role} ({p.info.alignment.value})"

    def acts_at_night(self, p: Player) -> bool:
        """Whether the player is asked for a night action (Yakuza always are, for the Katana vote)."""
        return p.info.acts_at_night

    def automatic_action(self, game: Game, p: Player) -> dict | None:
        """A night action code draws for a living player each night without asking them (e.g. the Ex-Con's random
        visit), in night_action_schema's shape. It goes in the night's actions for the moderator, the logs and the
        reveal, marked "automatic"; the player's own night history leaves it out."""
        return None

    def briefing(self, game: Game, p: Player) -> list[str]:
        """Extra sentences for the player's role briefing (shown in every prompt)."""
        return []

    def on_death(self, game: Game, p: Player, guilty_voters: list[str] | None) -> None:
        """This player just died. guilty_voters is set only for an execution by hanging."""

    def on_other_death(self, game: Game, me: Player, dead: Player, guilty_voters: list[str] | None) -> None:
        """Another player just died; called for every living player of this role."""

    def hears_pm(self, game: Game, me: Player, speaker: str, to: str) -> bool:
        """Whether this living, unpuppeted player also reads the contents of a Day private message from
        `speaker` to `to` (Wiretap, Eavesdropper)."""
        return False

    def trial_vote_weight(self, game: Game, p: Player) -> int:
        """How many votes this player's Guilty/Innocent vote counts as today (Ballot Stuffer)."""
        return 1

    def check_op(self, game: Game, change: dict) -> str | None:
        """Why one of this role's ops can't be carried out (the whole batch is then refused, so nothing is
        half-applied), or None if it can. Fields are already checked against `ops`."""
        return None

    def apply_op(self, game: Game, change: dict) -> None:
        """Carry out one of this role's ops. Fields are already checked against `ops`, and player
        names against the game."""
        raise NotImplementedError(change["op"])

    def at_dawn(self, game: Game) -> None:
        """Start of each day, after the night's deaths are revealed. Called once per registered role,
        whether or not anyone has it, so it can act after its player has died."""


LOGIC: dict[str, RoleLogic] = {}
DEFAULT = RoleLogic()


def token_user_error(game: Game, by_name: str, role: str, kind: str) -> str | None:
    """check_op for an op that spends one of `role`'s `kind` tokens: None if `by` can spend one."""
    by = game.player(by_name)
    if by.role != role or not by.alive:
        return f"{by.name} is not a living {role}"
    if by.tokens.get(kind, 0) < 1:
        return f"{by.name} has no {kind} token left"
    return None


def register(role: str):
    def wrap(cls: type[RoleLogic]) -> type[RoleLogic]:
        LOGIC[role] = cls()
        return cls
    return wrap


def logic(role: str) -> RoleLogic:
    return LOGIC.get(role, DEFAULT)


def code_hooks(role_logic: RoleLogic) -> list[str]:
    """Which hooks a role's file implements (for --list-roles), plus its ops and win-check flag."""
    hooks = [name for name, attr in vars(RoleLogic).items()
             if callable(attr) and not name.startswith("_") and name != "apply_op"
             and getattr(type(role_logic), name) is not attr]
    hooks += [f"op {op}" for op in role_logic.ops]
    if not role_logic.blocks_win:
        hooks.append("never blocks a win")
    return hooks
