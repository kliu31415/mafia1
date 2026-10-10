"""Setups: how a game's roles are chosen, and what players are told about it.

A named setup (SETUPS, picked with --roles NAME or NAME:N) draws a different role mix each game from the seed, so
role strength can be estimated across many mixes. Players never see the role list, but a note after the rules
(setup_note) describes how it was drawn: Kevin, Oct 10 2026, so they don't play blind, though without exact
counts. A hand-picked list (--roles A,B,C) is described by rough faction counts instead.

"standard" (the default; also "random") is described below:

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
from collections.abc import Callable
from dataclasses import dataclass

from roles import ROLES, Alignment

YAKUZA_SHARE = 0.3
MIN_PLAYERS = 5
EXCLUDED: set[str] = set()
POOLS = ("all", "tested")  # --role-pool: every role, or only roles seen working in a live game


@dataclass(frozen=True)
class Setup:
    draw: Callable[[int, random.Random, str], list[str]]  # (players, rng, pool) -> role names
    players: tuple[int, int]  # the player count range when --roles gives none (drawn from the seed)
    describe: str  # what players are told about it, after "This game's roles were drawn by the ... setup:"


def parse_setup(text: str) -> tuple[str, int | None] | None:
    """(setup name, player count or None) from "NAME" or "NAME:N"; None if text isn't a named setup (a role list).
    "random" is the standard setup."""
    name, colon, n = text.partition(":")
    name = "standard" if name == "random" else name
    if name not in SETUPS:
        return None
    if colon and (not n.isdigit() or int(n) < MIN_PLAYERS):
        raise ValueError(f"use --roles {name}:N with N >= {MIN_PLAYERS} players, e.g. {name}:12")
    return name, int(n) if colon else None


def players_for(name: str, n: int | None, seed: int) -> int:
    """The player count: n, or one drawn from the setup's range for this seed."""
    lo, hi = SETUPS[name].players
    return n if n is not None else random.Random(f"players|{seed}").randint(lo, hi)


def setup_note(setup: dict | None, roles: list[str]) -> str:
    """The text added after the rules (after any rule settings) telling players how this game's roles were
    chosen. setup: the log's settings.setup ({"kind": "random", "name": ...} or None for a hand-picked list)."""
    n = len(roles)
    if setup and setup.get("kind") == "random":
        name = setup.get("name", "standard")
        text = (f"This game has {n} players. Its roles were drawn at random by the {name} setup: "
                f"{SETUPS[name].describe}")
    else:
        count = {a: sum(ROLES[r].alignment is a for r in roles) for a in Alignment}
        yakuza, neutral = count[Alignment.EVIL], count[Alignment.NEUTRAL]
        text = (f"This game has {n} players. Its roles were picked by hand, not drawn by a standard setup. Roughly: "
                f"{max(1, yakuza - 1)} to {yakuza + 1} Yakuza, 0 to {neutral + 1} Neutrals, and the rest Village. "
                "Any role in the rules may be in it, and roles may repeat.")
    return f"\n\n---\n\nSetup (the role list itself is secret).\n{text}"


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


SETUPS = {
    "standard": Setup(random_setup, (11, 15),
                      "about 30% of the players are Yakuza (rounded, at least 1), each with a different Yakuza "
                      "role; 0 to 2 are Neutral (at most 1 below 9 players), each a different Neutral role; the rest "
                      "are Village, with at least one Investigative role, at most one Outsider, up to a third Vanilla "
                      "Villagers, and every other Village role at most once."),
}
