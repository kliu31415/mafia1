"""A browsable handbook of the game as the code has it now: the rules (rules_1.txt, with links between rules, roles
and traits), every role (ROLES: faction, category, summary, rules paragraph, tokens, defense, live-tested, notes,
code hooks, icon), every trait (traits.TRAITS), the setups (setups.py, with a few sample draws), rule settings
(variants.py), scripts (scripts.py) and role and trait power (role_power.py's priors and tips/role_power.json's fit),
with a calculator that scores a setup the way the standard setup balances them.

    uv run handbook.py                    # writes logs/handbook.html and opens it
    uv run game_index.py serve            # also serves it, rebuilt on every load, at /handbook.html

Everything is read from those sources when the page is built (data()), so it never needs updating by hand; the page
itself (handbook_page.html) only lays the data out. A new role or trait shows up with no change here, and a new
field shows up once data() passes it on.
"""

import argparse
import json
import random
import re
import subprocess
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import role_power
import scripts
import setups
import variants
from gamelogs import faction_of
from log_viewer import ICONS, icon_slug, trait_slug
from role_summaries import RULES, role_paragraphs
from roles import RETIRED, ROLES, Alignment, code_hooks, logic
from traits import EXCLUSIVE, FACTIONS, TRAITS, fits, hand_powers, parse_item, power_key, village_power

ROOT = Path(__file__).resolve().parent
PAGE = ROOT / "handbook_page.html"
OUT = ROOT / "logs" / "handbook.html"
SAMPLES = 6  # sample standard setups drawn for the Setups tab, new ones on every build
FACTION_OF = {a: f for f, a in FACTIONS.items()}
RULE_HEAD = re.compile(r"^(R\d+) \((.+?)\)(.*)$")  # "R4 (Day phase, chat, nominations and trials)"


def rules_parts(text: str) -> list[dict]:
    """rules_1.txt as parts ("=== PART 1: THE GAME ===") of blocks (split on blank lines): a rule ("R4 (Title)"), a
    faction heading ("--- Village (Good) ---") or category heading in the roles part, a role's paragraph (its name,
    then indented lines), or plain text. Each block keeps its lines as written; the page joins wrapped lines."""
    parts: list[dict] = []
    pieces = re.split(r"^=== (.+?) ===$", text, flags=re.M)[1:]
    for title, chunk in zip(pieces[::2], pieces[1::2]):
        roles_part = "ROLES" in title
        blocks = []
        for raw in re.split(r"\n\s*\n", chunk.strip("\n")):
            lines = raw.rstrip().split("\n")
            first = lines[0]
            if m := RULE_HEAD.match(first):
                rest = m[3].strip(": ")  # R20's heading line goes on with text
                blocks.append({"kind": "rule", "label": m[1], "title": m[2], "lines": [rest] * bool(rest) + lines[1:]})
            elif m := re.match(r"^--- (.+) ---$", first):
                blocks.append({"kind": "faction", "title": m[1], "lines": lines[1:]})
            elif first.strip() in ROLES and len(lines) > 1 and lines[1].startswith("  "):
                blocks.append({"kind": "role", "name": first.strip(), "lines": lines[1:]})
            elif roles_part and len(lines) == 1 and not first.startswith(" "):
                name, _, note = first.partition(" (")
                blocks.append({"kind": "category", "title": name, "note": note.rstrip(")")})
            else:
                blocks.append({"kind": "text", "lines": lines})
        parts.append({"title": title.title(), "blocks": blocks})
    return parts


def icon(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def power_table() -> dict:
    """The fit in tips/role_power.json (when it reads), with the priors for anything it lacks."""
    try:
        fit = json.loads(role_power.FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        fit = {}
    offset, roles = role_power.load()
    traits = role_power.load_traits()
    return {"written": fit.get("written", ""), "games": fit.get("games", 0), "offset": offset,
            "offset_prior": role_power.OFFSET_PRIOR, "off": fit.get("off") or {},
            "roles": {r: {"prior": role_power.PRIOR[r], "power": roles[r],
                          "games": (fit.get("roles") or {}).get(r, {}).get("games", 0)} for r in role_power.PRIOR},
            "traits": {k: {"prior": p, "power": traits[k],
                           "games": (fit.get("traits") or {}).get(k, {}).get("games", 0)}
                       for k, p in hand_powers().items()}}


def role_entries(powers: dict) -> list[dict]:
    paragraphs = role_paragraphs()
    script_names = [s for s, chosen in scripts.SCRIPTS.items() if chosen is not None]
    out = []
    for name, info in ROLES.items():
        lg = logic(name)
        out.append({
            "name": name, "faction": faction_of(name), "category": info.category, "subcategory": info.subcategory,
            "summary": info.summary, "rules": paragraphs.get(name, ""), "defense": info.defense,
            "tokens": info.tokens, "night": info.acts_at_night, "unique": info.unique, "tested": info.tested,
            "notes": info.notes, "sheriff": "Evil" if info.sheriff_evil else "Not Evil", "icon": icon_slug(name),
            "hooks": code_hooks(lg), "night_note": bool(lg.night_note),
            "scripts": [s for s in script_names if name in scripts.roles_of(s)],
            "off": [s for s, setup in setups.SETUPS.items() if name in setup.off],
            "power": powers["roles"].get(name),
            "traits": [t for t in TRAITS if fits(t, name)],
        })
    return out


def trait_entries(powers: dict) -> list[dict]:
    out = []
    for name, info in TRAITS.items():
        factions = [FACTION_OF[a] for a in Alignment if a in info.alignments]
        out.append({
            "name": name, "slug": trait_slug(name), "summary": info.summary, "hover": info.hover,
            "factions": factions, "hidden": info.hidden, "mark": " ".join(info.mark.split()),
            "roles": [r for r in ROLES if fits(name, r)],
            "excludes": sorted({o for e in EXCLUSIVE if name in e for o in e} - {name}),
            # what it adds to the Village's score held by each faction it can go to (the calculator adds these)
            "village": {FACTION_OF[a]: round(village_power(name, a, {k: v["power"] for k, v in
                                                                      powers["traits"].items()}), 3)
                        for a in Alignment if a in info.alignments},
            "powers": {FACTION_OF[a]: powers["traits"][power_key(name, a)] for a in Alignment if a in info.alignments},
        })
    return out


def samples(n: int = SAMPLES, players: int = 13) -> list[dict]:
    """A few standard setups as setups.py draws them (roles, then traits), each with its score."""
    out = []
    rng = random.Random()
    for _ in range(n):
        roles = setups.balanced_setup(players, rng)
        traits = setups.draw_traits(roles, rng)
        dealt = []
        for item in traits:
            names, alignment = parse_item(item)
            for t in names:
                dealt.append((t, alignment or next(iter(TRAITS[t].alignments))))
        out.append({"roles": sorted(roles, key=list(ROLES).index), "traits": traits,
                    "village": round(role_power.village_chance(roles, traits=dealt), 3)})
    return out


def setup_entries() -> dict:
    standard = setups.SETUPS["standard"]
    return {
        "setups": [{"name": n, "players": list(s.players), "describe": s.describe, "off": list(s.off)}
                   for n, s in setups.SETUPS.items()],
        "standard": {"yakuza_odds": setups.yakuza_odds(standard.players[0]), "neutral_odds": setups.NEUTRAL_ODDS,
                     "village_needs": setups.VILLAGE_NEEDS, "min_village": setups.MIN_VILLAGE,
                     "max_outsiders": setups.MAX_OUTSIDERS, "band": setups.BAND, "off": list(standard.off),
                     "trait_share": setups.TRAIT_SHARE, "trait_odds": setups.trait_odds(standard.players[0]),
                     "players": standard.players[0]},
        "note": setups.setup_note({"kind": "random", "name": "standard"}, ["?"] * standard.players[0]).strip(
            "\n-").strip(),
        "samples": samples(),
    }


def setting_note(name: str, choice: str) -> str:
    """What choosing this setting adds to the rules: its line of variants.rules_notes, without the preamble."""
    lines = variants.rules_notes({**variants.DEFAULTS, name: choice}).splitlines()
    return " ".join(line.removeprefix("- ") for line in lines if line.startswith("- "))


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def data() -> dict:
    """Everything the page shows, read from the sources (see the module docstring)."""
    powers = power_table()
    return {
        "built": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "commit": git_commit(),
        "rules": rules_parts(RULES.read_text(encoding="utf-8")),
        "roles": role_entries(powers),
        "retired": [{"name": name, "faction": faction_of(name), "summary": e.info.summary, "until": e.until,
                     "rules": e.rules, "now": f"{e.now[0]}" + "".join(f" + {t}" for t in e.now[1])}
                    for name, entries in RETIRED.items() for e in entries],
        "traits": trait_entries(powers),
        "power": {k: v for k, v in powers.items() if k not in ("roles", "traits")} | {
            "trait_rows": powers["traits"], "band": setups.BAND},
        "setups": setup_entries(),
        "settings": [{"name": n, "choices": list(c), "default": variants.DEFAULTS[n],
                      "notes": {ch: setting_note(n, ch) for ch in c[1:]}}
                     for n, c in variants.SETTINGS.items()],
        "scripts": {s: scripts.roles_of(s) for s in scripts.SCRIPTS},
        "icons": {p.stem: icon(p) for p in sorted(ICONS.glob("*.svg"))},
    }


def render(d: dict | None = None) -> str:
    """The page: handbook_page.html with the data in it (as JSON; "</" escaped so no string can end the script)."""
    payload = json.dumps(d if d is not None else data(), ensure_ascii=False).replace("</", "<\\/")
    return PAGE.read_text(encoding="utf-8").replace("/*DATA*/null", payload)


def build(out: Path = OUT) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(), encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT, help="where to write it (default logs/handbook.html)")
    ap.add_argument("--no-open", action="store_true", help="don't open it in a browser")
    args = ap.parse_args()
    out = build(args.out)
    print(f"Wrote {out}")
    if not args.no_open:
        webbrowser.open(out.resolve().as_uri())


if __name__ == "__main__":
    main()
