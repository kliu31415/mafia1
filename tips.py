"""Tips from past games, a program feature rather than a rule: `build` distills the players' lessons
and the moderator's strategy reviews saved in game logs (--lessons) into a Markdown tips file, and
`mafia.py --tips FILE` puts that file into chosen players' system prompts, so games with experienced
and fresh players can be compared.

A tips file is Markdown with one `## <heading>` section per audience: "Everyone", a faction
("Village", "Yakuza", "Neutral") or a role name. Text before the first section is notes for whoever
edits the file and is never shown to players. A player sees "Everyone", their faction's section and
their current role's section; a section with any other heading goes to everyone. Hand edits are fine.

Usage:
    uv run tips.py build                                # all logs/game_*.jsonl -> tips/tips.md
    uv run tips.py build logs/game_2026100* --out tips/early.md --max-words 600
    uv run tips.py show tips/tips.md --role Medic       # what a Medic would see
    uv run mafia.py --tips tips/tips.md --tips-for half # a random half of the seats get the tips
"""

import argparse
import glob
import hashlib
import json
import random
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from llm import LLMClient, MockClient, Model, ModelSpec, OpenRouterClient, answer_json, load_api_key, parse_model_spec
from roles import ROLES, Alignment

ROOT = Path(__file__).resolve().parent
FACTIONS = {Alignment.GOOD: "Village", Alignment.EVIL: "Yakuza"}  # anything else is "Neutral"
HEADINGS = ["Everyone", "Village", "Yakuza", "Neutral", *ROLES]
FALLBACKS_TO_DISTRUST = 3  # a player with this many fallback answers barely played (e.g. a provider bug)

# How strong each model is at this game, 1-5, kept by hand (a first guess from general capability, to be
# replaced by measured results). Lessons count for more when their author's model is stronger, and when the
# game's players were stronger on average (lessons from a game of weak players may be about beating weak play).
STRENGTH = {
    Model.OPUS_5_5: 5, Model.GPT_6_1_SOL: 5,
    Model.SONNET_5_5: 4, Model.GEMINI_3_1_PRO: 4, Model.GROK_4_7: 4, Model.KIMI_K3: 4,
    Model.QWEN_3_8_MAX_PRIME: 4, Model.QWEN_3_8_MAX: 4,
    Model.GEMINI_3_8_FLASH: 3,
    Model.HAIKU_5_5: 2, Model.GPT_6_LUNA: 2,
}
DEFAULT_STRENGTH = 3  # a model missing from STRENGTH


def strength(model_id: str) -> int:
    return next((v for m, v in STRENGTH.items() if m.value == model_id), DEFAULT_STRENGTH)


def lesson_weight(author: int, game_average: float) -> float:
    """1.0 for a top model's lesson from a game of top models; 0.16 for the weakest in the weakest game."""
    return round((author / 5) * (game_average / 5), 2)


def faction_of(role: str) -> str:
    return FACTIONS.get(ROLES[role].alignment, "Neutral") if role in ROLES else "Neutral"


# ---------------------------------------------------------------------------------------------
# Reading tips files (used by players.py)
# ---------------------------------------------------------------------------------------------

def sections(text: str) -> dict[str, str]:
    """Heading -> body for each `## ` section; text before the first one is dropped."""
    out: dict[str, str] = {}
    heading = None
    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            out.setdefault(heading, "")
        elif heading is not None:
            out[heading] += line + "\n"
    return {h: body.strip() for h, body in out.items() if body.strip()}


def tips_for_role(text: str, role: str) -> str:
    """The parts of a tips file a player with this role sees, as Markdown."""
    audience = {"Everyone", faction_of(role), role}
    known = set(HEADINGS)
    return "\n\n".join(f"## {h}\n{body}" for h, body in sections(text).items()
                       if h in audience or h not in known)


def choose_players(names: list[str], models: list[str], who: str, rng: random.Random) -> list[str]:
    """Which players get tips. who: "all", "half" (a random half, rounded down, picked with rng), or comma-separated player names and model short names."""
    if who == "all":
        return names
    if who == "half":
        return sorted(rng.sample(names, len(names) // 2), key=names.index)
    wanted = {w.strip() for w in who.split(",") if w.strip()}
    unknown = wanted - set(names) - set(models)
    if unknown:
        raise ValueError(f"--tips-for: {sorted(unknown)} match no player name or model in this game "
                         f"(players {names}, models {sorted(set(models))})")
    return [n for n, m in zip(names, models) if n in wanted or m in wanted]


def file_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------------------------
# Building a tips file from game logs
# ---------------------------------------------------------------------------------------------

def read_game(path: Path) -> dict | None:
    """The lessons, strategy review and outcome of one game log, or None if it has no lessons."""
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    lessons = [r for r in records if r["kind"] in ("lessons", "strategy_review")]
    if not lessons:
        return None
    result: dict = next((r for r in records if r["kind"] == "result"), {})
    fallbacks = Counter(r.get("player") for r in records if r["kind"] == "player_fallback")
    return {"game": path.stem, "records": lessons, "result": result,
            "unreliable": sorted(p for p, n in fallbacks.items() if p and n >= FALLBACKS_TO_DISTRUST),
            "mock": next((r.get("settings", {}).get("mock") for r in records if r["kind"] == "setup"), False)}


def describe_game(g: dict) -> str:
    """One game's lessons as text for the distilling model."""
    res = g["result"]
    models = res.get("models", {})
    avg = sum(map(strength, models.values())) / len(models) if models else DEFAULT_STRENGTH
    lines = [f"### Game {g['game']} (average player strength {avg:.1f}/5)"]
    if res:
        roles = ", ".join(f"{n} ({r}, {models.get(n, '?').split('/')[-1]})" for n, r in res.get("roles", {}).items())
        lines.append(f"Winners: {', '.join(res.get('winners') or []) or 'nobody'} "
                     f"(faction: {res.get('winning_faction') or 'none'}, end: {res.get('end_reason')}, "
                     f"{res.get('days')} days). Roles: {roles}.")
        if res.get("errors"):
            lines.append(f"Program errors this game: {res['errors']}.")
    else:
        lines.append("(no result record: the game did not finish)")
    if g["unreliable"]:
        lines.append(f"Distrust lessons from {', '.join(g['unreliable'])}: many of their turns failed, so they "
                     "barely played.")
    for r in g["records"]:
        if r["kind"] == "strategy_review":
            w = lesson_weight(strength(r["model"]), avg)
            lines.append(f"Moderator's strategy review ({r['model'].split('/')[-1]}, saw everything): "
                         f"{r['summary'].strip()}")
            lines += [f"- [moderator, weight {w}] for {x['applies_to']}, {x['topic']}: {x['tip']} "
                      f"(evidence: {x['evidence']})" for x in r["lessons"]]
        else:
            won = "won" if r["who"] in (res.get("winners") or []) else "lost"
            w = lesson_weight(strength(r["model"]), avg)
            lines += [f"- [{r['who']}, {r['role']}, {won}, {r['model'].split('/')[-1]}, weight {w}] for {x['applies_to']}, "
                      f"{x['topic']}: {x['tip']}" for x in r["lessons"]]
    return "\n".join(lines)


def _obj(**props: dict) -> dict:  # players.obj; not imported, since players.py imports this module
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


DISTILL_SCHEMA = _obj(sections={"type": "array", "items": _obj(
    heading={"type": "string", "enum": HEADINGS},
    tips={"type": "array", "items": _obj(tip={"type": "string"},
                                         games={"type": "integer"})})})  # games: how many games support it


def distill(client: LLMClient, spec: ModelSpec, rules: str, games: list[dict], max_words: int) -> tuple[str, float]:
    """Ask `spec` to merge every game's lessons into one tips file. Returns (Markdown body, cost)."""
    lessons = "\n\n".join(describe_game(g) for g in games)
    messages = [
        {"role": "system", "content": f"{rules}\n\n---\n\nYou coach players of this game. Below are lessons "
         "written after past games by the players (each tagged with their role, whether they won, their "
         "model and a weight) and by the moderator, who saw everything, including hidden night actions. "
         "The weight (0-1) is higher when the lesson's author is a stronger model and when the game's "
         "players were stronger on average."},
        {"role": "user", "content": f"Lessons from {len(games)} games:\n\n{lessons}\n\n---\n\n"
         "Distill these into a tips sheet that will be given to players before future games, so they "
         "start with the experience of these games. Rules:\n"
         "- Merge duplicates. Prefer lessons with a high weight, lessons that recur across games, and "
         "lessons the moderator backs with evidence; a low-weight lesson needs support from elsewhere to be "
         "kept, and where lessons conflict, the higher-weight side wins. For each tip give the number of "
         "games that support it.\n"
         "- Drop tips that contradict the rules above, recaps of one game, tips about the program or "
         "interface rather than play, and vague advice ('be careful'). Lessons from players marked as "
         "barely playing, or from games with many program errors, count for less.\n"
         "- Each tip is one or two concrete sentences a player can act on.\n"
         "- Use one section per audience: 'Everyone', a faction ('Village', 'Yakuza', 'Neutral'), or a "
         "role name. A player sees only Everyone, their faction and their own role, so put a tip where "
         "its reader will act on it. Leave out sections with nothing useful.\n"
         f"- At most {max_words} words in total; drop the weakest tips first."},
    ]
    reply = client.chat(spec.model, messages, schema=DISTILL_SCHEMA, schema_name="tips", effort=spec.effort)
    order = {h: i for i, h in enumerate(HEADINGS)}
    out = []
    for s in sorted(answer_json(reply).get("sections", []), key=lambda s: order.get(s["heading"], len(order))):
        tips = [t for t in s["tips"] if t["tip"].strip()]
        if tips:
            out.append(f"## {s['heading']}\n" + "\n".join(
                f"- {t['tip'].strip()}" + (f" (seen in {t['games']} games)" if t["games"] >= 2 else "") for t in tips))
    return "\n\n".join(out) + "\n", reply.cost


def build(paths: list[Path], out: Path, client: LLMClient, spec: ModelSpec, max_words: int,
          include_mock: bool = False) -> Path:
    games = [g for p in sorted(paths) if (g := read_game(p)) and (include_mock or not g["mock"])]
    if not games:
        raise SystemExit("No game logs with lessons found (games need --lessons, which is on by default).")
    rules = (ROOT / "rules_1.txt").read_text(encoding="utf-8")
    body, cost = distill(client, spec, rules, games, max_words)
    header = (f"# Tips from past games\n\nBuilt {datetime.now():%Y-%m-%d %H:%M} by {spec} from {len(games)} games "
              f"with `uv run tips.py build`. Players never see this paragraph; the sections below go to "
              f"players by heading (see tips.py). Games: {', '.join(g['game'] for g in games)}.\n\n")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(header + body, encoding="utf-8")
    print(f"Tips: {out} ({len(body.split())} words, from {len(games)} games; cost ${cost:.2f})")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="distill lessons and strategy reviews from game logs into a tips file")
    b.add_argument("logs", nargs="*", help="game JSONL logs or globs (default: logs/game_*.jsonl)")
    b.add_argument("--out", default=str(ROOT / "tips" / "tips.md"))
    b.add_argument("--model", default="opus-5.5", help="model[:effort] that distills the tips")
    b.add_argument("--max-words", type=int, default=800, help="length cap for the whole tips file")
    b.add_argument("--exclude", default="", help="comma-separated game ids (log file stems) to leave out")
    b.add_argument("--mock", action="store_true", help="no API calls (random tips), and read mock_*.jsonl logs")
    s = sub.add_parser("show", help="print what a player with a given role would see")
    s.add_argument("file")
    s.add_argument("--role", required=True, choices=list(ROLES))
    args = ap.parse_args()
    if args.cmd == "show":
        print(tips_for_role(Path(args.file).read_text(encoding="utf-8"), args.role))
        return
    patterns = args.logs or [str(ROOT / "logs" / ("mock_*.jsonl" if args.mock else "game_*.jsonl"))]
    excluded = {e.strip() for e in args.exclude.split(",") if e.strip()}
    paths = {Path(p) for pat in patterns for p in (glob.glob(pat) or [pat])}
    paths = {p for p in paths if p.suffix == ".jsonl" and re.match(r"(game|mock)_\d", p.name) and p.stem not in excluded}
    client = MockClient(0) if args.mock else OpenRouterClient(load_api_key())
    build(sorted(paths), Path(args.out), client, parse_model_spec(args.model), args.max_words, include_mock=args.mock)


if __name__ == "__main__":
    main()
