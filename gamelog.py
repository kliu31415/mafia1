"""The game log: JSONL for analysis, plus live .txt and an .html view."""

import json
import os
import threading
import time
import traceback
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
# 9: player_call records have notepad_before and notepad_after (the notepad the player saw, and after
#    its answer; equal when the answer kept it)
# 10: result has usage (cost, calls and tokens per player, the moderator and each post-game step; see
#     usage_by_caller); night_check, review, strategy_review and the moderator's debrief have usage
# 11: "tips" record (the tips file given to some players: file, sha256, players, text); settings have tips
#     and tips_for; result players have tips (whether that player had them)
# 12: "tips" record has shown (the sections each player with tips saw); lessons records of players with tips,
#     and the strategy_review when anyone had tips, have tips_feedback (tip, verdict helped/hurt/wrong, why)
# 13: "tips" record: players, files (player -> tips file), sha256 and texts (per file), instead of one file,
#     sha256, text and shown; settings have player_tips ([who, file or null] pairs)
# 14: new error kinds checkpoint_error, viewer_error, tips_error (and moderator_error for an empty answer);
#     a resumed game keeps the crash record that stopped it, counted in the result's errors
# 15: player_error has output, reasoning, cost and usage when an answer arrived (and counts in usage); new
#     error kinds moderator_warning, api_error, harness_error, setup_error; player answers that break their
#     schema are player_errors
LOG_VERSION = 15

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
        """Renders the .html view (a failure is logged as an error, so the log keeps it), then closes."""
        try:
            log_viewer.render_html(self.path)
        except Exception as e:
            self.error("viewer_error", f"rendering the HTML view failed: {type(e).__name__}: {e}",
                       traceback=traceback.format_exc())
        self.f.close()
        self.txt.close()


# Who a model call's cost belongs to, for records that aren't a player's or the moderator's own call.
# These all run on the moderator's model.
CALLER_BY_KIND = {"moderator_call": "Moderator", "night_check": "Night checks", "review": "Log review",
                  "strategy_review": "Strategy review"}
TOKEN_FIELDS = ["prompt_tokens", "cached_tokens", "completion_tokens", "reasoning_tokens"]


def caller_of(record: dict) -> str | None:
    """Whose call a record is: a player's name, "Moderator", a post-game step, or None (not a call)."""
    if record["kind"] == "player_call" or (record["kind"] == "player_error" and "cost" in record):
        return record["player"]  # a failed answer that was paid for counts too
    if record["kind"] == "debrief" and record.get("who") == "moderator":
        return "Moderator"
    return CALLER_BY_KIND.get(record["kind"]) if "cost" in record else None


def usage_by_caller(path: Path, players: list[dict]) -> list[dict]:
    """Cost, calls and tokens of each player (in seat order), the moderator, and each post-game step
    that made calls, read from a log's records so far. players: {name, model, role} per player.
    A player's failed calls (player_error; a failed answer that was paid for is also in calls and cost) and
    fallback answers (player_fallback) are counted too."""
    rows: dict[str, dict] = {p["name"]: {"who": p["name"], "kind": "player", "role": p.get("role"),
                                         "models": [p["model"]]} for p in players}
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["kind"] in ("player_error", "player_fallback") and r.get("player") in rows:
            key = "failed_calls" if r["kind"] == "player_error" else "fallbacks"
            rows[r["player"]][key] = rows[r["player"]].get(key, 0) + 1
        who = caller_of(r)
        if who is None:
            continue
        row = rows.setdefault(who, {"who": who, "kind": "moderator" if who == "Moderator" else "post_game",
                                    "models": []})
        model = r.get("model") or r.get("judge")
        if model and model not in row["models"]:
            row["models"].append(model)
        row["calls"] = row.get("calls", 0) + 1
        row["cost"] = row.get("cost", 0.0) + float(r.get("cost") or 0)
        usage = r.get("usage") or {}
        tokens = {"prompt_tokens": usage.get("prompt_tokens"),
                  "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
                  "completion_tokens": usage.get("completion_tokens"),
                  "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")}
        for k, v in tokens.items():
            row[k] = row.get(k, 0) + int(v or 0)
    out = []
    for row in rows.values():
        row.setdefault("calls", 0)
        row["cost"] = round(row.get("cost", 0.0), 6)
        for k in TOKEN_FIELDS:
            row.setdefault(k, 0)
        if row["kind"] == "player":
            row.setdefault("failed_calls", 0)
            row.setdefault("fallbacks", 0)
        out.append(row)
    return out
