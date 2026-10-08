"""Role definitions from rules_1.txt and the default setup.

Each role with effects that code carries out has its own file here (e.g. roles/executioner.py),
implementing the hooks in roles/base.py. Import it at the bottom of this file to register it.
"""

from dataclasses import dataclass, field
from enum import Enum

from roles.base import RoleLogic, Status, logic, register  # noqa: F401  (re-exported)


class Alignment(str, Enum):
    GOOD = "Good"  # the Village faction
    EVIL = "Evil"  # the Yakuza faction
    NEUTRAL = "Neutral"  # each Neutral player is their own faction


@dataclass(frozen=True)
class RoleInfo:
    alignment: Alignment
    category: str
    sheriff_evil: bool  # how the role appears to a Sheriff, before Katana/Fabricator effects
    defense: str = "None"
    tokens: dict[str, int] = field(default_factory=dict)
    acts_at_night: bool = False


ROLES: dict[str, RoleInfo] = {
    # Village
    "Vanilla Villager": RoleInfo(Alignment.GOOD, "Townsfolk", False),
    "Sheriff": RoleInfo(Alignment.GOOD, "Investigative", False, acts_at_night=True),
    "Tracker": RoleInfo(Alignment.GOOD, "Investigative", False, acts_at_night=True),
    "Lookout": RoleInfo(Alignment.GOOD, "Investigative", False, acts_at_night=True),
    "Seer": RoleInfo(Alignment.GOOD, "Investigative", False, tokens={"seer": 1}, acts_at_night=True),
    "Fortune Teller": RoleInfo(Alignment.GOOD, "Investigative", False),
    "Oracle": RoleInfo(Alignment.GOOD, "Investigative", False, acts_at_night=True),
    "Medic": RoleInfo(Alignment.GOOD, "Combat", False, tokens={"medic": 2}, acts_at_night=True),
    "Trapper": RoleInfo(Alignment.GOOD, "Combat", False, acts_at_night=True),
    "Vigilante": RoleInfo(Alignment.GOOD, "Combat", False, tokens={"vigilante": 3}, acts_at_night=True),
    "Prosecutor": RoleInfo(Alignment.GOOD, "Misc", False, tokens={"prosecutor": 2}, acts_at_night=True),
    "Party Animal": RoleInfo(Alignment.GOOD, "Misc", False, acts_at_night=True),
    "Roleplayer": RoleInfo(Alignment.GOOD, "Outsider", False, acts_at_night=True),
    "Ex-Con": RoleInfo(Alignment.GOOD, "Outsider", True),
    "Cardinal": RoleInfo(Alignment.GOOD, "Outsider", False),
    # Yakuza
    "Grunt": RoleInfo(Alignment.EVIL, "Yakuza", True),
    "Pharmacist": RoleInfo(Alignment.EVIL, "Yakuza", True, acts_at_night=True),
    "Ritualist": RoleInfo(Alignment.EVIL, "Yakuza", True, tokens={"ritual": 2}, acts_at_night=True),
    "Puppeteer": RoleInfo(Alignment.EVIL, "Yakuza", True, tokens={"puppet": 1}, acts_at_night=True),
    "Fabricator": RoleInfo(Alignment.EVIL, "Yakuza", True, tokens={"fabricator": 1}, acts_at_night=True),
    "Clerk": RoleInfo(Alignment.EVIL, "Yakuza", True, tokens={"clerk": 1}, acts_at_night=True),
    "Diviner": RoleInfo(Alignment.EVIL, "Yakuza", True, acts_at_night=True),
    "Mortician": RoleInfo(Alignment.EVIL, "Yakuza", True, tokens={"mortician": 2}, acts_at_night=True),
    # Neutral
    "Serial Killer": RoleInfo(Alignment.NEUTRAL, "Neutral", False, defense="Standard", acts_at_night=True),
    "Arsonist": RoleInfo(Alignment.NEUTRAL, "Neutral", False, defense="Standard", acts_at_night=True),
    "Jester": RoleInfo(Alignment.NEUTRAL, "Neutral", True, defense="Basic"),
    "Executioner": RoleInfo(Alignment.NEUTRAL, "Neutral", True, defense="Basic"),
}

# Neutrals that never block a win (rules: "if we ignore Jesters and Executioners...").
NON_BLOCKING_ROLES = {"Jester", "Executioner"}

DEFAULT_SETUP = [
    "Sheriff", "Medic", "Lookout", "Vigilante", "Vanilla Villager", "Vanilla Villager",
    "Grunt", "Pharmacist", "Fabricator",
    "Jester",
]


# Implementation status of every role. Keep this up to date when a role's handling changes, so
# nobody has to re-audit the code. `uv run mafia.py --list-roles` prints it.
#   handled_by: "code"       - its effects are implemented in code
#               "moderator"  - the LLM moderator resolves its night action from the rules
#               "passive"    - moderator-resolved, but it has effects with no submitted action, so the
#                              moderator's night prompt lists it explicitly
#               "none"       - no ability to implement
#   live_tested: seen working in at least one live (API) game
ROLE_STATUS: dict[str, tuple[str, bool, str]] = {
    # role: (handled_by, live_tested, notes)
    "Vanilla Villager": ("none", True, ""),
    "Sheriff": ("moderator", True, "Katana holder and framed players handled by the moderator"),
    "Tracker": ("moderator", True, ""),
    "Lookout": ("moderator", True, ""),
    "Seer": ("passive", True, "random pair each night unless a token is spent"),
    "Fortune Teller": ("passive", True, "numbers told at the end of the night"),
    "Oracle": ("moderator", False, ""),
    "Medic": ("moderator", True, "tokens tracked via set_tokens"),
    "Trapper": ("passive", False, "persistent traps tracked as player status"),
    "Vigilante": ("moderator", True, ""),
    "Prosecutor": ("code", True, "moderator records the prosecution; code runs the trial next day"),
    "Party Animal": ("moderator", False, ""),
    "Roleplayer": ("passive", False, "code assigns the fake role; moderator invents its results"),
    "Ex-Con": ("passive", False, "random visit each night"),
    "Cardinal": ("code", False, "curse resolved by code at the next dawn"),
    "Grunt": ("none", True, ""),
    "Pharmacist": ("moderator", True, ""),
    "Ritualist": ("moderator", False, "failed guesses must be announced publicly at dawn"),
    "Puppeteer": ("code", True, "moderator records the puppet; code swaps who chats next day"),
    "Fabricator": ("moderator", True, "forged wills via set_last_will"),
    "Clerk": ("code", False, "moderator records the rig; code executes regardless of the vote"),
    "Diviner": ("moderator", False, ""),
    "Mortician": ("moderator", True, "clean via status 'cleaned'; code hides the reveal"),
    "Serial Killer": ("moderator", False, ""),
    "Arsonist": ("passive", False, "douses tracked as player status"),
    "Jester": ("code", True, "hanging win and revenge in code"),
    "Executioner": ("code", True, "target, win, leaving and turning into a Jester in code"),
}
assert ROLE_STATUS.keys() == ROLES.keys(), "every role needs a ROLE_STATUS entry"


def role_status_table() -> str:
    rows = [f"{'Role':<17} {'Handled by':<10} {'Live-tested':<11} Notes"]
    for role, (by, tested, notes) in ROLE_STATUS.items():
        rows.append(f"{role:<17} {by:<10} {'yes' if tested else 'no':<11} {notes}")
    return "\n".join(rows)


# Role files register their hooks when imported.
from roles import executioner, roleplayer  # noqa: E402, F401
