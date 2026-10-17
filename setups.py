"""Setups: how a game's roles are chosen, and what players are told about it.

A named setup (SETUPS, picked with --roles NAME or NAME:N) draws a different role mix each game from the seed, so
role strength can be estimated across many mixes. Players never see the role list, but a note after the rules
(setup_note) describes how it was drawn: Kevin, Oct 10 2026, so they don't play blind, though without exact
counts. A hand-picked list (--roles A,B,C) is described by rough faction counts instead; like the standard setup
it leaves out Vanilla Villager and Grunt (setup_off) unless the list names them.

"standard" (the default, balanced by role_power.py) is balanced_setup, which may repeat any role that isn't
unique; "classic" (also "random", the draw before Oct 10 2026, without repeats) is described below:

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

from records import setup_record
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


def setup_off(setup: dict | None, roles: list[str]) -> tuple[str, ...]:
    """The roles this game's setup never uses (settings.setup_off): a drawn setup's own (Setup.off), and for a
    hand-picked list the standard setup's unless the list names them (Kevin, Oct 13 2026: Vanilla is too often a
    boring cover claim)."""
    if setup and setup.get("kind") == "random":
        return SETUPS[setup.get("name", "standard")].off
    return tuple(r for r in STANDARD_OFF if r not in roles)


def hand_traits_note(traits: list[str]) -> str:
    """How many traits (R24) hand-picked trait items (--traits) deal, roughly, like a hand-picked role list's Yakuza
    count. A pair trait (Bonded) is held by two players, and a second holder named in the list is the first's partner
    (traits.pair_up)."""
    from traits import TRAITS, parse_item as parse_trait
    if not traits:
        return " Nobody has a trait (R24) in this game."
    names = [t for item in traits for t in parse_trait(item)[0]]
    total = sum(2 * -(-names.count(t) // 2) if t in TRAITS and TRAITS[t].pairs else names.count(t) for t in set(names))
    return (f" Traits (R24) were picked by hand too: roughly {max(1, total - 1)} to {total + 1} in all, each dealt to "
            "a player it fits, and a player may hold more than one.")


def setup_note(setup: dict | None, roles: list[str], off: tuple[str, ...] | None = None,
               traits: list[str] | None = None) -> str:
    """The text added after the rules (after any rule settings) telling players how this game's roles were
    chosen. setup: the log's settings.setup ({"kind": "random", "name": ...} or None for a hand-picked list).
    off: the roles it never uses, when they aren't setup_off's (an older log's own). traits: the settings' traits
    (--traits items), told roughly when picked by hand; None for an older log (only "may have a trait")."""
    n = len(roles)
    off = setup_off(setup, roles) if off is None else off
    if setup and setup.get("kind") == "random":
        name = setup.get("name", "standard")
        text = (f"This game has {n} players. Its roles were drawn at random by the {name} setup: "
                f"{SETUPS[name].describe}")
    else:
        count = {a: sum(ROLES[r].alignment is a for r in roles) for a in Alignment}
        yakuza, neutral = count[Alignment.EVIL], count[Alignment.NEUTRAL]
        text = (f"This game has {n} players. Its roles were picked by hand, not drawn by a standard setup. Roughly: "
                f"{max(1, yakuza - 1)} to {yakuza + 1} Yakuza, 0 to {neutral + 1} Neutrals, and the rest Village. "
                f"Any {'other ' if off else ''}role in the rules may be in it, and roles may repeat.")
    if off:
        text += (f" This setup never uses these roles, so nobody has them: {', '.join(off)}. Results that name "
                 "a role (including fakes) never name them either.")
    if setup and setup.get("kind") == "random" and not setup.get("traits_given"):  # not chosen with --traits
        text += (" Separately, traits (R24) are dealt: each player, independently of everyone else, has 0, 1 or 2 "
                 "traits, a 1/3 chance each (rarely fewer, when no other trait fits them). Which traits are dealt is "
                 "drawn to help balance the sides; some traits can go only to Village players.")
    elif traits is not None:
        text += hand_traits_note(traits)
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


# standard: Yakuza count round(3/13 of the seats) or one more, half the time each, never fewer (Kevin, Oct 17 2026: 3 or
# 4 of 13, never 2, since the Yakuza had been winning too little; it was 20% 2, 65% 3, 15% 4)
YAKUZA_ODDS = {0: 50, 1: 50}
NEUTRAL_ODDS = {0: 10, 1: 20, 2: 40, 3: 20, 4: 10}  # standard (Kevin, Oct 17 2026; was 0-3 at 15-35-35-15)
MAX_OUTSIDERS = 2  # standard
# Kevin, Oct 17 2026: with up to 4 Neutrals, at most 2 Neutral killers (subcategory Killing), so nights don't turn
# into a lottery; the other Neutrals come from Chaos.
MAX_NEUTRAL_KILLERS = 2
VILLAGE_NEEDS = {"Investigative": 2, "Killing": 1, "Protective": 1}  # standard: Kevin, Oct 12 2026
POWER_CATEGORIES = ("Investigative", "Killing", "Protective", "Support")  # Village roles with a power
STANDARD_OFF = ("Vanilla Villager", "Grunt")  # Kevin, Oct 12 2026: no ability of their own
MIN_VILLAGE = 5  # standard: non-Outsider Village roles, VILLAGE_NEEDS among them
BAND = 0.4  # standard: a setup counts as balanced when |role_power.score| <= BAND (Village win chance 40-60%)
CANDIDATES = 60  # standard: Neutral and Village picks tried per setup
LOG_DIR = Path(__file__).parent / "logs"  # past games, for role_uses


def role_uses(log_dir: Path | None = None) -> Counter:
    """Role -> how many live games it was in. By default from the last role-power fit (tips/role_power.json, its
    roles' "games"), which the PC publishes to main and the logs branch, so a seed draws the same setup on the PC and
    in a cloud sandbox with no logs (Kevin, Oct 17 2026: cloud games had passed their drawn roles as a list, so
    players were told the roles were picked by hand). Without that file, or for an explicit log_dir, it counts the
    logs' setup records (LOG_DIR, read when called, so a test can point it elsewhere)."""
    if log_dir is None:
        import role_power
        try:
            fitted = json.loads(role_power.FILE.read_text(encoding="utf-8"))["roles"]
            return Counter({r: v["games"] for r, v in fitted.items() if v.get("games")})
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass
    uses: Counter = Counter()
    for path in sorted((log_dir or LOG_DIR).glob("game_*.jsonl")):
        setup = setup_record(path)
        uses.update({p.get("role") for p in setup.get("players") or []} - {None})
    return uses


def usual_yakuza(n: int) -> int:
    return max(1, round(n * 3 / 13))


def yakuza_odds(n: int) -> dict[int, int]:
    """The standard setup's odds of each Yakuza count for n players (YAKUZA_ODDS around usual_yakuza)."""
    odds: dict[int, int] = {}
    for shift, w in YAKUZA_ODDS.items():
        k = max(1, usual_yakuza(n) + shift)
        odds[k] = odds.get(k, 0) + w
    return odds


def balanced_setup(n: int, rng: random.Random, pool: str = "all", yakuza: int | None = None,
                   script: str = "all", frontier: bool = False) -> list[str]:
    """The standard setup (Kevin, Oct 10 2026; designed for 13 players): 3 or 4 Yakuza, half the time each (about 3/13
    of the seats and one more, scaled; never fewer since Oct 17 2026), 0-4 Neutrals (mostly 1-3), at least
    MIN_VILLAGE non-Outsider Village roles (VILLAGE_NEEDS among them: Kevin, Oct 12 2026), the rest Good. With more
    Yakuza than usual their roles lean weak. Then CANDIDATES random picks of the Yakuza, Neutral and Village roles
    are tried, and a random one within BAND of a role_power.score of 0 is kept (with one Neutral fewer only if none
    is; else the closest): e.g. weaker Village roles and more Outsiders against weak Yakuza. Every draw leans
    towards newer roles (not live-tested yet) and roles in fewer past games (logs/), so a seed's setup can change
    as games are added. frontier: every seat is a frontier model, whose games the fit gives an offset of their own
    (role_power.FRONTIER_PRIOR: the Village won 10 of 11 all-Opus games aimed at even)."""
    import role_power
    offset, power = role_power.load()
    if frontier:
        offset += role_power.load_frontier()

    def score(roles: list[str]) -> float:
        return offset + sum(power[r] for r in roles)

    allowed = [r for r in allowed_roles(pool, script) if r not in STANDARD_OFF]
    uses = role_uses()

    def novelty(r: str) -> float:  # Kevin, Oct 10 2026: lean towards newer and less used roles
        return (1.0 if ROLES[r].tested else 2.0) / math.sqrt(1 + uses[r] / 3)

    def of(alignment: Alignment, *categories: str) -> list[str]:
        return [r for r in allowed if ROLES[r].alignment is alignment
                and (not categories or ROLES[r].category in categories)]

    def chaos_only(r: str) -> float:
        return 0.0 if ROLES[r].subcategory == "Killing" else 1.0

    def draw(roles: list[str], k: int, weight=lambda r: 1.0, taken: tuple[str, ...] = ()) -> list[str]:
        """k roles drawn with replacement, heavier ones more often; a role may repeat (Kevin, Oct 11 2026) unless
        it is unique (rules R2), in which case it never repeats one in `taken` or already drawn."""
        picked: list[str] = []
        for _ in range(k):
            options = [r for r in roles if not (ROLES[r].unique and r in (*taken, *picked)) and weight(r) > 0]
            if not options:
                break
            picked += rng.choices(options, [weight(r) * novelty(r) for r in options])
        return picked

    usual = usual_yakuza(n)
    odds = yakuza_odds(n)
    n_yakuza = yakuza if yakuza is not None else rng.choices(list(odds), list(odds.values()))[0]
    lean = 0 if n_yakuza == usual else 3 if n_yakuza < usual else -3  # fewer Yakuza: stronger roles
    # The Village must outnumber the Yakuza (rules R2) and get its MIN_VILLAGE seats.
    room = n - n_yakuza - max(MIN_VILLAGE, n_yakuza + 1)

    wanted = max(0, min(rng.choices(list(NEUTRAL_ODDS), list(NEUTRAL_ODDS.values()))[0], room))

    def candidate(n_neutrals: int) -> list[str]:
        # The Yakuza roles are redrawn with the rest (Kevin, Oct 12 2026): weak ones drawn once left 18% of setups
        # unbalanced, since no Village mix made up for them.
        evil = draw(of(Alignment.EVIL), n_yakuza, lambda r: math.exp(lean * (-power[r] - 0.95)))
        neutrals = draw(of(Alignment.NEUTRAL), n_neutrals)
        killers = [r for r in neutrals if ROLES[r].subcategory == "Killing"]
        if len(killers) > MAX_NEUTRAL_KILLERS:  # the extra Neutral killers are redrawn as Chaos Neutrals
            kept = killers[:MAX_NEUTRAL_KILLERS] + [r for r in neutrals if ROLES[r].subcategory != "Killing"]
            neutrals = kept + draw(of(Alignment.NEUTRAL), len(neutrals) - len(kept), chaos_only, taken=tuple(kept))
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
                      "3 or 4 Yakuza for 13 players (each about half the time); 0 to 4 Neutrals, usually 2, at most "
                      "2 of them Neutral killers; the rest are Good: at least 5 Village roles that aren't Outsiders "
                      "(at least 2 of them "
                      "Investigative, 1 Killing and 1 Protective), plus any mix of Village roles and up to 2 "
                      "Outsiders. Roles may repeat, except unique ones (R2). The roles are picked so that the sides "
                      "are roughly balanced by strength: e.g. more Yakuza tend to get weaker roles.", STANDARD_OFF),
    "classic": Setup(random_setup, (11, 15),
                     "about 30% of the players are Yakuza (rounded, at least 1), each with a different Yakuza "
                     "role; 0 to 2 are Neutral (at most 1 below 9 players), each a different Neutral role; the rest "
                     "are Village, with at least one Investigative role, at most one Outsider, up to a third Vanilla "
                     "Villagers, and every other Village role at most once."),
}


def seeded_setup(name: str, n: int | None, seed: int, pool: str = "all", script: str = "all",
                 yakuza: int | None = None, frontier: bool = False) -> tuple[list[str], dict]:
    """A named setup's roles as a game with this seed draws them (mafia.py --roles NAME[:N] --seed SEED; the
    handbook's setup builder), and its setup record. Its own RNG, so a seed's setup doesn't depend on the rest of the
    game (and vice versa). frontier: balance for a game of frontier models only (balanced_setup)."""
    n = players_for(name, n, seed)
    options: dict = {"yakuza": yakuza} if yakuza is not None else {}
    if frontier and name == "standard":
        options["frontier"] = True
    roles = SETUPS[name].draw(n, random.Random(f"setup|{seed}"), pool, script=script, **options)
    return roles, {"kind": "random", "name": name, "players": n, "pool": pool, **options}


def seeded_traits(roles: list[str], seed: int, frontier: bool = False) -> list[str]:
    """The traits a drawn setup deals for this seed (draw_traits on its own RNG, like seeded_setup)."""
    return draw_traits(roles, random.Random(f"traits|{seed}"), frontier)


# Kevin, Oct 13 2026: each player independently holds 0, 1 or 2 traits, a 1/3 chance each (TRAIT_COUNT_ODDS; a
# 13-player game averages 13), and players are told so. Balancing picks only which traits, never how many, so the
# odds stay true. Was about one for every two players, give or take 3 (earlier Oct 13), and a quarter (Oct 12).
TRAIT_COUNT_ODDS = {0: 1, 1: 1, 2: 1}  # odds of each player's trait count
TRAITS_EACH = max(TRAIT_COUNT_ODDS)
TRAIT_SAMPLES = 40  # random trait sets tried; balance picks among them
# Traits that fix or skew how a player's trial vote counts, unseen by others (Kevin, Oct 17 2026: at most
# MAX_VOTE_TRAITS a game). game_20261015_080049_1001 had 6, every trial after Day 2 failed, and vote totals, a big part
# of how the town reads Days, became noise.
VOTE_TRAITS = frozenset({"Merciful", "Zealot", "Turncoat", "Remorseful", "Ashamed"})
MAX_VOTE_TRAITS = 2


def draw_traits(roles: list[str], rng: random.Random, frontier: bool = False) -> list[str]:
    """Traits for a drawn setup (traits.py, rules R24): each seat's count from TRAIT_COUNT_ODDS, then TRAIT_SAMPLES
    random sets of which traits fill those counts; one set is picked with odds scaled down the further
    role_power.score (of the roles and the set's traits, with their fitted powers) leaves even (Kevin: traits help
    balance setups, semi-randomly). The counts are drawn once, so balancing never changes them. Each seat, in a
    random order, draws its traits from those it fits (none it excludes, and a unique trait once); a paired trait
    (Bonded) also fills a free place of another seat it fits, so both partners' counts include it. Each player's
    traits come out as one item ("Martyr+Kindred"), dealt to one player. An item with a trait that can go to more
    than one faction names the faction of its seat ("Grudge@Yakuza"), so the balance knows which side it helps.
    A set holds at most MAX_VOTE_TRAITS of VOTE_TRAITS. frontier: balance for a game of frontier models only."""
    import role_power
    from traits import FACTIONS, TRAITS, bundle_error, fits
    faction_name = {a: f for f, a in FACTIONS.items()}
    counts = rng.choices(list(TRAIT_COUNT_ODDS), list(TRAIT_COUNT_ODDS.values()), k=len(roles))

    def sample() -> list[list[str]]:
        held: list[list[str]] = [[] for _ in roles]  # each seat's traits
        order = list(range(len(roles)))
        rng.shuffle(order)

        def free(i: int, t: str) -> bool:
            return len(held[i]) < counts[i] and fits(t, roles[i]) and not bundle_error(held[i] + [t])

        def partners(i: int, t: str) -> list[int]:  # seats a pair trait's partner may take (Rival: same side)
            return [j for j in order if j != i and free(j, t)
                    and (not TRAITS[t].same_faction or ROLES[roles[j]].alignment is ROLES[roles[i]].alignment)]

        for i in order:
            while len(held[i]) < counts[i]:
                votes = sum(t in VOTE_TRAITS for h in held for t in h)
                options = [t for t in TRAITS if free(i, t) and not (TRAITS[t].unique and any(t in h for h in held))
                           and not (TRAITS[t].pairs and not partners(i, t))  # rules R24
                           and not (t in VOTE_TRAITS and votes >= MAX_VOTE_TRAITS)]
                if not options:
                    break  # nothing else fits this seat: it holds fewer (rare)
                held[i].append(t := rng.choice(options))
                if TRAITS[t].pairs:
                    held[rng.choice(partners(i, t))].append(t)
        return held

    def powers(held: list[list[str]]) -> list[tuple[str, Alignment]]:
        return [(t, ROLES[r].alignment) for h, r in zip(held, roles) for t in h]

    sets = [sample() for _ in range(TRAIT_SAMPLES)]
    # Each set's odds, scaled down the further it leaves the setup from even (in units of BAND), so traits lean
    # towards what evens the sides.
    off = [(role_power.score(roles, traits=powers(c), frontier=frontier) / BAND) ** 2 for c in sets]
    weight = [math.exp(min(off) - o) for o in off]  # relative to the most even, so they never all round to 0
    chosen = rng.choices(sets, weight)[0]
    return ["+".join(h) + (f"@{faction_name[ROLES[r].alignment]}" if any(len(TRAITS[t].alignments) > 1 for t in h)
                           else "")
            for h, r in zip(chosen, roles) if h]

