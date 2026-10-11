"""Setups: how a game's roles are chosen, and what players are told about it.

A named setup (SETUPS, picked with --roles NAME or NAME:N) draws a different role mix each game from the seed, so
role strength can be estimated across many mixes. Players never see the role list, but a note after the rules
(setup_note) describes how it was drawn: Kevin, Oct 10 2026, so they don't play blind, though without exact
counts. A hand-picked list (--roles A,B,C) is described by rough faction counts instead.

"standard" (the default, balanced by role_power.py) is balanced_setup; "classic" (also "random", the
draw before Oct 10 2026) is described below:

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

import json
import math
import random
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from roles import ROLES, Alignment
from scripts import roles_of

YAKUZA_SHARE = 0.3
MIN_PLAYERS = 5
EXCLUDED: set[str] = set()
POOLS = ("all", "tested")  # --role-pool: every role, or only roles seen working in a live game


@dataclass(frozen=True)
class Setup:
    draw: Callable[..., list[str]]  # (players, rng, pool, script=..., **options) -> role names
    players: tuple[int, int]  # the player count range when --roles gives none (drawn from the seed)
    describe: str  # what players are told about it, after "This game's roles were drawn by the ... setup:"


def parse_setup(text: str) -> tuple[str, int | None] | None:
    """(setup name, player count or None) from "NAME" or "NAME:N"; None if text isn't a named setup (a role list).
    "random" is the classic setup (it was the random setup before "standard" existed)."""
    name, colon, n = text.partition(":")
    name = "classic" if name == "random" else name
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


def allowed_roles(pool: str, script: str) -> list[str]:
    """The roles a setup may draw: on the script (scripts.py), not EXCLUDED, and live-tested if pool is "tested"."""
    return [r for r in roles_of(script) if (pool == "all" or ROLES[r].tested) and r not in EXCLUDED]


def random_setup(n: int, rng: random.Random, pool: str = "all", script: str = "all") -> list[str]:
    """n role names, drawn as the module docstring describes. pool: "all" or "tested"."""
    allowed = allowed_roles(pool, script)

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


YAKUZA_ODDS = {-1: 20, 0: 65, 1: 15}  # standard: Yakuza count around round(3/13 of the seats)
NEUTRAL_ODDS = {0: 15, 1: 35, 2: 35, 3: 15}
MAX_OUTSIDERS = 2  # standard
MAX_VANILLA = 2  # standard: Kevin, Oct 10 2026: many Vanilla Villagers make a game less strategic
MIN_VILLAGE = 5  # standard: non-Outsider Village roles, at least one Investigative
BAND = 0.4  # standard: a setup counts as balanced when |role_power.score| <= BAND (Village win chance 40-60%)
CANDIDATES = 60  # standard: Neutral and Village picks tried per setup
LOG_DIR = Path(__file__).parent / "logs"  # past games, for role_uses


def role_uses(log_dir: Path = LOG_DIR) -> Counter:
    """Role -> how many live games in log_dir it was in (read from each log's first line, the setup record)."""
    uses: Counter = Counter()
    for path in sorted(log_dir.glob("game_*.jsonl")):
        try:
            with path.open(encoding="utf-8") as f:
                setup = json.loads(f.readline())
        except (OSError, ValueError):
            continue
        uses.update({p.get("role") for p in setup.get("players") or []} - {None})
    return uses


def balanced_setup(n: int, rng: random.Random, pool: str = "all", yakuza: int | None = None,
                   script: str = "all") -> list[str]:
    """The standard setup (Kevin, Oct 10 2026; designed for 13 players): usually 3 Yakuza, sometimes 2 or 4
    (about 3/13 of the seats, scaled), 0-3 Neutrals (mostly 1-2), at least MIN_VILLAGE non-Outsider Village
    roles, the rest Good. With fewer Yakuza than usual their roles lean strong, with more they lean weak. Then
    CANDIDATES random picks of the Neutral and Village roles are tried, and a random one within BAND of a
    role_power.score of 0 is kept (with one Neutral fewer only if none is; else the closest): e.g. weaker
    Village roles and more Outsiders against weak Yakuza. Every draw leans towards newer roles (not live-tested
    yet) and roles in fewer past games (logs/), so a seed's setup can change as games are added."""
    import role_power
    offset, power = role_power.load()

    def score(roles: list[str]) -> float:
        return offset + sum(power[r] for r in roles)

    allowed = allowed_roles(pool, script)
    uses = role_uses()

    def novelty(r: str) -> float:  # Kevin, Oct 10 2026: lean towards newer and less used roles
        return (1.0 if ROLES[r].tested else 2.0) / math.sqrt(1 + uses[r] / 3)

    def of(alignment: Alignment, *categories: str) -> list[str]:
        return [r for r in allowed if ROLES[r].alignment is alignment
                and (not categories or ROLES[r].category in categories)]

    def weighted_order(roles: list[str], weight=lambda r: 1.0) -> list[str]:
        """roles in a random order where heavier ones tend to come first (weighted sampling without replacement)."""
        return sorted(roles, key=lambda r: -rng.random() ** (1 / (weight(r) * novelty(r))))

    usual = max(1, round(n * 3 / 13))
    shift = rng.choices(list(YAKUZA_ODDS), list(YAKUZA_ODDS.values()))[0]
    n_yakuza = yakuza if yakuza is not None else max(1, usual + shift)
    lean = 0 if n_yakuza == usual else 3 if n_yakuza < usual else -3  # fewer Yakuza: stronger roles
    evil = weighted_order(of(Alignment.EVIL), lambda r: math.exp(lean * (-power[r] - 0.95)))[:n_yakuza]
    # The Village must outnumber the Yakuza (rules R2) and get its MIN_VILLAGE seats.
    room = n - len(evil) - max(MIN_VILLAGE, len(evil) + 1)

    wanted = max(0, min(rng.choices(list(NEUTRAL_ODDS), list(NEUTRAL_ODDS.values()))[0], room))

    def candidate(n_neutrals: int) -> list[str]:
        neutrals = weighted_order(of(Alignment.NEUTRAL))[:n_neutrals]
        slots = n - len(evil) - len(neutrals)
        village = weighted_order(of(Alignment.GOOD, "Investigative"))[:1]
        rest = weighted_order([r for r in of(Alignment.GOOD, "Investigative", "Combat", "Misc") if r not in village])
        outsiders = weighted_order(of(Alignment.GOOD, "Outsider"))[:MAX_OUTSIDERS]
        while len(village) < slots:
            roll = rng.random()
            vanilla = village.count("Vanilla Villager") < MAX_VANILLA
            if len(village) >= MIN_VILLAGE and outsiders and roll < 0.2:
                village.append(outsiders.pop(0))
            elif (roll < 0.35 and vanilla) or not rest:
                village.append("Vanilla Villager")
            else:
                village.append(rest.pop(0))
        return village + evil + neutrals

    tried: list[tuple[float, list[str]]] = []
    for n_neutrals in range(wanted, -1, -1):  # one Neutral fewer only when no pick is balanced enough
        scored = [(abs(score(c)), c) for c in (candidate(n_neutrals) for _ in range(CANDIDATES))]
        good = [c for s, c in scored if s <= BAND]
        if good:
            return rng.choice(good)
        tried += scored
    return min(tried, key=lambda x: x[0])[1]


SETUPS = {
    "standard": Setup(balanced_setup, (13, 13),
                      "usually 3 Yakuza for 13 players (about 3 in 13 seats; sometimes one fewer, occasionally one "
                      "more), each with a different Yakuza role; 0 to 3 Neutrals, usually 1 or 2, each a different "
                      "Neutral role; the rest are Good: at least 5 Village roles that aren't Outsiders (at least one "
                      "of them Investigative), plus any mix of Village roles, up to 2 Vanilla Villagers and up to "
                      "2 Outsiders. Every "
                      "role but the Vanilla Villager appears at most once (this setup never repeats one, though R2 "
                      "allows it). The roles are picked so that the sides "
                      "are roughly balanced by strength: e.g. fewer Yakuza tend to get stronger roles, and newer "
                      "roles come up more often."),
    "classic": Setup(random_setup, (11, 15),
                     "about 30% of the players are Yakuza (rounded, at least 1), each with a different Yakuza "
                     "role; 0 to 2 are Neutral (at most 1 below 9 players), each a different Neutral role; the rest "
                     "are Village, with at least one Investigative role, at most one Outsider, up to a third Vanilla "
                     "Villagers, and every other Village role at most once."),
}
