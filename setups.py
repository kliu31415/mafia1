"""Random setups (--roles random:N): a different role mix each game, so role strength can be
estimated across many mixes instead of only DEFAULT_SETUP.

The rules don't say how setups are built (only that Village outnumbers Yakuza, R2), so these
proportions are a choice of this program, modelled on DEFAULT_SETUP (10 players: 6 Village incl. two
Vanilla Villagers, 3 Yakuza, 1 Neutral):
- Yakuza: about 30% of the seats, at least one. Every Yakuza role at most once.
- Neutral: 0-1 below 9 players, 0-2 from 9 (one is the most likely), fewer if the Village
  would no longer outnumber the Yakuza.
- Village: the rest, with at least one Investigative role, at most one Outsider, and up to a third
  Vanilla Villagers. Every other Village role at most once.
- Roles in EXCLUDED are never drawn.
"""

import random

from roles import ROLES, Alignment

YAKUZA_SHARE = 0.3
MIN_PLAYERS = 5
# The Mortician hides the role and alignment, which the default settings (variants.py) already hide, so there it
# would be a Grunt (Kevin, Oct 10 2026: leave it out of random setups for now).
EXCLUDED = {"Mortician"}
POOLS = ("all", "tested")  # --role-pool: every role, or only roles seen working in a live game


def parse_random_roles(text: str) -> int | None:
    """The player count from "random:N", or None if text isn't a random setup."""
    if not text.startswith("random"):
        return None
    _, _, n = text.partition(":")
    if not n.isdigit() or int(n) < MIN_PLAYERS:
        raise ValueError(f"use --roles random:N with N >= {MIN_PLAYERS} players, e.g. random:8")
    return int(n)


def random_setup(n: int, rng: random.Random, pool: str = "all") -> list[str]:
    """n role names, drawn as the module docstring describes. pool: "all" or "tested"."""
    allowed = [r for r, info in ROLES.items() if (pool == "all" or info.tested) and r not in EXCLUDED]

    def of(alignment: Alignment, *categories: str) -> list[str]:
        return [r for r in allowed if ROLES[r].alignment is alignment
                and (not categories or ROLES[r].category in categories)]

    yakuza_pool = of(Alignment.EVIL)
    yakuza = rng.sample(yakuza_pool, min(len(yakuza_pool), max(1, round(n * YAKUZA_SHARE))))
    neutral_pool = of(Alignment.NEUTRAL)
    wanted = rng.choice([0, 1, 1, 2] if n >= 9 else [0, 1])
    # Village must outnumber the Yakuza (rules R2), which caps the Neutrals in small games.
    neutrals = rng.sample(neutral_pool, max(0, min(len(neutral_pool), wanted, n - 2 * len(yakuza) - 1)))

    village_slots = n - len(yakuza) - len(neutrals)
    village = [rng.choice(of(Alignment.GOOD, "Investigative"))]
    outsiders = of(Alignment.GOOD, "Outsider")
    if outsiders and village_slots > 3 and rng.random() < 0.4:
        village.append(rng.choice(outsiders))
    village += ["Vanilla Villager"] * rng.randint(0, village_slots // 3)
    rest = [r for r in of(Alignment.GOOD, "Investigative", "Combat", "Misc") if r not in village]
    rng.shuffle(rest)
    while len(village) < village_slots:
        village.append(rest.pop() if rest else "Vanilla Villager")
    return village[:village_slots] + yakuza + neutrals
