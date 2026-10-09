"""Errors from games that nobody has reviewed yet, so they get looked at without anyone reading logs.

Every error a game runs into is logged with alert: true (GameLog.error). This lists the games in logs/
whose errors haven't been marked reviewed, plus games that stopped with no result and no crash record
(the process was killed). Claude Code runs `--hook` when a session starts in this folder
(.claude/settings.json), so Claude sees new errors and brings them up; a finished game also prints a
reminder line while any are unreviewed. Reviewed games are kept in logs/alerts_reviewed.json; a game
that gets new errors later (e.g. it was resumed) shows up again.

Usage:
    uv run alerts.py                 # list games with unreviewed errors
    uv run alerts.py --ack all       # mark them all reviewed (or give game ids, e.g. game_20261009_004910_895267)
    uv run alerts.py --hook          # for the SessionStart hook: prints nothing when everything is reviewed
    uv run alerts.py --mock          # the same for mock games
"""

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "logs"
REVIEWED_FILE = "alerts_reviewed.json"
STOPPED_AFTER_S = 3600  # a log with no result, untouched this long, belongs to a game that was killed
SAMPLES_PER_KIND = 2


def scan(path: Path) -> dict | None:
    """A game log's problems: error counts per kind and a few samples, and whether it stopped silently.
    None if it has none (or is still running without errors)."""
    data = path.read_bytes()
    finished = b'"kind": "result"' in data
    if b'"alert": true' not in data and (finished or time.time() - path.stat().st_mtime < STOPPED_AFTER_S):
        return None
    errors = [json.loads(line) for line in data.splitlines() if b'"alert": true' in line]
    errors = [r for r in errors if r.get("alert")]
    kinds = Counter(r["kind"] for r in errors)
    samples: list[str] = []
    for kind in kinds:
        samples += [f"{kind}: {r['error'][:300]}" for r in errors if r["kind"] == kind][:SAMPLES_PER_KIND]
    stopped = not finished and not kinds["crash"] and time.time() - path.stat().st_mtime >= STOPPED_AFTER_S
    if stopped:
        samples.append("the log ends with no result and no crash record: the process was probably killed"
                       + (f"; continue it with: uv run mafia.py --resume {path.with_suffix('.ckpt')}"
                          if path.with_suffix(".ckpt").exists() else ""))
    return {"game": path.stem, "path": path, "issues": len(errors) + stopped, "kinds": kinds,
            "finished": finished, "stopped": stopped, "samples": samples}


def reviewed_path(log_dir: Path) -> Path:
    return log_dir / REVIEWED_FILE


def load_reviewed(log_dir: Path) -> dict[str, int]:
    """Game id -> how many issues it had when it was marked reviewed."""
    p = reviewed_path(log_dir)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def unreviewed(log_dir: Path, prefix: str = "game") -> list[dict]:
    """Games (oldest first) with more issues than when they were last marked reviewed."""
    reviewed = load_reviewed(log_dir)
    out = []
    for path in sorted(log_dir.glob(f"{prefix}_*.jsonl")):
        if (s := scan(path)) and s["issues"] > reviewed.get(s["game"], 0):
            out.append(s)
    return out


def describe(games: list[dict]) -> str:
    lines = []
    for g in games:
        counts = ", ".join(f"{n} {k}" for k, n in g["kinds"].most_common())
        state = "finished" if g["finished"] else "stopped" if g["stopped"] or g["kinds"]["crash"] else "running"
        lines.append(f"- {g['game']} ({state}): {counts or 'no error records'}. "
                     f"Details: {g['path'].with_suffix('.html')}"
                     + (f" and {g['path'].stem}_feedback.md" if g["finished"] else ""))
        lines += [f"    {s}" for s in g["samples"]]
    return "\n".join(lines)


def pending_line(log_dir: Path, prefix: str = "game") -> str | None:
    """One line for the end of a game when any game's errors are unreviewed, else None."""
    try:
        games = unreviewed(log_dir, prefix)
    except Exception as e:  # only a reminder: it must never break the end of a game
        return f"ALERT alerts_error: checking for unreviewed errors failed: {type(e).__name__}: {e}"
    if not games:
        return None
    return (f"Unreviewed errors in {len(games)} game{'s' if len(games) > 1 else ''}: see `uv run alerts.py`"
            + (" --mock" if prefix == "mock" else "") + ", then mark them reviewed with --ack.")


def ack(log_dir: Path, which: list[str], prefix: str = "game") -> list[str]:
    """Marks games reviewed at their current issue count ("all": every unreviewed one). Returns their ids."""
    games = {g["game"]: g for g in unreviewed(log_dir, prefix)}
    names = list(games) if which == ["all"] else which
    reviewed = load_reviewed(log_dir)
    for name in names:
        path = log_dir / f"{name}.jsonl"
        g = games.get(name) or (scan(path) if path.exists() else None)
        if g is None:
            raise SystemExit(f"no game log {log_dir / name}.jsonl with errors")
        reviewed[name] = g["issues"]
    tmp = reviewed_path(log_dir).with_suffix(".tmp")
    tmp.write_text(json.dumps(reviewed, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, reviewed_path(log_dir))
    return names


HOOK_INTRO = ("mafia1 games have errors nobody has reviewed yet (from alerts.py; each is logged with alert: true "
              "in the game's JSONL, at the top of its HTML view and feedback report). Before anything else in "
              "your first reply, tell Kevin about them in a few lines: which games, which kinds of errors, and "
              "what probably caused them (read the logs if that's quick). New kinds of errors matter most. "
              "Once he has seen them, mark them reviewed with `uv run alerts.py --ack all` (or the game ids).")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ack", nargs="+", metavar="GAME", help="mark these games (or all) reviewed")
    ap.add_argument("--hook", action="store_true", help="print only when something is unreviewed, for Claude")
    ap.add_argument("--mock", action="store_true", help="mock games (logs/mock_*) instead of real ones")
    ap.add_argument("--logs", type=Path, default=LOG_DIR, help="the logs folder")
    args = ap.parse_args()
    prefix = "mock" if args.mock else "game"
    if not args.logs.is_dir():
        if not args.hook:
            print(f"No logs folder at {args.logs}.")
        return
    if args.ack:
        names = ack(args.logs, args.ack, prefix)
        print(f"Marked reviewed: {', '.join(names) or 'nothing (no unreviewed errors)'}")
        return
    try:
        games = unreviewed(args.logs, prefix)
    except Exception as e:
        print(f"alerts.py could not check the logs for errors: {type(e).__name__}: {e}")
        sys.exit(0 if args.hook else 1)
    if args.hook:
        if games:
            print(HOOK_INTRO + "\n\n" + describe(games))
        return
    print(describe(games) if games else "No unreviewed errors.")


if __name__ == "__main__":
    main()
