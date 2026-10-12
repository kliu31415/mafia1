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

from roles import ROLES, Alignment, logic
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
    off: tuple[str, ...] = ()  # roles it never draws; players are told, and fakes and decoys leave them out


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
        if off := SETUPS[name].off:
            text += (f" This setup never uses these roles, so nobody has them: {', '.join(off)}. Results that name "
                     "a role (including fakes) never name them either.")
    else:
        count = {a: sum(ROLES[r].alignment is a for r in roles) for a in Alignment}
        yakuza, neutral = count[Alignment.EVIL], count[Alignment.NEUTRAL]
        text = (f"This game has {n} players. Its roles were picked by hand, not drawn by a standard setup. Roughly: "
                f"{max(1, yakuza - 1)} to {yakuza + 1} Yakuza, 0 to {neutral + 1} Neutrals, and the rest Village. "
                "Any role in the rules may be in it, and roles may repeat.")
    if setup and setup.get("kind") == "random" and not setup.get("traits_given"):  # not chosen with --traits
        text += (f" Separately, about {TRAIT_SHARE:.0%} of the players (give or take {max(TRAIT_SPREAD)}) get a "
                 "trait (R24), never more than one each, drawn to help balance the sides; some traits can go only "
                 "to Village players.")
    else:
        text += " Players may also have a trait (R24)."
    return f"\n\n---\n\nSetup (the role list itself is secret).\n{text}"


def allowed_roles(pool: str, script: str) -> list[str]:
    """The roles a setup may draw: on the script (scripts.py), not EXCLUDED, and live-tested if pool is "tested"."""
    return [r for r in roles_of(script) if (pool == "all" or ROLES[r].tested) and r not in EXCLUDED]


def fits(roles: list[str]) -> bool:
    """Whether every role in a random setup accepts the others (RoleLogic.fits_setup, e.g. the Magpie's)."""
    return all(logic(r).fits_setup(roles) for r in set(roles))


def random_setup(n: int, rng: random.Random, pool: str = "all", script: str = "all") -> list[str]:
    """n role names, drawn as the module docstring describes, redrawn while a role doesn't fit (fits)."""
    for _ in range(100):
        if fits(roles := classic_draw(n, rng, pool, script)):
            break
    return roles


def classic_draw(n: int, rng: random.Random, pool: str, script: str) -> list[str]:
    """One draw for random_setup. pool: "all" or "tested"."""
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
    rest = [r for r in of(Alignment.GOOD, *POWER_CATEGORIES) if r not in village]
    rng.shuffle(rest)
    while len(village) < village_slots:
        village.append(rest.pop() if rest else "Vanilla Villager")
    return village[:village_slots] + yakuza + neutrals


YAKUZA_ODDS = {-1: 20, 0: 65, 1: 15}  # standard: Yakuza count around round(3/13 of the seats)
NEUTRAL_ODDS = {0: 15, 1: 35, 2: 35, 3: 15}
MAX_OUTSIDERS = 2  # standard
VILLAGE_NEEDS = {"Investigative": 2, "Killing": 1, "Protective": 1}  # standard: Kevin, Oct 12 2026
POWER_CATEGORIES = ("Investigative", "Killing", "Protective", "Support")  # Village roles with a power
STANDARD_OFF = ("Vanilla Villager", "Grunt")  # Kevin, Oct 12 2026: no ability of their own
MIN_VILLAGE = 5  # standard: non-Outsider Village roles, VILLAGE_NEEDS among them
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
    """The standard setup (Kevin, Oct 10 2026; designed for 13 players): usually 3 Yakuza, sometimes 2 or 4 (about
    3/13 of the seats, scaled), 0-3 Neutrals (mostly 1-2), at least MIN_VILLAGE non-Outsider Village roles
    (VILLAGE_NEEDS among them: Kevin, Oct 12 2026), the rest Good. With fewer Yakuza than usual their roles lean
    strong, with more they lean weak. Then CANDIDATES random picks of the Neutral and Village roles are tried, and a
    random one within BAND of a role_power.score of 0 is kept (with one Neutral fewer only if none is; else the
    closest): e.g. weaker Village roles and more Outsiders against weak Yakuza. Every draw leans towards newer roles
    (not live-tested yet) and roles in fewer past games (logs/), so a seed's setup can change as games are added."""
    import role_power
    offset, power = role_power.load()

    def score(roles: list[str]) -> float:
        return offset + sum(power[r] for r in roles)

    allowed = [r for r in allowed_roles(pool, script) if r not in STANDARD_OFF]
    uses = role_uses()

    def novelty(r: str) -> float:  # Kevin, Oct 10 2026: lean towards newer and less used roles
        return (1.0 if ROLES[r].tested else 2.0) / math.sqrt(1 + uses[r] / 3)

    def of(alignment: Alignment, *categories: str) -> list[str]:
        return [r for r in allowed if ROLES[r].alignment is alignment
                and (not categories or ROLES[r].category in categories)]

    def draw(roles: list[str], k: int, weight=lambda r: 1.0, taken: tuple[str, ...] = ()) -> list[str]:
        """k roles drawn with replacement, heavier ones more often; a role may repeat (Kevin, Oct 11 2026) unless
        it is unique (rules R2), in which case it never repeats one in `taken` or already drawn."""
        picked: list[str] = []
        for _ in range(k):
            options = [r for r in roles if not (ROLES[r].unique and r in (*taken, *picked))]
            if not options:
                break
            picked += rng.choices(options, [weight(r) * novelty(r) for r in options])
        return picked

    usual = max(1, round(n * 3 / 13))
    shift = rng.choices(list(YAKUZA_ODDS), list(YAKUZA_ODDS.values()))[0]
    n_yakuza = yakuza if yakuza is not None else max(1, usual + shift)
    lean = 0 if n_yakuza == usual else 3 if n_yakuza < usual else -3  # fewer Yakuza: stronger roles
    evil = draw(of(Alignment.EVIL), n_yakuza, lambda r: math.exp(lean * (-power[r] - 0.95)))
    # The Village must outnumber the Yakuza (rules R2) and get its MIN_VILLAGE seats.
    room = n - len(evil) - max(MIN_VILLAGE, len(evil) + 1)

    wanted = max(0, min(rng.choices(list(NEUTRAL_ODDS), list(NEUTRAL_ODDS.values()))[0], room))

    def candidate(n_neutrals: int) -> list[str]:
        neutrals = draw(of(Alignment.NEUTRAL), n_neutrals)
        slots = n - len(evil) - len(neutrals)
        village = [r for category, k in VILLAGE_NEEDS.items() for r in draw(of(Alignment.GOOD, category), k)]
        rest = of(Alignment.GOOD, *POWER_CATEGORIES)
        outsiders = draw(of(Alignment.GOOD, "Outsider"), MAX_OUTSIDERS)
        while len(village) < slots:
            more = draw(rest, 1, taken=tuple(village))
            if len(village) >= MIN_VILLAGE and outsiders and rng.random() < 0.2:
                village.append(outsiders.pop(0))
            elif more:
                village += more
            else:  # a script with too few Village roles
                village.append("Vanilla Villager")
        return village + evil + neutrals

    tried: list[tuple[float, list[str]]] = []
    for n_neutrals in range(wanted, -1, -1):  # one Neutral fewer only when no pick is balanced enough
        picks = (candidate(n_neutrals) for _ in range(CANDIDATES))
        scored = [(abs(score(c)) if fits(c) else math.inf, c) for c in picks]
        good = [c for s, c in scored if s <= BAND]
        if good:
            return rng.choice(good)
        tried += scored
    return min(tried, key=lambda x: x[0])[1]


SETUPS = {
    "standard": Setup(balanced_setup, (13, 13),
                      "usually 3 Yakuza for 13 players (about 3 in 13 seats; sometimes one fewer, occasionally one "
                      "more); 0 to 3 Neutrals, usually 1 or 2; the rest are Good: at least 5 Village roles that "
                      "aren't Outsiders (at least 2 of them Investigative, 1 Killing and 1 Protective), plus any mix "
                      "of Village roles and up to 2 Outsiders. Roles may repeat, except "
                      "unique ones (R2). The roles are picked so that the sides are roughly balanced by strength: e.g. "
                      "fewer Yakuza tend to get stronger roles.", STANDARD_OFF),
    "classic": Setup(random_setup, (11, 15),
                     "about 30% of the players are Yakuza (rounded, at least 1), each with a different Yakuza "
                     "role; 0 to 2 are Neutral (at most 1 below 9 players), each a different Neutral role; the rest "
                     "are Village, with at least one Investigative role, at most one Outsider, up to a third Vanilla "
                     "Villagers, and every other Village role at most once."),
}


# Kevin, Oct 12 2026: about a quarter of the players get a trait, give or take 2 (13 players: usually 3, 1-5).
TRAIT_SHARE = 0.25
TRAIT_SPREAD = {-2: 1, -1: 3, 0: 4, 1: 3, 2: 1}  # odds of each count around TRAIT_SHARE of the players
TRAIT_SAMPLES = 8  # random trait sets tried per count; balance picks among them all


def trait_odds(players: int) -> dict[int, int]:
    """The odds of each trait count before balancing (draw_traits)."""
    mid = round(players * TRAIT_SHARE)
    odds: dict[int, int] = {}
    for d, w in TRAIT_SPREAD.items():
        n = max(0, mid + d)
        odds[n] = odds.get(n, 0) + w
    return odds


def draw_traits(roles: list[str], rng: random.Random) -> list[str]:
    """Traits for a drawn setup (traits.py, rules R24): a count from trait_odds, and for each count TRAIT_SAMPLES random
    trait sets; one set is picked by its count's odds, scaled down the further role_power.score (of the roles and
    the set's traits, with their fitted powers) leaves even (Kevin: traits help balance setups, semi-randomly). Each
    trait is drawn from those its players could get (an eligible seat without a trait yet: a drawn setup gives a
    player at most one). A trait that can go to more
    than one faction is drawn with the faction of the seat it goes to ("Grudge@Yakuza"), so the balance knows
    which side it helps."""
    import role_power
    from traits import FACTIONS, TRAITS
    faction_name = {a: f for f, a in FACTIONS.items()}

    def sample(n: int) -> list[tuple[str, Alignment]]:
        chosen: list[tuple[str, Alignment]] = []
        for _ in range(n):
            # At most one trait a player (Kevin, Oct 12 2026): a trait needs a seat of its alignments with none yet.
            seats = [ROLES[r].alignment for r in roles]
            for _, a in chosen:
                seats.remove(a)
            free = {t: [a for a in seats if a in info.alignments] for t, info in TRAITS.items()}
            options = [t for t, seats in free.items() if seats]
            if not options:
                break
            t = rng.choice(options)
            chosen.append((t, rng.choice(free[t])))  # as if dealt to a random free seat
        return chosen

    sets = [(odds / TRAIT_SAMPLES, sample(n)) for n, odds in trait_odds(len(roles)).items()
            for _ in range(TRAIT_SAMPLES)]
    # Each set's odds, scaled down the further it leaves the setup from even (in units of BAND), so traits lean
    # towards what evens the sides without overriding the odds.
    weight = [odds * math.exp(-(role_power.score(roles, traits=c) / BAND) ** 2) for odds, c in sets]
    chosen = rng.choices([c for _, c in sets], weight)[0]
    return [t if len(TRAITS[t].alignments) == 1 else f"{t}@{faction_name[a]}" for t, a in chosen]

