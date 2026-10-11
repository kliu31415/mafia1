"""Talent Agent: a Yakuza who spends a token (at most one a night) to learn a random non-Yakuza role in play and one
not in play, or how many players have a named role. "In play" means players alive when the night began."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RoleLogic, acted_tonight, register, spend_token, token_user_error

if TYPE_CHECKING:
    from state import Game

ROLE = "Talent Agent"
TOKEN = "talent"
USED = "talent_agent_used"  # game.role_state: {day: [Talent Agents who spent a token that night]}


def in_play(game: Game) -> list[str]:
    """True roles of the players alive when the night began (rules, Talent Agent: an exact-role check, R19)."""
    return [p.role for p in game.players if acted_tonight(game, p)]


def non_yakuza(roles) -> list[str]:
    from roles import ROLES, Alignment
    return sorted({r for r in roles if ROLES[r].alignment is not Alignment.EVIL})


def scan_text(game: Game) -> str:
    from scripts import script_roles
    playing = in_play(game)
    yes, no = non_yakuza(playing), [r for r in non_yakuza(script_roles(game)) if r not in playing]
    parts = [f"{game.rng.choice(yes)} is in play" if yes else "no non-Yakuza role is in play",
             f"{game.rng.choice(no)} is not in play" if no else "every non-Yakuza role is in play"]
    return f"Your scan: {parts[0]}, and {parts[1]}."


def count_text(game: Game, role: str) -> str:
    n = in_play(game).count(role)
    return f"Your count: {n} living player{'' if n == 1 else 's'} {'has' if n == 1 else 'have'} the role {role}."


@register(ROLE)
class TalentAgent(RoleLogic):
    roleplayer_can_fake = False  # code reads the true roles
    code_tells_user = True
    ops = {"scout_talent": ({"by"}, {"role"},
                            "{op:'scout_talent', role?, by}: the Talent Agent `by` spends a token to scan (no role: "
                            "code tells them a random non-Yakuza role in play and one not in play) or to count `role` "
                            "(code tells them how many living players have it)")}
    night_note = ("A Talent Agent who spent a token (and wasn't role-blocked): use the scout_talent op, with role "
                  "set to the role they named (guessed_role) to count it, or without role to scan; it spends the "
                  "token, and at most one a night. Code tells them the result: don't tell() the Talent Agent "
                  "anything about it. It targets no player, so it visits no one.")

    def check_op(self, game: Game, change: dict) -> str | None:
        from scripts import script_roles
        by = change["by"]
        if error := token_user_error(game, by, ROLE, TOKEN):
            return error
        if by in game.role_state.get(USED, {}).get(game.day, []):
            return "a Talent Agent can spend only one token a night"
        if "role" in change and change["role"] not in script_roles(game):
            return f"{change['role']!r} isn't a role in this game's rules"
        return None

    def apply_op(self, game: Game, change: dict) -> None:
        by = change["by"]
        spend_token(game, by, TOKEN)
        game.role_state.setdefault(USED, {}).setdefault(game.day, []).append(by)
        game.tell([by], count_text(game, change["role"]) if "role" in change else scan_text(game))
