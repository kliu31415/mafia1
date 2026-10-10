"""Role power: how much each role moves the Village's chance to win, for setups that balance their draws
(setups.py "standard"). A setup's score is OFFSET plus the sum of its roles' powers; the Village's estimated
chance to win is logistic(score), so 0 means even, and +0.4 is about 60%.

The numbers are hand-set intuition (Oct 10 2026), from notes/role-ratings.md, the role-strength review and the
live games so far: a Good seat is worth about +0.25 to +0.55, a Yakuza seat about -0.85 to -1.1, Outsiders near 0,
Neutral killers clearly negative. Planned: refit them from game results (stats.py data) as games accumulate."""

import math

OFFSET = -0.3  # hidden flips and secret votes favor the Yakuza (Oct 10 games); refit with the powers

POWER: dict[str, float] = {
    # Village
    "Vanilla Villager": 0.25, "Sheriff": 0.55, "Tracker": 0.45, "Lookout": 0.45, "Seer": 0.4,
    "Fortune Teller": 0.35, "Oracle": 0.45, "Eavesdropper": 0.4, "Archivist": 0.4, "Surveyor": 0.4,
    "Census Taker": 0.45, "Profiler": 0.45, "Coroner": 0.35, "Chronicler": 0.4, "Auditor": 0.4,
    "Cartographer": 0.35, "Scout": 0.3, "Insomniac": 0.35, "Accountant": 0.35,
    "Medic": 0.55, "Trapper": 0.55, "Vigilante": 0.45, "Veteran": 0.5,
    "Prosecutor": 0.4, "Philanthropist": 0.35, "Party Animal": 0.45,
    "Roleplayer": 0.0, "Ex-Con": 0.05, "Cardinal": 0.1,
    # Yakuza
    "Grunt": -0.85, "Pharmacist": -1.1, "Ritualist": -1.0, "Puppeteer": -1.0, "Fabricator": -1.0, "Clerk": -0.95,
    "Smuggler": -0.9, "Ballot Stuffer": -0.95, "Fixer": -0.95, "Diviner": -1.05, "Mortician": -0.95,
    "Wiretap": -1.0, "Informant": -0.95,
    # Neutral
    "Vulture": -0.25, "Serial Killer": -0.6, "Arsonist": -0.8, "Jester": -0.15, "Executioner": -0.2,
}


def score(roles: list[str]) -> float:
    return OFFSET + sum(POWER[r] for r in roles)


def village_chance(roles: list[str]) -> float:
    return 1 / (1 + math.exp(-score(roles)))
