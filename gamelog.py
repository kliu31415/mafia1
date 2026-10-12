"""The game log: JSONL for analysis, plus live .txt and an .html view."""

import json
import os
import threading
import time
import traceback
from pathlib import Path
from typing import Any

import log_viewer
from records import read_records, safe_print


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
# 16: settings have setup: {"kind": "fixed"}, or {"kind": "random", "players", "pool"} for --roles random:N
# 17: "resume" has cut_cost (cost of the calls cut from the log, still in the result's cost) and
#     unreadable_lines; a resumed game keeps earlier nights' night_check records; "night_effects_undone" record
#     (a revenge kill reverted a night's will forgery or cleaning); new error kind log_error (unreadable log lines)
# 18: "katana" has revote_targets (Yakuza -> target in the revote, or null when there was none)
# 19: "tips_update" record after the result (model, cost of updating the tips; not in the result's cost)
# 20: trial "vote" records have weights (voter -> votes counted, only voters counted more than once; Ballot Stuffer)
# 21: "claim" record (day, player, claim) when a player's public claim changes
# 22: setup settings.moderator_fallback; "moderator_switch" error record (day, phase, old, new, reason); a BYOK
#     call's cost includes what the provider billed (upstream_inference_cost)
# 23: player answers have no "thoughts" field (any model): written-out reasoning looks like distillation to
#     Anthropic's filter, which blocked Opus calls in game_20261009_084630_739772; see "reasoning" instead
# 24: player_call outputs have "reason", a sentence or a few on why the player chose that answer (players.REASON_NOTE)
# 25: claims are "event" records with cat "claim" (fields speaker, claim), shown in players' history, instead of
#     "claim" records
# 26: "section" records (title) before each post-game step, so log views show them as named sections
# 27: chat and pm events a Puppeteer wrote have a "puppeteer" field; night_actions include automatic actions
#     (the Ex-Con's random visit), marked "automatic": true
# 28: player_call, player_error and player_fallback have step (players.STEPS), day, phase and round (chat turns and
#     Yakuza chat); player_call, player_error and moderator_call have latency_s (seconds the call took, retries
#     included); moderator_call has day and phase; "resume" has at ("day" or "night": the checkpoint's phase)
# 29: player_feedback has step (players.STEPS), so answers to post-game questions aren't read as in-game reports
# 30: "katana" result has moved_from (the previous holder) when the Katana changed hands that night
# 31: death records (and result players' death) have killers and killer_roles: every attacker whose attack was
#     fatal (killer/killer_role are the first); the kill op's `by` may be a list
# 32: player_call has effort when it differs from the player's own: a retry after an answer cut off at max_tokens
#     uses one step lower (llm.lower_effort)
# 33: "visits" records (day, visits: [visitor, target] pairs) from the moderator's record_visits, one per night
# 34: "left" records (player, day, phase) when a player leaves the game without dying (a winning Executioner)
# 35: "effort_fallback" alert records (player, model, from_effort, to_effort, step, day, phase, round) when a
#     player's answer was cut off at max_tokens and the retry uses one effort step lower; result usage rows of
#     players have effort_fallbacks (how many)
# 36: games start with Night 1 (no Day 1, rules R1): day 1 has only the opening wills and Night 1
# 37: setup settings carry the rule settings (variants.py: flips, trial_votes, nomination_votes; older logs mean
#     variants.LEGACY), and the defaults hide flips and votes: secret votes' public events give only totals, each
#     voter gets a "notice" with their own vote, and "vote" records still list every vote
# 38: "vote" records have secret (players saw only the totals); the .txt view then lists the votes
# 39: trial "vote" records have reversed (voters whose vote a Fixer reversed; votes holds the counted votes)
# 40: settings.setup has name (random setups); players are told how roles were chosen (setups.setup_note)
# 41: settings has script (scripts.py: the roles the game could use, and the only ones in its rules text; older
#     logs mean "all")
# 42: "briefing" record after setup (and tips): rules (the full rules text every prompt starts with, which
#     rules_sha256 hashes), setup_note (what players were told about the setup) and players (each player's
#     opening role briefing); "moderator_prompt" records (day, phase, instructions, state_summary, full_state):
#     what the moderator was told at the start of each phase it ran
# 43: "attacks" records (day, attackers): the attacker of each Attack that night, from the moderator's attacks op
#     (games with a Bloodhound)
# 46: settings has fix_nights (--fix-nights: night checks run before dawn and high-severity findings go back to
#     the moderator); "night_fix" records (night, issues, transcript): what the moderator did about them
# 47: setup and result players have via: how the model's calls ran (api, claude_code: --claude-code, or mock)
# 48: setup players have traits (traits.py, rules R24); settings has traits (the traits dealt); "martyr" records
#     (player, guilty, day) when a Martyr is hanged
# 49: night_actions may have trait_actions ([{trait, target}], e.g. Armed's shot), and a player asked only for one
#     has no act; settings traits may bundle several for one player ("Martyr+Armed")
# 50: "avenger" records (player, killed, day) when an Avenger's vengeance kills an attacker
# 51: setup has role_info (every script role and role in play: alignment, category, summary, rules paragraph) and
#     trait_info (every trait: alignments, summary, hover), so a log reads the same after roles change; the Cardinal
#     role became the Cursed trait (roles.RETIRED), and "cardinal" records became "curse" (victim, cursed)
# 52: "day_shot" records (player, target, attack, day) when a Sniper's held shot fires (rules R25), and
#     "day_action_refused" (player, target, tokens) for a day action with a bad token count
# 53: "day_shot_taken" records (player, target, attack, delay: speaking turns until it fires, rules R25) and
#     "day_shot_dropped" records (player, target) when a held shot's shooter died first
# 54: "kitsune_charm" (player, target, attacks, swallowed, day) and "kitsune_release" (player, target, attack, cause,
#     day) records for the Kitsune
# 55: "trap" records (trapper, target, attacks, stopped, day) when a trap meets attacks: from now on a trap stops one
#     attack and hits its attacker back if it was a visit (before, it hit the first non-Village visitor)
LOG_VERSION = 55

ALERT_LINES_PER_SOURCE = 3  # ALERT lines printed per (kind, player); the rest are only logged and counted


class GameLog:
    """Writes every event and LLM call as one JSON line, for later analysis, plus a live
    human-readable .txt next to it. close() also renders an expandable .html view.
    Safe to call from several threads (players are asked in parallel)."""

    def __init__(self, path: Path, resume_at: tuple[int, int] | None = None, exclusive: bool = False):
        """resume_at: offsets() of an existing log, which is cut back to them and continued (checkpoint.py).
        exclusive: raise FileExistsError rather than overwrite an existing log."""
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.cut_records: list[dict] = []  # JSONL records that resume_at cut off
        self.cut_unreadable = 0  # lines among them that weren't JSON (e.g. half-written when the game stopped)
        if resume_at is not None:
            for p, offset in zip((path, path.with_suffix(".txt")), resume_at):
                with p.open("r+b") as fh:
                    fh.seek(offset)
                    tail = fh.read().decode("utf-8", "replace")
                    if p == path:  # read before cutting, so a bad line can't lose the rest
                        for line in tail.splitlines():
                            try:
                                if line.strip():
                                    self.cut_records.append(json.loads(line))
                            except json.JSONDecodeError:
                                self.cut_unreadable += 1
                    fh.truncate(offset)
        self.error_counts: dict[str, int] = {}  # per error kind, for the result record
        self.alerts_printed: dict[tuple[str, str], int] = {}
        mode = "a" if resume_at is not None else "x" if exclusive else "w"
        self.f = path.open(mode, encoding="utf-8")
        # errors="replace": e.g. a lone surrogate in a model's text can't be encoded
        self.txt = path.with_suffix(".txt").open("w" if mode == "x" else mode, encoding="utf-8", errors="replace")
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
            safe_print(f"ALERT {kind}: {error[:400]}{more}")  # the log has the whole error

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


# Record kind -> the key of a player's usage row that counts them.
COUNTED_PER_PLAYER = {"player_error": "failed_calls", "player_fallback": "fallbacks",
                      "effort_fallback": "effort_fallbacks"}


def usage_by_caller(path: Path, players: list[dict]) -> list[dict]:
    """Cost, calls and tokens of each player (in seat order), the moderator, and each post-game step
    that made calls, read from a log's records so far. players: {name, model, role} per player.
    A player's failed calls (player_error; a failed answer that was paid for is also in calls and cost) and
    fallback answers (player_fallback) and retries at a lower effort (effort_fallback) are counted too."""
    rows: dict[str, dict] = {p["name"]: {"who": p["name"], "kind": "player", "role": p.get("role"),
                                         "models": [p["model"]]} for p in players}
    for r in read_records(path)[0]:
        if r["kind"] in COUNTED_PER_PLAYER and r.get("player") in rows:
            key = COUNTED_PER_PLAYER[r["kind"]]
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
            for key in COUNTED_PER_PLAYER.values():
                row.setdefault(key, 0)
        out.append(row)
    return out
