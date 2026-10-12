"""Role power: how much each role moves the Village's chance to win, for setups that balance their draws
(setups.py "standard"). A setup's score is the offset plus the sum of its roles' powers, plus its traits' powers
(traits.py, counted for the holder's side: + for a Village holder, - for a Yakuza, 0 for a Neutral; village_power);
the Village's estimated chance to win is logistic(score), so 0 means even, and +0.4 is about 60%.

A living document (Kevin, Oct 10 2026): PRIOR holds hand-set intuition (from notes/role-ratings.md, the role
strength review and the live games so far: a Good seat about +0.25 to +0.55, a Yakuza seat about -0.85 to -1.1,
Outsiders near 0, Neutral killers clearly negative), and each trait's TraitInfo.power (and power_for) its prior.
`fit` refits every power from finished live games: a logistic regression of "the Village won" on the setup's roles
and dealt traits (each trait a term signed by its holder's alignment; read from the log's seats, and a pre-v51
Cardinal counts as a Vanilla Villager with the Cursed trait), pulled towards the priors (each prior counts like a
few games, so a role or trait seen in few games stays near its prior). The result goes in tips/role_power.json,
which setups read (a file without "traits", from before traits were fitted, leaves them at their hand-set power),
and tips/role_power.md, a readable table. They're rebuilt where the tips are (a PC game's end, `sync_logs.py
pull`), so the existing tips commit and publish carry them to main and to cloud games. Edit PRIOR or TRAITS to
change the intuition; `uv run role_power.py` refits by hand.
"""

import argparse
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import variants
from roles import Alignment
from traits import FACTIONS, TRAITS, hand_powers, power_key, village_power, village_sign

ROOT = Path(__file__).parent
FILE = ROOT / "tips" / "role_power.json"
OFFSET_PRIOR = -0.3  # hidden flips and secret votes favor the Yakuza (Oct 10 games)
PRIOR_SD = 0.3  # how far data may move a power: the prior's weight (smaller = stickier)
OFFSET_SD = 0.5
OTHER_SETTINGS_WEIGHT = 0.5  # games played under other rule settings than today's defaults count half

PRIOR: dict[str, float] = {
    # Village
    "Vanilla Villager": 0.25, "Sheriff": 0.55, "Tracker": 0.45, "Lookout": 0.45, "Seer": 0.4,
    "Fortune Teller": 0.35, "Oracle": 0.45, "Eavesdropper": 0.4, "Archivist": 0.4, "Surveyor": 0.4,
    "Census Taker": 0.45, "Profiler": 0.45, "Coroner": 0.35, "Chronicler": 0.4, "Auditor": 0.4, "Juror": 0.35,
    "Scrutineer": 0.3, "Bloodhound": 0.4, "Cartographer": 0.35, "Scout": 0.3, "Insomniac": 0.35, "Accountant": 0.35,
    "Medic": 0.55, "Trapper": 0.7, "Kitsune": 0.6, "Vigilante": 0.45, "Enforcer": 0.45, "Veteran": 0.5, "Sniper": 0.45,
    "Prosecutor": 0.4, "Philanthropist": 0.35, "Party Animal": 0.45,
    "Roleplayer": 0.0, "Ex-Con": 0.05,
    # Yakuza
    "Grunt": -0.85, "Pharmacist": -1.1, "Ritualist": -1.0, "Puppeteer": -1.0, "Fabricator": -1.0, "Clerk": -0.95,
    "Smuggler": -0.9, "Ballot Stuffer": -0.95, "Fixer": -0.95, "Diviner": -1.05, "Mortician": -0.95,
    "Wiretap": -1.0, "Informant": -0.95, "Talent Agent": -0.95,
    # Neutral
    "Vulture": -0.25, "Serial Killer": -0.6, "Arsonist": -0.8, "Jester": -0.15, "Executioner": -0.2,
    "Bounty Hunter": -0.3, "Magpie": -0.15,
}


TRAIT_PRIOR = hand_powers()  # power_key -> hand-set power: each trait's prior


@dataclass(frozen=True)
class Played:
    """One finished game, as fit uses it."""
    roles: list[str]  # the start roles
    won: int  # 1 if the Village won, else 0
    weight: float = 1.0
    traits: tuple[tuple[str, Alignment], ...] = ()  # (trait, holder's alignment) for each dealt trait


def load(path: Path | None = None) -> tuple[float, dict[str, float]]:
    """(offset, power per role): the last fit (FILE), with PRIOR for roles it lacks; PRIOR alone without a fit."""
    try:
        data = json.loads((path or FILE).read_text(encoding="utf-8"))
        fitted = {r: v["power"] for r, v in data["roles"].items()}
        return data["offset"], {r: fitted.get(r, p) for r, p in PRIOR.items()}
    except (OSError, ValueError, KeyError):
        return OFFSET_PRIOR, dict(PRIOR)


def load_traits(path: Path | None = None) -> dict[str, float]:
    """Power per trait key (traits.power_key): the last fit (FILE), with the hand-set power (TRAIT_PRIOR) for keys it
    lacks, e.g. every key with a file written before traits were fitted."""
    try:
        data = json.loads((path or FILE).read_text(encoding="utf-8"))
        fitted = {k: v["power"] for k, v in (data.get("traits") or {}).items()}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        fitted = {}
    return {k: fitted.get(k, p) for k, p in TRAIT_PRIOR.items()}


def score(roles: list[str], path: Path | None = None, traits: Iterable[tuple[str, Alignment]] = ()) -> float:
    """The setup's score: the offset, its roles' powers and its traits' (trait, holder's alignment) powers for the
    Village (traits.village_power)."""
    offset, power = load(path)
    traits = list(traits)
    trait_power = load_traits(path) if traits else {}
    return offset + sum(power[r] for r in roles) + sum(village_power(t, a, trait_power) for t, a in traits)


def village_chance(roles: list[str], path: Path | None = None, traits: Iterable[tuple[str, Alignment]] = ()) -> float:
    return 1 / (1 + math.exp(-score(roles, path, traits)))


def games(log_dir: Path) -> list[Played]:
    """Each finished live game in log_dir that has a winning faction (games stopped by the stall rule or the day limit
    are left out), and that has only roles and traits this code knows."""
    import stats  # here: it imports the game index, which setups (which imports this) doesn't need
    from roles import RETIRED_BY_LABEL
    out = []
    for path in sorted(log_dir.glob("game_*.jsonl")):
        g = stats.load_game(path)
        if not g or g["mock"] or g["winning_faction"] is None:
            continue
        roles: list[str] = []
        dealt: list[tuple[str, Alignment]] = []
        for p in g["players"]:
            # A retired role counts as the role it became, with the traits it became (the Cardinal: a Vanilla
            # Villager with the Cursed trait), held with the player's faction.
            role, added = RETIRED_BY_LABEL[p["role"]].now if p["role"] in RETIRED_BY_LABEL else (p["role"], ())
            roles.append(role)
            holder = FACTIONS.get(p["faction"], Alignment.NEUTRAL)
            dealt += [(t, holder) for t in dict.fromkeys([*p["traits"], *added])]
        if any(r not in PRIOR for r in roles) or any(t not in TRAITS for t, _ in dealt):
            continue
        setup = json.loads(path.open(encoding="utf-8").readline())
        same = variants.full((setup.get("settings") or {})) == variants.DEFAULTS
        out.append(Played(roles, int(g["winning_faction"] == "Village"), 1.0 if same else OTHER_SETTINGS_WEIGHT,
                          tuple(dealt)))
    return out


def terms(game: Played) -> list[tuple[str, int]]:
    """The game's trait terms: (power_key, sign for the Village), without a Neutral holder's (sign 0)."""
    return [(power_key(t, a), village_sign(a)) for t, a in game.traits if village_sign(a)]


def fit(data: list[Played], steps: int = 3000,
        rate: float = 0.05) -> tuple[float, dict[str, float], dict[str, float]]:
    """(offset, power per role, power per trait key) maximizing the games' weighted log-likelihood minus the pull
    towards the priors (L2, PRIOR_SD for roles and traits alike), by gradient ascent. Deterministic, and quick for a
    few hundred games."""
    power, trait_power, offset = dict(PRIOR), dict(TRAIT_PRIOR), OFFSET_PRIOR
    total = sum(g.weight for g in data) or 1.0
    game_terms = [terms(g) for g in data]
    for _ in range(steps):
        grad = {r: -(power[r] - PRIOR[r]) / PRIOR_SD ** 2 for r in power}
        t_grad = {k: -(trait_power[k] - TRAIT_PRIOR[k]) / PRIOR_SD ** 2 for k in trait_power}
        g_off = -(offset - OFFSET_PRIOR) / OFFSET_SD ** 2
        for g, tt in zip(data, game_terms):
            x = offset + sum(power[r] for r in g.roles) + sum(sign * trait_power[k] for k, sign in tt)
            err = g.weight * (g.won - 1 / (1 + math.exp(-x)))
            g_off += err
            for r in g.roles:
                grad[r] += err
            for k, sign in tt:
                t_grad[k] += sign * err
        step = rate / max(1.0, total / 20)
        offset += step * g_off
        for r in power:
            power[r] += step * grad[r]
        for k in trait_power:
            trait_power[k] += step * t_grad[k]
    return offset, power, trait_power


def trait_holder(key: str) -> str:
    """Whose trait a key's power is, for the table: "Yakuza" for "Grudge@Yakuza", else the factions that can hold the
    trait without a power_for of their own."""
    name, _, faction = key.partition("@")
    if faction:
        return faction
    info = TRAITS[name]
    return ", ".join(f for f, a in FACTIONS.items() if a in info.alignments and a not in (info.power_for or {}))


def update(log_dir: Path, path: Path | None = None) -> Path:
    """Refits from log_dir's games and writes path (default FILE, .json) and its .md table. Returns it."""
    from roles import ROLES
    path = path or FILE
    data = games(log_dir)
    offset, power, trait_power = fit(data)
    seen = {r: sum(r in g.roles for g in data) for r in PRIOR}
    trait_seen = {k: sum(k in dict(terms(g)) for g in data) for k in TRAIT_PRIOR}
    written = f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"written": written, "games": len(data), "offset": round(offset, 3),
                                "roles": {r: {"prior": PRIOR[r], "power": round(power[r], 3), "games": seen[r]}
                                          for r in PRIOR},
                                "traits": {k: {"prior": TRAIT_PRIOR[k], "power": round(trait_power[k], 3),
                                               "games": trait_seen[k]} for k in TRAIT_PRIOR}},
                               indent=1) + "\n", encoding="utf-8")
    village = sum(g.won for g in data)
    rows = sorted(PRIOR, key=lambda r: (ROLES[r].alignment.value, -power[r]))
    lines = [f"# Role power\n\nRefit {written} by `role_power.py` from {len(data)} finished live games "
             f"(Village won {village}). Power is how much a role adds to the Village's win chance, in logits "
             f"(+0.4 is about +10 points near even). Offset {offset:+.2f} (prior {OFFSET_PRIOR:+.2f}). Change the "
             "priors in role_power.py; this file is rewritten after every game.\n",
             "| Role | Side | Prior | Power | Games |", "|---|---|---|---|---|"]
    lines += [f"| {r} | {ROLES[r].alignment.value} | {PRIOR[r]:+.2f} | {power[r]:+.2f} | {seen[r]} |" for r in rows]
    lines += ["", "A trait's power is how much it helps its holder's side (the Village for a Village holder, the "
              "Yakuza for a Yakuza; a Neutral holder's traits aren't counted). Its prior is its power in traits.py.\n",
              "| Trait | Holder | Prior | Power | Games |", "|---|---|---|---|---|"]
    lines += [f"| {k.partition('@')[0]} | {trait_holder(k)} | {TRAIT_PRIOR[k]:+.2f} | {trait_power[k]:+.2f} | "
              f"{trait_seen[k]} |" for k in sorted(TRAIT_PRIOR, key=lambda k: -trait_power[k])]
    path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logs", type=Path, default=ROOT / "logs", help="folder of game logs")
    args = ap.parse_args()
    out = update(args.logs)
    print(f"Wrote {out} and {out.with_suffix('.md')}")
