"""Small I/O helpers every tool shares: reading game logs (JSONL) that may end in a half-written line,
e.g. a game killed mid-write, and printing text from models to any console."""

import json
import sys
from pathlib import Path


def safe_print(text: str) -> None:
    """print() that can't fail on the text: a Windows console or pipe (cp1252) can't encode many characters
    models write, and no console can encode a lone surrogate. Those become escapes instead."""
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(encoding, "backslashreplace").decode(encoding, "replace"), flush=True)


def read_records(path: Path) -> tuple[list[dict], int]:
    """The log's records, and how many lines weren't readable JSON objects (skipped, for the caller to
    report)."""
    records, unreadable = [], 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            unreadable += 1
            continue
        if isinstance(r, dict) and "kind" in r:
            records.append(r)
        else:
            unreadable += 1
    return records, unreadable
