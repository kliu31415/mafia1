"""Errors from games that nobody has reviewed yet, so they get looked at without anyone reading logs.

Every error a game runs into is logged with alert: true (GameLog.error). This lists the games in logs/
whose errors haven't been marked reviewed (and problems the moderator flagged, players reported in their
feedback field, or the post-game log review rated high severity), plus games that stopped with no result and no
crash record (the process was killed). Claude Code runs `--hook` when a session starts in this folder
(.claude/settings.json), so Claude sees new errors and brings them up; a finished game also prints a
reminder line while any are unreviewed. Reviewed errors are kept in logs/alerts_reviewed.json (by when
each happened), so a game that gets new errors later (e.g. it was resumed) shows up again.

Claude acks problems once they're fully handled (fixed, settled, or noise) without asking. Ones still being
discussed are marked in progress with a note (logs/alerts_in_progress.json, kept on this machine only): they
stay listed, briefly and apart from new ones, until they're acked.

Usage:
    uv run alerts.py                 # list games with unreviewed errors
    uv run alerts.py --ack all       # mark them all reviewed (or give game ids, e.g. game_20261009_004910_895267)
    uv run alerts.py --wip GAME --note "budget pricing: waiting on Kevin"   # mark in progress (or "all")
    uv run alerts.py --hook          # for the SessionStart hook: prints nothing when everything is reviewed
    uv run alerts.py --mock          # the same for mock games
"""

import argparse
import json
import os
import re
import time
from collections import Counter
from pathlib import Path

from records import safe_print

LOG_DIR = Path(__file__).resolve().parent / "logs"
REVIEWED_FILE = "alerts_reviewed.json"
IN_PROGRESS_FILE = "alerts_in_progress.json"
STOPPED_AFTER_S = 3600  # a log with no result, untouched this long, belongs to a game that was killed
SAMPLES_PER_KIND = 2
# Not errors, but problems players, the moderator or the log review noticed (bugs, leaks, rules gaps): listed too.
FEEDBACK_MARKS = (b'"kind": "moderator_flag"', b'"kind": "player_feedback"', b'"kind": "review"')


def scan(path: Path) -> dict:
    """A game log's problems: an id for each (its error records' times, "stopped" if it stopped silently,
    "unreadable:<n>" for error lines that aren't JSON), counts per kind and a few samples."""
    data = path.read_bytes()
    finished = b'"kind": "result"' in data
    stale = time.time() - path.stat().st_mtime >= STOPPED_AFTER_S
    lines = data.split(b"\n")
    errors, unreadable = [], 0
    for i, line in enumerate(lines):
        if b'"alert": true' not in line and not any(m in line for m in FEEDBACK_MARKS):
            continue
        try:
            r = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            if i < len(lines) - 1 or stale:  # a running game's last line may be half-written
                unreadable += 1
            continue
        if not isinstance(r, dict):
            continue
        if r.get("alert"):
            errors.append(r)
        elif r.get("kind") in ("moderator_flag", "player_feedback"):  # players and the moderator saw a problem
            errors.append({**r, "error": r.get("issue") or f"{r.get('player')}: {r.get('feedback')}"})
        elif r.get("kind") == "review":  # the post-game log review's serious findings
            errors += [{"t": r.get("t"), "kind": "review_issue", "id": f"{r.get('t')}:review_issue:{n}",
                        "error": f"{i.get('kind')}: {i.get('description')}"}
                       for n, i in enumerate(r.get("issues") or [])
                       if isinstance(i, dict) and i.get("severity") == "high"]
    kinds = Counter(str(r.get("kind")) for r in errors)
    samples: list[str] = []
    for kind in kinds:
        samples += [f"{kind}: {str(r.get('error'))[:300]}" for r in errors if r.get("kind") == kind][:SAMPLES_PER_KIND]
    ids = [r.get("id") or f"{r.get('t')}:{r.get('kind')}" for r in errors]
    stopped = not finished and not kinds["crash"] and stale
    if stopped:
        ids.append("stopped")
        samples.append("the log ends with no result and no crash record: the process was probably killed"
                       + (f"; continue it with: uv run mafia.py --resume {path.with_suffix('.ckpt')}"
                          if path.with_suffix(".ckpt").exists() else ""))
    if unreadable:
        kinds["unreadable log line"] = unreadable
        ids.append(f"unreadable:{unreadable}")
        samples.append(f"{unreadable} line(s) of the log aren't readable JSON")
    return {"game": path.stem, "path": str(path), "ids": ids, "kinds": dict(kinds), "finished": finished,
            "stopped": stopped, "samples": samples}


def load_json(path: Path) -> dict:
    """A small state file of ours; an unreadable one counts as empty (it is rebuilt)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_json(path: Path, data: dict) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")  # parallel games each write their own
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def game_logs(log_dir: Path, prefix: str) -> list[Path]:
    return sorted(p for p in log_dir.glob(f"{prefix}_*.jsonl") if re.match(rf"{prefix}_\d", p.name))


def unreviewed(log_dir: Path, prefix: str = "game") -> list[dict]:
    """Games (oldest first) with problems that weren't marked reviewed."""
    reviewed = load_json(log_dir / REVIEWED_FILE)
    out = []
    for path in game_logs(log_dir, prefix):
        g = scan(path)
        old = reviewed.get(g["game"])
        seen = set(old) if isinstance(old, list) else set()  # an old-format entry (a count) counts as nothing
        if any(i not in seen for i in g["ids"]):
            out.append(g)
    return out


def split_in_progress(log_dir: Path, games: list[dict]) -> tuple[list[dict], list[dict]]:
    """(new, in progress): a game is in progress when every problem it has was marked so (a new one
    since makes it new again). In-progress games get their "note"."""
    marked = load_json(log_dir / IN_PROGRESS_FILE)
    new, wip = [], []
    for g in games:
        m = marked.get(g["game"])
        if isinstance(m, dict) and set(g["ids"]) <= set(m.get("ids") or []):
            wip.append({**g, "note": str(m.get("note") or "")})
        else:
            new.append(g)
    return new, wip


def describe(games: list[dict], wip: list[dict] | None = None) -> str:
    lines = []
    if wip:
        lines.append("Still in progress (already raised with Kevin; don't report again, ack once resolved):")
        lines += [f"- {g['game']}: {g['note'] or '(no note)'}" for g in wip]
        if games:
            lines.append("New:")
    for g in games:
        kinds = Counter(g["kinds"])
        counts = ", ".join(f"{n} {k}" for k, n in kinds.most_common())
        state = "finished" if g["finished"] else "stopped" if g["stopped"] or kinds["crash"] else "running"
        path = Path(g["path"])
        lines.append(f"- {g['game']} ({state}): {counts or 'no error records'}. Details: {path.with_suffix('.html')}"
                     + (f" and {path.stem}_feedback.md" if g["finished"] else ""))
        lines += [f"    {s}" for s in g["samples"]]
    return "\n".join(lines)


def pending_line(log_dir: Path, prefix: str = "game") -> str | None:
    """One line for the end of a game when any game's errors are unreviewed, else None."""
    try:
        games = unreviewed(log_dir, prefix)
    except Exception as e:  # only a reminder: it must never break the end of a game
        return f"ALERT alerts_error: checking for unreviewed errors failed: {type(e).__name__}: {e}"
    games, _ = split_in_progress(log_dir, games)
    if not games:
        return None  # in-progress ones are already being handled
    return (f"Unreviewed errors in {len(games)} game{'s' if len(games) > 1 else ''}: see `uv run alerts.py"
            + (" --mock" if prefix == "mock" else "") + "`, then mark them reviewed with --ack.")


def ack(log_dir: Path, which: list[str], prefix: str = "game") -> list[str]:
    """Marks games' current problems reviewed ("all": every unreviewed game not in progress; name those
    to ack them). Returns their ids."""
    games = {g["game"]: g for g in unreviewed(log_dir, prefix)}
    names = [g["game"] for g in split_in_progress(log_dir, list(games.values()))[0]] if which == ["all"] else which
    reviewed = load_json(log_dir / REVIEWED_FILE)
    for name in names:
        path = log_dir / f"{name}.jsonl"
        g = games.get(name) or (scan(path) if path.exists() else None)
        if g is None:
            raise SystemExit(f"no game log {path}")
        reviewed[name] = sorted(set(g["ids"]))
    save_json(log_dir / REVIEWED_FILE, reviewed)
    marked = load_json(log_dir / IN_PROGRESS_FILE)
    if any([marked.pop(name, None) is not None for name in names]):
        save_json(log_dir / IN_PROGRESS_FILE, marked)
    return names


def mark_in_progress(log_dir: Path, which: list[str], note: str, prefix: str = "game") -> list[str]:
    """Marks games' current problems in progress, with a note on what's pending ("all": every unreviewed game)."""
    games = {g["game"]: g for g in unreviewed(log_dir, prefix)}
    names = list(games) if which == ["all"] else which
    marked = load_json(log_dir / IN_PROGRESS_FILE)
    for name in names:
        if name not in games:
            raise SystemExit(f"{name} has no unreviewed problems")
        marked[name] = {"ids": sorted(set(games[name]["ids"])), "note": note}
    save_json(log_dir / IN_PROGRESS_FILE, marked)
    return names


HOOK_INTRO = ("mafia1 games have errors or problem reports nobody has reviewed yet (from alerts.py: errors are "
              "logged with alert: true; moderator_flag, player_feedback and high-severity review_issue entries are "
              "problems the moderator, players or the post-game log review noticed; all are in the game's feedback "
              "report). Before anything else in your first reply, tell Kevin about them in a few lines: which games, "
              "which kinds, and what probably caused them (read the logs if that's quick). New kinds matter most; "
              "a report that points at a real bug (e.g. a player seeing information they shouldn't) is worth "
              "checking in the code and fixing. "
              "Ack what's fully handled (fixed, settled, or noise) yourself with `uv run alerts.py --ack GAME ...` and "
              "say so; mark what's still under discussion with `--wip GAME ... --note \"what's pending\"`.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ack", nargs="+", metavar="GAME", help="mark these games (or all) reviewed")
    ap.add_argument("--wip", nargs="+", metavar="GAME", help="mark these games (or all) in progress")
    ap.add_argument("--note", default="", help="with --wip: what's pending")
    ap.add_argument("--hook", action="store_true", help="print only when something is unreviewed, for Claude")
    ap.add_argument("--mock", action="store_true", help="mock games (logs/mock_*) instead of real ones")
    ap.add_argument("--logs", type=Path, default=LOG_DIR, help="the logs folder")
    args = ap.parse_args()
    prefix = "mock" if args.mock else "game"
    if not args.logs.is_dir():
        if not args.hook:
            print(f"No logs folder at {args.logs}.")
        return
    try:
        if args.ack:
            names = ack(args.logs, args.ack, prefix)
            print(f"Marked reviewed: {', '.join(names) or 'nothing (no unreviewed errors)'}")
            return
        if args.wip:
            names = mark_in_progress(args.logs, args.wip, args.note, prefix)
            print(f"Marked in progress: {', '.join(names) or 'nothing (no unreviewed errors)'}")
            return
        new, wip = split_in_progress(args.logs, unreviewed(args.logs, prefix))
    except Exception as e:  # the hook must say so, not fail with a traceback Claude never sees
        safe_print(f"alerts.py could not check the logs for errors: {type(e).__name__}: {e}")
        raise SystemExit(0 if args.hook else 1) from None
    if args.hook:
        if new:
            safe_print(HOOK_INTRO + "\n\n" + describe(new, wip))
        elif wip:
            safe_print("mafia1 alerts still in progress; bring them up only if relevant, and ack each with "
                       "`uv run alerts.py --ack GAME` once it's resolved.\n\n" + describe([], wip))
        return
    safe_print(describe(new, wip) if new or wip else "No unreviewed errors.")


if __name__ == "__main__":
    main()
