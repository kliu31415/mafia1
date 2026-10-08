"""The game log: JSONL for analysis, plus live .txt and an .html view."""

import json
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
LOG_VERSION = 4


class GameLog:
    """Writes every event and LLM call as one JSON line, for later analysis, plus a live
    human-readable .txt next to it. close() also renders an expandable .html view.
    Safe to call from several threads (players are asked in parallel)."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.f = path.open("w", encoding="utf-8")
        self.txt = path.with_suffix(".txt").open("w", encoding="utf-8")
        self.lock = threading.Lock()

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
