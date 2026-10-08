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
LOG_VERSION = 7


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
