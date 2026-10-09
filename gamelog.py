"""The game log: JSONL for analysis, plus live .txt and an .html view."""

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import log_viewer


# Bump when a record's fields change in a way analysis code has to handle (written in "setup").
# 2: setup has git_commit, git_dirty, rules_sha256, settings; "vote" records
# 3: setup has game_id; result has end_reason, winning_faction, duration_s, players (per-player outcome);
#    night_check has alive and roles_in_play
# 4: death records (and result players' death) have killer, killer_role, katana
# 5: setup players have effort; settings.models is a list of {model, effort}, plus moderator_effort
# 6: "strategy_review" records (moderator model's lessons with evidence); lessons.jsonl lines have source
# 7: "resume" records (the game continued from a checkpoint; see checkpoint.py)
# 8: error records (GameLog.error) have alert=true and an "error" summary; new kinds player_fallback,
#    api_retry, moderator_tool_error, night_check_error, feedback_error, crash; result has errors
LOG_VERSION = 8

ALERT_LINES_PER_SOURCE = 3  # ALERT lines printed per (kind, player); the rest are only logged and counted


class GameLog:
    """Writes every event and LLM call as one JSON line, for later analysis, plus a live
    human-readable .txt next to it. close() also renders an expandable .html view.
    Safe to call from several threads (players are asked in parallel)."""

    def __init__(self, path: Path, resume_at: tuple[int, int] | None = None):
        """resume_at: offsets() of an existing log, which is cut back to them and continued (checkpoint.py)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.cut_records: list[dict] = []  # JSONL records that resume_at cut off
        if resume_at is not None:
            for p, offset in zip((path, path.with_suffix(".txt")), resume_at):
                with p.open("r+b") as fh:
                    fh.seek(offset)
                    tail = fh.read().decode("utf-8", "replace")
                    fh.truncate(offset)
                if p == path:
                    self.cut_records = [json.loads(line) for line in tail.splitlines() if line.strip()]
        self.error_counts: dict[str, int] = {}  # per error kind, for the result record
        self.alerts_printed: dict[tuple[str, str], int] = {}
        mode = "w" if resume_at is None else "a"
        self.f = path.open(mode, encoding="utf-8")
        self.txt = path.with_suffix(".txt").open(mode, encoding="utf-8")
        self.lock = threading.Lock()

    def offsets(self) -> tuple[int, int]:
        """Byte sizes of the JSONL and .txt so far, for a checkpoint to cut the log back to."""
        with self.lock:
            self.f.flush()
            self.txt.flush()
            return os.fstat(self.f.fileno()).st_size, os.fstat(self.txt.fileno()).st_size

    def error(self, kind: str, error: str, **data: Any) -> None:
        """Something went wrong that someone should fix. Logged with alert=true, counted in the result
        record and listed at the top of the feedback report, and printed as an "ALERT" line, which
        whoever runs the game watches for (the first few per kind and player)."""
        source = (kind, str(data.get("player", "")))
        with self.lock:
            self.error_counts[kind] = self.error_counts.get(kind, 0) + 1
            printed = self.alerts_printed[source] = self.alerts_printed.get(source, 0) + 1
        self.write(kind, alert=True, error=error, **data)
        if printed <= ALERT_LINES_PER_SOURCE:
            more = " (further ones like this are only logged)" if printed == ALERT_LINES_PER_SOURCE else ""
            print(f"ALERT {kind}: {error[:400]}{more}", flush=True)  # the log has the whole error

    def write_raw(self, record: dict) -> None:
        """Writes a record as it is (keeping its time), e.g. one that resuming cut off but keeps."""
        self.write(record["kind"], **{k: v for k, v in record.items() if k != "kind"})

    def write(self, kind: str, **data: Any) -> None:
        line = json.dumps({"t": time.time(), "kind": kind, **data}, default=str)
        text = log_viewer.text_line(json.loads(line))
        with self.lock:
            self.f.write(line + "\n")
            self.f.flush()
            if text is not None:
                self.txt.write(text + "\n")
                self.txt.flush()

    def close(self) -> None:
        self.f.close()
        self.txt.close()
        log_viewer.render_html(self.path)
