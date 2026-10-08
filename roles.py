"""Role definitions from rules_1.txt and the default setup."""

from dataclasses import dataclass, field
from enum import Enum


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
