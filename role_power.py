"""Role power: how much each role moves the Village's chance to win, for setups that balance their draws
(setups.py "standard"). A setup's score is the offset plus the sum of its roles' powers; the Village's estimated
chance to win is logistic(score), so 0 means even, and +0.4 is about 60%.

A living document (Kevin, Oct 10 2026): PRIOR holds hand-set intuition (from notes/role-ratings.md, the role
strength review and the live games so far: a Good seat about +0.25 to +0.55, a Yakuza seat about -0.85 to -1.1,
Outsiders near 0, Neutral killers clearly negative). `fit` refits every power from finished live games: a logistic
regression of "the Village won" on the setup's roles, pulled towards PRIOR (each prior counts like a few games,
so a role seen in few games stays near its prior). The result goes in tips/role_power.json, which setups read,
and tips/role_power.md, a readable table. They're rebuilt where the tips are (a PC game's end, `sync_logs.py
pull`), so the existing tips commit and publish carry them to main and to cloud games. Edit PRIOR to change
the intuition; `uv run role_power.py` refits by hand.
"""

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import variants

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


def load(path: Path | None = None) -> tuple[float, dict[str, float]]:
    """(offset, power per role): the last fit (FILE), with PRIOR for roles it lacks; PRIOR alone without a fit."""
    try:
        data = json.loads((path or FILE).read_text(encoding="utf-8"))
        fitted = {r: v["power"] for r, v in data["roles"].items()}
        return data["offset"], {r: fitted.get(r, p) for r, p in PRIOR.items()}
    except (OSError, ValueError, KeyError):
        return OFFSET_PRIOR, dict(PRIOR)


def score(roles: list[str], path: Path | None = None) -> float:
    offset, power = load(path)
    return offset + sum(power[r] for r in roles)


def village_chance(roles: list[str], path: Path | None = None) -> float:
    return 1 / (1 + math.exp(-score(roles, path)))


def games(log_dir: Path) -> list[tuple[list[str], int, float]]:
    """(start roles, 1 if the Village won else 0, weight) for each finished live game in log_dir that has a
    winning faction (games stopped by the stall rule or the day limit are left out)."""
    import stats  # here: it imports the game index, which setups (which imports this) doesn't need
    out = []
    for path in sorted(log_dir.glob("game_*.jsonl")):
        g = stats.load_game(path)
        if not g or g["mock"] or g["winning_faction"] is None or any(r not in PRIOR for r in g["roles"]):
            continue
        setup = json.loads(path.open(encoding="utf-8").readline())
        same = variants.full((setup.get("settings") or {})) == variants.DEFAULTS
        out.append((g["roles"], int(g["winning_faction"] == "Village"), 1.0 if same else OTHER_SETTINGS_WEIGHT))
    return out


def fit(data: list[tuple[list[str], int, float]], steps: int = 3000, rate: float = 0.05) -> tuple[float, dict]:
    """(offset, power per role) maximizing the games' weighted log-likelihood minus the pull towards PRIOR
    (L2, PRIOR_SD), by gradient ascent. Deterministic, and quick for a few hundred games."""
    power, offset = dict(PRIOR), OFFSET_PRIOR
    total = sum(w for _, _, w in data) or 1.0
    for _ in range(steps):
        grad = {r: -(power[r] - PRIOR[r]) / PRIOR_SD ** 2 for r in power}
        g_off = -(offset - OFFSET_PRIOR) / OFFSET_SD ** 2
        for roles, won, w in data:
            p = 1 / (1 + math.exp(-(offset + sum(power[r] for r in roles))))
            err = w * (won - p)
            g_off += err
            for r in roles:
                grad[r] += err
        step = rate / max(1.0, total / 20)
        offset += step * g_off
        for r in power:
            power[r] += step * grad[r]
    return offset, power


def update(log_dir: Path, path: Path | None = None) -> Path:
    """Refits from log_dir's games and writes path (default FILE, .json) and its .md table. Returns it."""
    from roles import ROLES
    path = path or FILE
    data = games(log_dir)
    offset, power = fit(data)
    seen = {r: sum(r in roles for roles, _, _ in data) for r in PRIOR}
    written = f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"written": written, "games": len(data), "offset": round(offset, 3),
                                "roles": {r: {"prior": PRIOR[r], "power": round(power[r], 3), "games": seen[r]}
                                          for r in PRIOR}}, indent=1) + "\n", encoding="utf-8")
    village = sum(won for _, won, _ in data)
    rows = sorted(PRIOR, key=lambda r: (ROLES[r].alignment.value, -power[r]))
    lines = [f"# Role power\n\nRefit {written} by `role_power.py` from {len(data)} finished live games "
             f"(Village won {village}). Power is how much a role adds to the Village's win chance, in logits "
             f"(+0.4 is about +10 points near even). Offset {offset:+.2f} (prior {OFFSET_PRIOR:+.2f}). Change the "
             "priors in role_power.py; this file is rewritten after every game.\n",
             "| Role | Side | Prior | Power | Games |", "|---|---|---|---|---|"]
    lines += [f"| {r} | {ROLES[r].alignment.value} | {PRIOR[r]:+.2f} | {power[r]:+.2f} | {seen[r]} |" for r in rows]
    path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logs", type=Path, default=ROOT / "logs", help="folder of game logs")
    args = ap.parse_args()
    out = update(args.logs)
    print(f"Wrote {out} and {out.with_suffix('.md')}")
