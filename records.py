"""Small I/O helpers every tool shares: reading game logs (JSONL) that may end in a half-written line,
e.g. a game killed mid-write, printing text from models to any console, whose call a record is, and keeping
secrets out of logs."""

import functools
import json
import os
import re
import sys
from pathlib import Path

# Logs get shared (Kevin, Oct 12 2026: HTML logs sent to friends), so no secret may reach one. redact() runs on
# every line GameLog writes and on every log read_records reads (so old logs render clean too).
SECRET_ENV_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSW|CREDENTIAL|AUTH", re.I)
SECRET_PATTERN = re.compile(r"\b(?:sk-(?:or|ant|proj)-[A-Za-z0-9_-]{8,}|sk-[A-Za-z0-9]{32,}|gh[pousr]_[A-Za-z0-9]{20,}"
                            r"|github_pat_[A-Za-z0-9_]{20,}|AIza[0-9A-Za-z_-]{30,}|xox[abpr]-[A-Za-z0-9-]{10,})"
                            r"|Bearer [A-Za-z0-9._~+/=-]{20,}")
# Email addresses too: the Claude Code CLI puts the signed-in account's email in Claude seats' context
# (claude_code.CLI_NOTE), and a model may repeat it.
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")


@functools.cache
def secret_values() -> tuple[str, ...]:
    """Values of environment variables named like secrets (OPENROUTER_API_KEY, GITHUB_TOKEN, ...)."""
    values = {v for k, v in os.environ.items()
              if SECRET_ENV_NAME.search(k) and len(v) >= 16 and not re.search(r"\s", v)}
    return tuple(sorted(values, key=len, reverse=True))


@functools.cache
def home_dirs() -> tuple[str, ...]:
    """The home folder (it names the user), as written, as JSON writes it (Windows backslashes doubled) and with
    forward slashes (as git and some tools print a Windows path)."""
    home = str(Path.home())
    return tuple(dict.fromkeys((json.dumps(home)[1:-1], home, Path.home().as_posix()))) if len(home) > 5 else ()


def redact(text: str) -> str:
    """text with secrets, email addresses and the home folder's path (as "~") taken out."""
    for value in secret_values():
        text = text.replace(value, "[redacted secret]")
    text = SECRET_PATTERN.sub("[redacted secret]", text)
    if "@" in text:
        text = EMAIL.sub("[redacted email]", text)
    for home in home_dirs():
        text = text.replace(home, "~")
    return text


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
    for line in redact(path.read_text(encoding="utf-8", errors="replace")).splitlines():
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


# Who a model call's cost belongs to, for records that aren't a player's or the moderator's own call.
# These all run on the moderator's model.
CALLER_BY_KIND = {"moderator_call": "Moderator", "night_check": "Night checks", "review": "Log review",
                  "strategy_review": "Strategy review"}


def caller_of(record: dict) -> str | None:
    """Whose call a record is: a player's name, "Moderator", a post-game step, or None (not a call)."""
    if record["kind"] == "player_call" or (record["kind"] == "player_error" and "cost" in record):
        return record["player"]  # a failed answer that was paid for counts too
    if record["kind"] == "debrief" and record.get("who") == "moderator":
        return "Moderator"
    return CALLER_BY_KIND.get(record["kind"]) if "cost" in record else None
