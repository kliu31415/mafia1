"""Tips from past games, a program feature rather than a rule: `build` distills the players' lessons
and the moderator's strategy reviews saved in game logs (--lessons) into a Markdown tips file, and
`mafia.py --tips FILE` puts that file into chosen players' system prompts, so games with experienced
and fresh players can be compared. The models learn collectively: one tips file pools every model's
lessons, to make the strongest player possible.

A tips file is Markdown with one `## <heading>` section per audience: "Everyone", a faction
("Village", "Yakuza", "Neutral") or a role name. Text before the first section is notes for whoever
edits the file and is never shown to players. Players see every section, the way an experienced player
knows how every role tends to play, not only their own. Hand edits are fine.

Two living documents, the way a serious player keeps detailed notes and a short cheat sheet:
- the notebook (tips/tips_notebook.json, readable as .md): every tip ever learned, with the games and
  evidence behind it and reports of it backfiring, including ideas too thinly supported for players
  yet. `build` updates it one new game at a time (their lessons, plus what players who had the tips and
  the moderator say went especially well or badly with them) through small ops, so nothing is lost to
  a rewrite.
- the sheet (tips/tips.md): what players get, distilled from the notebook's active entries each time.
Old versions of both go to history/. --fresh starts a new notebook. `mafia.py --update-tips FILE`
runs the update after each game.

Usage:
    uv run tips.py build                                # add new logs/game_*.jsonl, rewrite tips/tips.md
    uv run tips.py build logs/game_2026100* --out tips/early.md --max-words 600
    uv run tips.py show tips/tips.md                    # what players see
    uv run mafia.py --tips tips/tips.md --tips-for half # a random half of the seats get the tips
    uv run mafia.py --player-tips Alice=tips/history/tips_20261009_120000.md,gpt-6-luna=none
"""

import argparse
import glob
import hashlib
import json
import os
import random
import re
import time
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from llm import LLMClient, MockClient, Model, ModelSpec, OpenRouterClient, answer_json, load_api_key, parse_model_spec
from roles import ROLES

ROOT = Path(__file__).resolve().parent
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


def player_view(text: str) -> str:
    """What players see of a tips file: every section, without the preamble."""
    return "\n\n".join(f"## {h}\n{body}" for h, body in sections(text).items())


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


def parse_player_tips(spec: str) -> list[tuple[str, Path | None]]:
    """'Alice=tips/a.md,gpt-6-luna=none' -> [("Alice", Path("tips/a.md")), ("gpt-6-luna", None)]."""
    out: list[tuple[str, Path | None]] = []
    for item in filter(None, (i.strip() for i in spec.split(","))):
        who, sep, file = item.partition("=")
        if not sep or not who.strip() or not file.strip():
            raise ValueError(f"--player-tips: expected WHO=FILE or WHO=none, got {item!r}")
        out.append((who.strip(), None if file.strip().lower() == "none" else Path(file.strip())))
    return out


def assign_tips(names: list[str], models: list[str], tips: Path | None, tips_for: str,
                player_tips: list[tuple[str, Path | None]], rng: random.Random) -> dict[str, Path]:
    """Each player's tips file: `tips` for the players `tips_for` picks, then `player_tips` (player names
    or models, each with a file or None for no tips); a player's name wins over their model."""
    out = dict.fromkeys(choose_players(names, models, tips_for, rng), tips) if tips else {}
    unknown = {w for w, _ in player_tips} - set(names) - set(models)
    if unknown:
        raise ValueError(f"--player-tips: {sorted(unknown)} match no player name or model in this game "
                         f"(players {names}, models {sorted(set(models))})")
    for who, file in sorted(player_tips, key=lambda x: x[0] in names):  # models first, then names
        for n, m in zip(names, models):
            if who in (n, m):
                if file:
                    out[n] = file
                else:
                    out.pop(n, None)
    return {n: out[n] for n in names if out.get(n)}


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
    tips = next((r for r in records if r["kind"] == "tips"), None)
    return {"game": path.stem, "records": lessons, "result": result, "had_tips": tips["players"] if tips else [],
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
    if g["had_tips"]:
        lines.append(f"Players given a tips sheet from earlier games: {', '.join(g['had_tips'])}.")
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
            author = f"moderator, weight {w}"
        else:
            won = "won" if r["who"] in (res.get("winners") or []) else "lost"
            w = lesson_weight(strength(r["model"]), avg)
            author = f"{r['who']}, {r['role']}, {won}, {r['model'].split('/')[-1]}, weight {w}"
            lines += [f"- [{author}] for {x['applies_to']}, {x['topic']}: {x['tip']}" for x in r["lessons"]]
        lines += [f"- [{author}] FEEDBACK ON THE TIPS SHEET, {x['verdict']}: \"{x['tip']}\" because {x['why']}"
                  for x in r.get("tips_feedback", [])]
    return "\n".join(lines)


def _obj(**props: dict) -> dict:  # players.obj; not imported, since players.py imports this module
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def system_prompt(rules: str, role: str) -> str:
    return (f"{rules}\n\n---\n\nYou coach players of this game. {role} Lessons come from past games, written "
            "by the players (each tagged with their role, whether they won, their model and a weight) and by "
            "the moderator, who saw everything, including hidden night actions. The weight (0-1) is higher when "
            "the author is a stronger model and when the game's players were stronger on average.")


# The notebook: every tip ever learned, with its evidence, in JSON (<sheet>_notebook.json, plus a
# readable .md). The model updates it one game at a time with small ops, so nothing it once knew is
# lost to a rewrite, including ideas with thin evidence that aren't worth a place on the sheet yet.
OPS_SCHEMA = _obj(ops={"type": "array", "items": _obj(
    op={"type": "string", "enum": ["add", "support", "against", "edit", "retire", "restore"]},
    id={"type": "string"},  # an existing entry's id; "" for add
    audience={"type": "string", "enum": HEADINGS},  # for add (and edit, to move it)
    tip={"type": "string"},  # for add and edit; "" otherwise
    weight={"type": "number"},  # the weight of the lesson or report this op is based on
    note={"type": "string"})})  # the evidence, or why (for against, edit, retire, restore)


def new_notebook() -> dict:
    return {"games": [], "next_id": 1, "entries": []}


def notebook_path(sheet: Path) -> Path:
    return sheet.with_name(sheet.stem + "_notebook.json")


def entry_line(e: dict, notes: int = 3) -> str:
    """One notebook entry for a model to read: id, audience, tip, support and reports against it."""
    games = {x["game"] for x in e["support"]}
    line = (f"[{e['id']}] ({e['audience']}) {e['tip']} | support: {len(games)} games, total weight "
            f"{sum(x['weight'] for x in e['support']):.2f}")
    if e["against"]:
        line += (f" | against: {len(e['against'])} reports, total weight {sum(x['weight'] for x in e['against']):.2f}: "
                 + "; ".join(x["note"] for x in e["against"][-notes:]))
    if e["support"] and notes:
        line += " | recent evidence: " + "; ".join(x["note"] for x in e["support"][-notes:] if x["note"])
    return line


def notebook_view(nb: dict) -> str:
    live = [entry_line(e) for e in nb["entries"] if e["status"] == "active"]
    retired = [f"[{e['id']}] ({e['audience']}) {e['tip']} | retired: {e['history'][-1]['note'] if e['history'] else ''}"
               for e in nb["entries"] if e["status"] == "retired"]
    return ("\n".join(live) or "(empty)") + ("\n\nRetired entries:\n" + "\n".join(retired) if retired else "")


def apply_ops(nb: dict, ops: list[dict], game: str) -> int:
    """Carries out the model's ops on the notebook; returns how many were skipped (an unknown id, an
    empty tip)."""
    by_id = {e["id"]: e for e in nb["entries"]}
    skipped = 0
    for op in ops:
        w = op.get("weight")
        kind, note, weight = op["op"], op["note"].strip(), max(0.0, min(1.0, w)) if isinstance(w, (int, float)) else 0.0
        if kind == "add":
            if not op["tip"].strip():
                skipped += 1
                continue
            added = {"id": f"t{nb['next_id']}", "audience": op["audience"], "tip": op["tip"].strip(), "status": "active",
                 "support": [{"game": game, "weight": weight, "note": note}], "against": [],
                 "history": [{"game": game, "change": "added"}]}
            nb["next_id"] += 1
            nb["entries"].append(added)
            by_id[added["id"]] = added
            continue
        e = by_id.get(op["id"])
        if e is None:
            skipped += 1
            continue
        if kind == "support":
            e["support"].append({"game": game, "weight": weight, "note": note})
        elif kind == "against":
            e["against"].append({"game": game, "weight": weight, "note": note})
        elif kind == "edit" and op["tip"].strip():
            e["history"].append({"game": game, "change": "edited", "old": e["tip"], "note": note})
            e["tip"], e["audience"] = op["tip"].strip(), op["audience"]
        elif kind in ("retire", "restore"):
            e["status"] = "retired" if kind == "retire" else "active"
            e["history"].append({"game": game, "change": kind + "d", "note": note})
        else:
            skipped += 1
    nb["games"].append(game)
    return skipped


def update_notebook(client: LLMClient, spec: ModelSpec, rules: str, nb: dict, g: dict) -> tuple[int, int, float]:
    """Updates the notebook with one game. Returns (ops applied, ops skipped, cost)."""
    messages = [
        {"role": "system", "content": system_prompt(rules, "You keep a notebook of everything learned about "
         "playing this game well: the long-term memory behind a short tips sheet that players get.")},
        {"role": "user", "content": f"The notebook so far:\n\n{notebook_view(nb)}\n\n---\n\nLessons from a new game:"
         f"\n\n{describe_game(g)}\n\n---\n\nUpdate the notebook with this game, as ops:\n"
         "- support: a lesson matches an existing entry. Give the lesson's weight and a short note of the "
         "evidence (who, and what happened).\n"
         "- add: a concrete, reusable lesson with no entry yet, with its audience ('Everyone', a faction or a "
         "role), weight and evidence. Keep ideas with thin evidence too: the notebook is where they wait for "
         "more games, and only the best reach the players' sheet.\n"
         "- against: a report that an entry backfired, was exploited by opponents, or is wrong, with the "
         "report's weight and why. FEEDBACK ON THE TIPS SHEET lines are such reports when they say hurt or "
         "wrong, and support when they say helped.\n"
         "- edit: new evidence refines an entry (sharper wording, a condition, a different audience); give "
         "the new tip and why.\n"
         "- retire: an entry is shown wrong (it contradicts the rules, or well-weighted reports keep showing "
         "it backfires); restore: new evidence revives a retired entry, instead of adding it again.\n"
         "Skip recaps of this game, complaints about the program or interface, vague advice, lessons that "
         "contradict the rules, and lessons from players marked as barely playing. Several ops can come "
         "from one lesson, and no ops is fine if the game taught nothing new."},
    ]
    reply = client.chat(spec.model, messages, schema=OPS_SCHEMA, schema_name="notebook_ops", effort=spec.effort)
    ops = answer_json(reply).get("ops", [])
    skipped = apply_ops(nb, ops, g["game"])
    return len(ops) - skipped, skipped, reply.cost


def render_notebook(nb: dict) -> str:
    """The notebook as Markdown, for people to read."""
    out = [f"# Tips notebook\n\nEverything learned from {len(nb['games'])} games, with evidence. Built by "
           "`uv run tips.py build`; the players' sheet is distilled from the active entries.\n"]
    for status in ("active", "retired"):
        entries = [e for e in nb["entries"] if e["status"] == status]
        if entries:
            out.append(f"## {status.capitalize()} ({len(entries)})\n")
            out += [f"- {entry_line(e, notes=10)}" for e in sorted(entries, key=lambda e: HEADINGS.index(e["audience"])
                                                                     if e["audience"] in HEADINGS else len(HEADINGS))]
            out.append("")
    return "\n".join(out)


DISTILL_SCHEMA = _obj(sections={"type": "array", "items": _obj(
    heading={"type": "string", "enum": HEADINGS},
    tips={"type": "array", "items": _obj(tip={"type": "string"},
                                         games={"type": "integer"})})})  # games: how many games support it


def write_sheet(client: LLMClient, spec: ModelSpec, rules: str, nb: dict, max_words: int) -> tuple[str, float]:
    """Distills the notebook's active entries into the players' tips sheet. Returns (Markdown body, cost)."""
    entries = "\n".join(entry_line(e) for e in nb["entries"] if e["status"] == "active")
    messages = [
        {"role": "system", "content": system_prompt(rules, "You keep a notebook of tips learned from past "
         "games, and from it write the short tips sheet players get before a game.")},
        {"role": "user", "content": f"The notebook ({len(nb['games'])} games):\n\n{entries}\n\n---\n\n"
         "Write the tips sheet: the most useful entries, merged and worded for a player about to play. Rules:\n"
         "- Prefer entries with more games and total weight behind them; an entry with reports against it "
         "needs clearly more support than reports, or a rewording that fixes what went wrong. Thinly supported "
         "entries make the sheet only if they are clearly valuable. For each tip give the number of games "
         "that support it.\n"
         "- Each tip is one or two concrete sentences a player can act on.\n"
         "- Use one section per audience: 'Everyone', a faction ('Village', 'Yakuza', 'Neutral'), or a "
         "role name. Every player sees the whole sheet, so a section also tells the other side how that "
         "role or faction tends to play (e.g. a Villager reading the Yakuza section learns their usual "
         "tricks); include tips on spotting and countering each side. Leave out sections with nothing "
         "useful.\n"
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


class NoNewGames(Exception):
    pass


def print_alert(kind: str, error: str, **data: Any) -> None:
    """How `uv run tips.py build` reports errors (a game's own build logs them with GameLog.error)."""
    print(f"ALERT {kind}: {error}", flush=True)


LOCK_WAIT_S = 3600  # how long a build waits for another process's build of the same sheet
LOCK_STALE_S = 1800  # a lock older than this was left by a process that died, and is taken over


@contextmanager
def locked(path: Path, on_error: Callable[..., None] = print_alert) -> Iterator[None]:
    """Only one process at a time builds a given sheet (games running in parallel each update the tips
    when they finish): a lock file next to it, created atomically, works across processes and OSes."""
    lock = path.with_name(path.name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + LOCK_WAIT_S
    while True:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE_S:
                    on_error("tips_error", f"took over {lock}, left for over {LOCK_STALE_S}s by a build that "
                             "probably crashed", lock=str(lock))
                    lock.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.time() > deadline:
                raise TimeoutError(f"{lock} is still held by another build after {LOCK_WAIT_S}s") from None
            time.sleep(1)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def write_atomic(path: Path, text: str) -> None:
    """So a game starting meanwhile never reads a half-written sheet."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def build(paths: list[Path], out: Path, client: LLMClient, spec: ModelSpec, max_words: int,
          include_mock: bool = False, fresh: bool = False, on_error: Callable[..., None] = print_alert) -> Path:
    """Updates the notebook beside the sheet `out` with each game it doesn't have yet (in log order),
    then rewrites the sheet from it. Earlier versions of both go to <out dir>/history/. `fresh` starts
    a new notebook. Safe to run from several processes at once: builds of the same sheet take turns.
    on_error(kind, summary, **fields) is told about problems that don't stop the build (GameLog.error)."""
    with locked(out, on_error):
        return _build(paths, out, client, spec, max_words, include_mock, fresh, on_error)


def _build(paths: list[Path], out: Path, client: LLMClient, spec: ModelSpec, max_words: int,
           include_mock: bool, fresh: bool, on_error: Callable[..., None]) -> Path:
    nb_path = notebook_path(out)
    nb = new_notebook() if fresh or not nb_path.exists() else json.loads(nb_path.read_text(encoding="utf-8"))
    games = [g for p in sorted(paths, key=lambda p: p.name) if p.stem not in nb["games"] and (g := read_game(p))
             and (include_mock or not g["mock"])]
    if not games:
        raise NoNewGames("No new game logs with lessons found (games need --lessons, which is on by default)."
                         + (f" {nb_path} already has all {len(nb['games'])} games." if nb["games"] else ""))
    rules = (ROOT / "rules_1.txt").read_text(encoding="utf-8")
    cost = 0.0
    for g in games:
        applied, skipped, c = update_notebook(client, spec, rules, nb, g)
        cost += c
        print(f"  {g['game']}: {applied} notebook changes" + (f" ({skipped} invalid ones skipped)" if skipped else ""))
        if skipped:
            on_error("tips_error", f"the tips model gave {skipped} invalid notebook changes for {g['game']} "
                     "(an unknown entry id or an empty tip); they were skipped", game=g["game"], skipped=skipped)
    body, c = write_sheet(client, spec, rules, nb, max_words)
    cost += c
    stamp = f"{datetime.now():%Y%m%d_%H%M%S_%f}"
    for path in (out, nb_path):
        if path.exists():
            (out.parent / "history").mkdir(parents=True, exist_ok=True)
            (out.parent / "history" / f"{path.stem}_{stamp}{path.suffix}").write_bytes(path.read_bytes())
    active = sum(e["status"] == "active" for e in nb["entries"])
    header = (f"# Tips from past games\n\nWritten {datetime.now():%Y-%m-%d %H:%M} by {spec} with `uv run tips.py "
              f"build`, from the {active} active entries of {nb_path.name} ({len(nb['games'])} games). Players never "
              "see this preamble; they see every section below. Earlier versions are in history/.\n\n")
    out.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(nb_path, json.dumps(nb, indent=1, ensure_ascii=False))
    write_atomic(nb_path.with_suffix(".md"), render_notebook(nb))
    write_atomic(out, header + body)
    print(f"Tips: {out} ({len(body.split())} words) from {nb_path.name} ({active} active entries, "
          f"{len(nb['games'])} games; {len(games)} new); cost ${cost:.2f}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="update the notebook with new games' lessons, then rewrite the tips sheet")
    b.add_argument("logs", nargs="*", help="game JSONL logs or globs (default: logs/game_*.jsonl)")
    b.add_argument("--out", default=str(ROOT / "tips" / "tips.md"), help="the players' sheet; the notebook is "
                   "<name>_notebook.json (and .md) beside it")
    b.add_argument("--model", default="opus-5.5", help="model[:effort] that distills the tips")
    b.add_argument("--max-words", type=int, default=800, help="length cap for the whole tips file")
    b.add_argument("--exclude", default="", help="comma-separated game ids (log file stems) to leave out")
    b.add_argument("--fresh", action="store_true", help="start a new notebook from all the games, instead of "
                   "adding the games it doesn't have yet")
    b.add_argument("--mock", action="store_true", help="no API calls (random tips), and read mock_*.jsonl logs")
    s = sub.add_parser("show", help="print what players see of a tips file")
    s.add_argument("file")
    args = ap.parse_args()
    if args.cmd == "show":
        print(player_view(Path(args.file).read_text(encoding="utf-8")))
        return
    patterns = args.logs or [str(ROOT / "logs" / ("mock_*.jsonl" if args.mock else "game_*.jsonl"))]
    excluded = {e.strip() for e in args.exclude.split(",") if e.strip()}
    paths = {Path(p) for pat in patterns for p in (glob.glob(pat) or [pat])}
    paths = {p for p in paths if p.suffix == ".jsonl" and re.match(r"(game|mock)_\d", p.name) and p.stem not in excluded}
    client = MockClient(0) if args.mock else OpenRouterClient(load_api_key())
    if isinstance(client, OpenRouterClient):
        client.on_error = print_alert
    try:
        build(sorted(paths), Path(args.out), client, parse_model_spec(args.model), args.max_words, include_mock=args.mock,
              fresh=args.fresh)
    except NoNewGames as e:
        raise SystemExit(str(e)) from None


if __name__ == "__main__":
    main()
