"""Scaffolding for LLM-played games of the Mafia variant in rules_1.txt.

Design: code owns the game state, the RNG and who can see which message. Day phases (chat,
nominations, votes) run in code. Night actions are collected from players as structured output,
then an LLM moderator resolves them through tools (get_state, apply_changes, random_choice, tell,
ask_player, end_phase), since the role interactions are too varied to hand-code yet.

All LLM calls go through OpenRouter. The API key is read from the OPENROUTER_API_KEY
environment variable.

Code layout:
    mafia.py       entry point: game loop and CLI
    llm.py         OpenRouter client, model list, offline mock client
    roles/         role definitions, the default setup, and per-role hooks (roles/base.py)
    events.py      event categories for game.emit()
    state.py       game state, events with visibility, deaths, win checks
    players.py     player prompts, output schemas, notepads
    day.py         speaking budget, chat turns, nominations, votes
    night.py       Yakuza chat, night actions, Katana vote
    moderator.py   LLM moderator and its tools
    gamelog.py     JSONL log plus live .txt; log_viewer.py renders .txt/.html
    records.py     lenient JSONL reading (skips damaged lines) and console-safe printing
    checkpoint.py  saves the game each day so a stopped game can continue (--resume)
    feedback.py    debriefs, log review, lessons, strategy review and the rules quiz
    tips.py        distills lessons from past games into a tips file; --tips gives it to players
    setups.py      random setups (--roles random:N), for role strength across many role mixes
    stats.py       cross-game statistics: win rates by faction, role and model, per-decision skill
    night_check.py a judge model checks each night's moderator resolution (--check-nights)
    alerts.py      lists games whose errors nobody has reviewed yet (Claude Code runs it at session start)
    sync_logs.py   moves logs from cloud games to the PC (and the tips sheet back) through the `logs` branch
    role_summaries.py checks each role's one-line hover summary against its paragraph in rules_1.txt
    tests/         offline scenario and hidden-information tests (uv run pytest)

Usage:
    uv run pytest                                            # offline tests
    uv run mafia.py --mock                                   # offline run, no API calls
    uv run mafia.py --list-roles                             # which roles are implemented
    uv run mafia.py --players haiku-5.5,gpt-6-luna --moderator haiku-5.5
    uv run mafia.py --players opus-5.5:high,haiku-5.5:low --moderator opus-5.5:medium
    uv run mafia.py --resume logs/<game>.ckpt                # continue a game that stopped
    uv run tips.py build                                     # tips file from past games' lessons
    uv run alerts.py                                         # games with errors nobody has reviewed yet
    uv run mafia.py --tips tips/tips.md --tips-for half      # half the seats play with those tips
    uv run mafia.py --roles random:8                         # a random 8-player setup
    uv run stats.py                                          # win rates and decision skill across logs/
    uv run sync_logs.py pull                                 # cloud games' logs into logs/ (see sync_logs.py)
"""

import argparse
import hashlib
import random
import subprocess
import time
import traceback
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import alerts
import sync_logs
from day import run_day
from checkpoint import load as load_checkpoint, save as save_checkpoint
from feedback import run_debrief, run_lessons, run_quiz, run_review, run_strategy_review, write_report
from gamelog import GameLog, usage_by_caller
from log_viewer import render_html, usage_lines
from llm import (EFFORTS, LLMClient, MockClient, Model, ModelSpec, OpenRouterClient, default_effort,
                 load_api_key, parse_model_spec)
from moderator import Moderator
from night_check import NightChecker
from night import run_night
from players import Players
from roles import DEFAULT_SETUP, ROLES, Status, role_status_table
from setups import POOLS, parse_random_roles, random_setup
from events import PHASE
from records import read_records
from state import PLAYER_NAMES, Game, setup_game
from tips import assign_tips, build as build_tips, file_digest, parse_player_tips, print_alert

ROOT = Path(__file__).resolve().parent
RULES_PATH = ROOT / "rules_1.txt"
LOG_DIR = ROOT / "logs"
DEFAULT_TIPS = ROOT / "tips" / "tips.md"  # the players' sheet --update-tips keeps up to date after each game
MOCK_TIPS = LOG_DIR / "mock_tips" / "tips.md"  # mock games' random lessons stay out of the real notebook
# The moderator's replacement if a content filter keeps blocking it (moderator.FILTER_BLOCKS_BEFORE_SWITCH).
DEFAULT_MODERATOR_FALLBACK = ModelSpec(Model.GPT_6_1_SOL, default_effort(Model.GPT_6_1_SOL))


# Safeguard against games that never end (not a rule from rules_1.txt): by default a game stops
# after (number of players + EXTRA_DAYS) days, with no winner. Override with --max-days.
EXTRA_DAYS = 10
STALL_LIMIT = 6  # rules R14: everyone loses after three nights and three days with no deaths


def game_meta(rules: str, settings: dict) -> dict:
    """What a game ran with, for comparing games across code and rules versions: the git commit
    (and whether there were uncommitted changes), a hash of the rules text, and the settings."""
    def git(*args: str) -> str | None:
        try:
            out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10)
            return out.stdout.strip() if out.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None
    status = git("status", "--porcelain", "--untracked-files=no")
    return {"git_commit": git("rev-parse", "HEAD"), "git_dirty": bool(status) if status is not None else None,
            "rules_sha256": hashlib.sha256(rules.encode("utf-8")).hexdigest()[:16], "settings": settings}


def play_game(client: LLMClient, models: Sequence[Model | ModelSpec], moderator_model: Model | ModelSpec,
              roles: list[str],
              seed: int | None, debrief: bool = False, flag_issues: bool = False,
              feedback_field: bool = False, review: bool = False, lessons: bool = False,
              max_days: int | None = None, check_nights: bool = False, checkpoint: bool = True,
              resume: dict | None = None, tips: Path | None = None, tips_for: str = "all",
              player_tips: list[tuple[str, Path | None]] | None = None, update_tips: Path | None = None,
              setup: dict | None = None, moderator_fallback: ModelSpec | None = DEFAULT_MODERATOR_FALLBACK) -> Path:
    """checkpoint: save the game at the start of each day to logs/<game>.ckpt (deleted when the game
    finishes). resume: a loaded checkpoint (checkpoint.load) to continue instead of starting a game.
    tips: a tips file (tips.py) put into the system prompt of the players tips_for picks (see
    tips.choose_players); player_tips then sets (or, with None, removes) each named player's or model's
    tips file. Resumed games keep the tips they started with. update_tips: a tips sheet whose notebook
    to update with this game's lessons afterwards (tips.build), rewriting the sheet. setup: how roles
    was chosen, for the log (default {"kind": "fixed"}; setups.py makes {"kind": "random", "pool": ...})."""
    play_args = {"models": models, "moderator_model": moderator_model, "roles": roles, "seed": seed,
                 "debrief": debrief, "flag_issues": flag_issues, "feedback_field": feedback_field,
                 "review": review, "lessons": lessons, "max_days": max_days, "check_nights": check_nights,
                 "tips": tips, "tips_for": tips_for, "player_tips": player_tips,
                 "update_tips": update_tips, "setup": setup, "moderator_fallback": moderator_fallback}
    mod = moderator_model if isinstance(moderator_model, ModelSpec) else ModelSpec(moderator_model)
    specs = [m if isinstance(m, ModelSpec) else ModelSpec(m) for m in models]
    rules = RULES_PATH.read_text(encoding="utf-8")
    max_days = max_days if max_days is not None else len(roles) + EXTRA_DAYS
    if resume:
        log = GameLog(resume["log_path"], resume_at=resume["log_offsets"])
    else:
        prefix = "mock" if isinstance(client, MockClient) else "game"  # mock games say random filler text
        log = new_log(prefix, seed)
    ckpt_path = log.path.with_suffix(".ckpt")
    stage = "while setting it up"  # for the crash record
    try:
        if resume:
            game = resume["game"]
            game.log = log
            resume_log(game, log, resume, client, check_nights)
            started = time.time() - resume["elapsed_s"]
        else:
            rng = random.Random(seed)
            settings = {"moderator": mod.model.value, "moderator_effort": mod.effort,
                        "moderator_fallback": str(moderator_fallback) if moderator_fallback else None,
                        "models": [{"model": m.model.value, "effort": m.effort} for m in specs], "roles": roles,
                        "seed": seed, "max_days": max_days, "effort": getattr(client, "effort", None),
                        "mock": isinstance(client, MockClient), "mod_flags": flag_issues,
                        "feedback_field": feedback_field, "check_nights": check_nights, "checkpoint": checkpoint,
                        "tips": str(tips) if tips else None, "tips_for": tips_for if tips else None,
                        "player_tips": [[w, str(f) if f else None] for w, f in player_tips or []],
                        "setup": setup or {"kind": "fixed"}}
            started = time.time()
            meta = game_meta(rules, settings)
            game = setup_game(roles, specs, rng, log, meta={"game_id": log.path.stem, **meta})
            if meta["git_commit"] is None:  # analysis across games groups them by code version
                log.error("setup_error", "couldn't read the git commit (is git installed and on PATH?), so this "
                          "game's code version isn't recorded")
            # Its own RNG, so choosing who gets tips doesn't change the rest of a seed's game.
            files = assign_tips([p.name for p in game.players], [p.model.short for p in game.players], tips,
                                tips_for, player_tips or [], random.Random(f"tips|{seed}"))
            if files:
                texts = {str(f): f.read_text(encoding="utf-8") for f in set(files.values())}
                for p in game.players:
                    p.tips = texts[str(files[p.name])] if p.name in files else ""
                log.write("tips", players=list(files), files={n: str(f) for n, f in files.items()},
                          sha256={f: file_digest(t) for f, t in texts.items()}, texts=texts)
        if isinstance(client, OpenRouterClient):
            client.on_error = log.error
        players = Players(game, client, rules, feedback_field=feedback_field, shared=isinstance(client, OpenRouterClient))
        moderator = Moderator(game, client, players, mod.model, rules, flag_issues=flag_issues, effort=mod.effort,
                              fallback=moderator_fallback)
        if resume:
            moderator.flags = resume["moderator_flags"]
        # The judge is the moderator's model; checks run in the background while the game continues.
        checker = (NightChecker(client, mod.model, mod.model, rules, log, effort=mod.effort)
                   if check_nights else None)
        for p in game.players:
            print(f"  {p.name:<8} {p.role:<17} {ModelSpec(p.model, p.effort)}" + ("  +tips" if p.tips else ""))

        while game.day <= max_days:
            stage = "on day {day} {phase}"
            if checkpoint:
                try:
                    save_checkpoint(ckpt_path, game, play_args=play_args, cost=dict(client.total_cost),
                                    moderator_flags=list(moderator.flags), elapsed_s=time.time() - started,
                                    error_counts=dict(log.error_counts),
                                    client={"mock": isinstance(client, MockClient),
                                            "effort": getattr(client, "effort", None)})
                except Exception as e:  # the game goes on; it just can't be resumed from today
                    log.error("checkpoint_error", f"saving the day {game.day} checkpoint failed: "
                              f"{type(e).__name__}: {e}", traceback=traceback.format_exc())
            # The stall rule (R14) is checked when a day begins; a winner (R1) is checked after every death,
            # i.e. after the day's execution and after the night's (simultaneous) deaths.
            if game.phases_without_death >= STALL_LIMIT:
                game.winners, end_reason = [], "stall"
                game.emit("Nobody died for three days and three nights. Everyone loses.")
                break
            print(f"Day {game.day}...")
            deaths_before = game.death_count()
            run_day(game, players)
            if (winners := game.check_winner()) is not None:
                game.winners, end_reason = winners, "win"
                break
            print(f"Night {game.day}...")
            run_night(game, players, moderator, checker)
            if (winners := game.check_winner()) is not None:
                # Reveal the night's deaths at a proper dawn before the game ends.
                game.phase = "day"
                game.emit(f"Day {game.day} begins.", cat=PHASE)
                game.announce_dawn()
                game.winners, end_reason = winners, "win"
                break
            if game.death_count() == deaths_before:
                game.phases_without_death += 2
        else:
            game.winners, end_reason = [], "day_limit"
            game.emit(f"The game reached its limit of {max_days} days, a safeguard of this program rather "
                      "than a rule, so it ends with no winner.")

        # The game is decided. Steps after it aren't resumable: replaying the last day would add its
        # lessons to lessons.jsonl twice.
        ckpt_path.unlink(missing_ok=True)
        stage = "after the game (in the post-game steps)"
        duration = time.time() - started  # the game itself, without the feedback steps below
        game.emit(f"The game is over. {game.winners_line()}")
        print(f"Winners: {game.winners}")

        def step(label: str, run: Callable[[], object]) -> None:
            """A step after the game; one that fails is logged as an error and the rest still run."""
            print(f"{label}...")
            try:
                run()
            except Exception as e:
                log.error("feedback_error", f"{label} failed: {type(e).__name__}: {e}", step=label,
                          traceback=traceback.format_exc())

        lessons_file = LOG_DIR / ("mock_lessons.jsonl" if isinstance(client, MockClient) else "lessons.jsonl")
        text_log = log.path.with_suffix(".txt")
        if debrief:
            step("Debriefing players and moderator", lambda: run_debrief(game, players, moderator))
        if lessons:
            step("Collecting lessons from players", lambda: run_lessons(game, players, lessons_file))
            step("Collecting the moderator's strategy review",
                 lambda: run_strategy_review(game, client, mod.model, rules, text_log, lessons_file, effort=mod.effort))
        if checker:
            step("Waiting for night checks", checker.finish)
        if review:
            step("Reviewing the log", lambda: run_review(game, client, mod.model, rules, text_log, effort=mod.effort))
        faction_winners = [w for w in game.winners or [] if w not in game.personal_winners]
        winning_faction = game.player(faction_winners[0]).faction if faction_winners else None
        if end_reason == "win" and winning_faction is None:
            end_reason = "no_faction_left"  # e.g. the last players died together, or only Jesters remain
        usage = usage_by_caller(log.path, [{"name": p.name, "model": p.model.value, "role": p.start_role}
                                           for p in game.players])
        log.write("result", winners=game.winners, days=game.day, cost=client.total_cost, usage=usage,
                  roles={p.name: p.role for p in game.players},
                  models={p.name: p.model.value for p in game.players},
                  end_reason=end_reason, winning_faction=winning_faction, duration_s=round(duration),
                  players=[{"name": p.name, "seat": p.seat, "model": p.model.value, "start_role": p.start_role,
                            "final_role": p.role, "faction": p.faction, "alive": p.alive,
                            "left": bool(p.status.get(Status.LEFT)), "won": p.name in (game.winners or []),
                            "tips": bool(p.tips),
                            "death": p.death} for p in game.players],
                  errors=dict(log.error_counts))
        if update_tips and lessons:  # after the result record, which it reads; its errors and cost miss the result
            before = sum(client.total_cost.values())
            step("Updating the tips notebook and sheet", lambda: build_tips(
                [log.path], update_tips, client, mod, 800, include_mock=isinstance(client, MockClient),
                on_error=log.error))
            log.write("tips_update", model=mod.model.value, cost=round(sum(client.total_cost.values()) - before, 6))
    except BaseException as e:  # log it for whoever runs the game, then stop as before
        where = stage.format(day=game.day, phase=game.phase) if "{" in stage else stage
        log.error("crash", f"the game stopped {where}: {type(e).__name__}: {e}"
                  + (f"; continue it with: uv run mafia.py --resume {ckpt_path}" if ckpt_path.exists() else ""),
                  traceback=traceback.format_exc())
        write_views(log)  # the log stays open: night checks may still be running
        raise
    report = write_views(log, close=True)
    print("\n".join(usage_lines(usage)))
    print(f"Errors: {log.error_counts} (listed at the top of the feedback report and the HTML view)"
          if log.error_counts else "Errors: none")
    print(f"Logs: {log.path} (+ .txt, .html)")
    if report:
        print(f"Feedback: {report}")
    if pending := alerts.pending_line(log.path.parent, log.path.stem.split("_")[0]):
        print(pending)
    return log.path


def new_log(prefix: str, seed: int | None) -> GameLog:
    """A new game's log, named by its start time and seed; never another game's (parallel games with the
    same seed can start in the same second)."""
    stem = f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}_{seed}"
    for n in range(1, 100):
        try:
            return GameLog(LOG_DIR / (stem + (f"_{n}" if n > 1 else "") + ".jsonl"), exclusive=True)
        except FileExistsError:
            continue
    raise FileExistsError(f"{LOG_DIR / stem}*.jsonl: too many games with this name")


def resume_log(game: Game, log: GameLog, resume: dict, client: LLMClient, check_nights: bool) -> None:
    """Continues a stopped game's log from its checkpoint (checkpoint.py). The log was cut back to the
    checkpoint; of the records after it, night checks of earlier nights (and the errors they raised) stay,
    as does the crash that stopped the game: they stay counted as errors. The rest is replayed."""
    kept = [r for r in log.cut_records if r["kind"] == "crash"
            or (r["kind"] in ("night_check", "night_check_issue", "night_check_error") and r["night"] < game.day)]
    for r in kept:
        log.write_raw(r)
    # The cut calls were paid for but aren't in the checkpoint's cost (the per-caller usage leaves them out).
    cut_cost: dict[str, float] = {}
    for r in log.cut_records:
        if r.get("cost") and (model := r.get("model") or r.get("judge")):
            cut_cost[model] = cut_cost.get(model, 0) + float(r["cost"])
    log.write("resume", day=game.day, cut_records=len(log.cut_records), unreadable_lines=log.cut_unreadable,
              cut_cost=round(sum(cut_cost.values()), 6))
    print(f"Resuming {log.path.stem} at day {game.day}")
    for model, cost in list(resume["cost"].items()) + list(cut_cost.items()):
        client.total_cost[model] = client.total_cost.get(model, 0) + cost
    log.error_counts = dict(resume["error_counts"])
    for r in kept:
        if r.get("alert"):
            log.error_counts[r["kind"]] = log.error_counts.get(r["kind"], 0) + 1
    if log.cut_unreadable:
        log.error("log_error", f"{log.cut_unreadable} unreadable line(s) after the checkpoint were dropped "
                  "(probably half-written when the game stopped)")


def write_views(log: GameLog, close: bool = False) -> Path | None:
    """Writes the feedback report and (closing the log if `close`) the HTML view. Their failures are
    logged as errors too. Returns the report's path, if there was anything to report."""
    report = None
    try:
        report = write_report(log.path)
    except Exception as e:
        log.error("feedback_error", f"writing the feedback report failed: {type(e).__name__}: {e}",
                  traceback=traceback.format_exc())
    if close:
        log.close()  # renders the HTML view
    else:
        try:
            render_html(log.path)
        except Exception as e:
            log.error("viewer_error", f"rendering the HTML view failed: {type(e).__name__}: {e}",
                      traceback=traceback.format_exc())
    return report


def resolve_effort(spec: ModelSpec, effort: str | None) -> ModelSpec:
    """A spec's own effort, else --effort, else the model's default (MODEL_EFFORT in llm.py)."""
    return ModelSpec(spec.model, spec.effort or effort or default_effort(spec.model))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--players", default="haiku-5.5",
                    help="comma-separated models, cycled over the seats (seats are shuffled); each may set its "
                    "own reasoning effort, e.g. opus-5.5:high,haiku-5.5:low")
    ap.add_argument("--moderator", default="opus-5.5", help="model[:effort] for the moderator, and for the "
                    "night checks, review and quiz grading")
    ap.add_argument("--moderator-fallback", default=str(DEFAULT_MODERATOR_FALLBACK),
                    help="model[:effort] the moderator switches to for the rest of the game if a content filter "
                    "blocks it several times in a row, or 'none'")
    ap.add_argument("--roles", default=",".join(DEFAULT_SETUP), help="comma-separated role names, or random:N "
                    "for a random N-player setup drawn from the seed (see setups.py)")
    ap.add_argument("--role-pool", default="all", choices=POOLS, help="for --roles random:N, draw from every "
                    "role or only roles seen working in a live game")
    ap.add_argument("--effort", default=None, choices=EFFORTS,
                    help="reasoning effort for models that don't set their own (default: each model's own, "
                    "MODEL_EFFORT in llm.py)")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--max-days", type=int, default=None,
                    help=f"stop a game that runs this long, with no winner (default: players + {EXTRA_DAYS})")
    ap.add_argument("--mock", action="store_true", help="no API calls; random player outputs")
    ap.add_argument("--list-roles", action="store_true", help="print which roles are implemented, and how")
    ap.add_argument("--checkpoint", action=argparse.BooleanOptionalAction, default=True,
                    help="save the game at the start of each day to logs/<game>.ckpt, deleted when the game "
                    "finishes, so a stopped game can be continued with --resume")
    ap.add_argument("--resume", metavar="CKPT", help="continue a stopped game from its checkpoint, with the "
                    "settings it started with (other game options are ignored); replays the day it was saved on")
    fb = ap.add_argument_group("feedback from the models (written to logs/<game>_feedback.md); on by default, "
                             "turn one off with --no-<flag>")
    fb.add_argument("--debrief", action=argparse.BooleanOptionalAction, default=True, help="after the game, ask every player and the moderator "
                    "what was confusing, missing or broken")
    fb.add_argument("--mod-flags", action=argparse.BooleanOptionalAction, default=True, help="give the moderator a flag_issue tool for rules "
                    "ambiguities and missing tools during the game")
    fb.add_argument("--feedback-field", action=argparse.BooleanOptionalAction, default=True, help="add an optional out-of-game feedback field "
                    "to every player response")
    fb.add_argument("--lessons", action=argparse.BooleanOptionalAction, default=True, help="after the game, ask every player for tips they wish "
                    "they'd known, and the moderator model for a strategy review of the game; also "
                    "appended to logs/lessons.jsonl across games for analysis")
    fb.add_argument("--review", action=argparse.BooleanOptionalAction, default=True, help="after the game, have the moderator model review the "
                    "whole log for problems")
    fb.add_argument("--check-nights", action=argparse.BooleanOptionalAction, default=True,
                    help="after each night, have the moderator model check the moderator's resolution against "
                    "the rules, in the background; results are logged as night_check records")
    ap.add_argument("--tips", metavar="FILE", type=Path, help="a tips file from past games (build one with "
                    "`uv run tips.py build`), shown in the system prompt of the players --tips-for picks")
    ap.add_argument("--tips-for", default="all", metavar="WHO", help="who gets --tips: all (default), half (a "
                    "random half of the seats, for comparing experienced and fresh players), or comma-separated "
                    "player names (Alice, ...) and models (e.g. opus-5.5)")
    ap.add_argument("--update-tips", metavar="FILE", type=Path, help="after the game, add "
                    "its lessons to the notebook of this tips sheet and rewrite the sheet (tips.py build; needs "
                    f"--lessons); default {DEFAULT_TIPS.relative_to(ROOT)}, {MOCK_TIPS.relative_to(ROOT)} for "
                    "--mock, and none in the cloud (the PC's notebook is the one source of truth)")
    ap.add_argument("--no-update-tips", action="store_true", help="don't update the tips after the game")
    ap.add_argument("--sync", action=argparse.BooleanOptionalAction, default=True, help="when a live game ends or "
                    "stops: in the cloud, push its logs to the logs branch (sync_logs.py push); on the PC, publish "
                    f"the {DEFAULT_TIPS.relative_to(ROOT)} it updated there for cloud games")
    ap.add_argument("--player-tips", default="", metavar="WHO=FILE,...", help="per player or model, which tips "
                    "file to give (or none), applied after --tips/--tips-for; a name wins over a model, e.g. "
                    "opus-5.5=tips/tips.md,Alice=tips/history/tips_20261009_120000.md,gpt-6-luna=none")
    fb.add_argument("--rules-quiz", action="store_true", help="instead of a game, quiz the --players and "
                    "--moderator models on the rules (graded by the moderator model)")
    args = ap.parse_args()
    if args.list_roles:
        print(role_status_table())
        return
    if args.resume:
        try:
            ckpt = load_checkpoint(Path(args.resume))
        except Exception as e:  # e.g. damaged, or pickled on another OS
            ap.error(f"can't resume from {args.resume}: {type(e).__name__}: {e}")
        if any(r["kind"] == "result" for r in read_records(ckpt["log_path"])[0]):  # e.g. a stale synced .ckpt
            ap.error(f"{ckpt['log_path']} already finished; resuming would replace its ending")
        saved = ckpt["play_args"]
        if args.no_update_tips or sync_logs.in_cloud():  # the other options are the game's own
            saved["update_tips"] = None
        resumed_client = (MockClient(saved["seed"]) if ckpt["client"]["mock"]
                          else OpenRouterClient(load_api_key(), effort=ckpt["client"]["effort"]))
        with synced(args.sync and not ckpt["client"]["mock"], saved["update_tips"]):
            play_game(resumed_client, **saved, checkpoint=args.checkpoint, resume=ckpt)
        return

    if args.max_days is not None and args.max_days < 1:
        ap.error("--max-days must be at least 1")
    if args.tips_for != "all" and not args.tips:
        ap.error("--tips-for picks who gets --tips, so it needs --tips")
    seed = args.seed if args.seed is not None else random.randrange(10**6)
    try:
        random_players = parse_random_roles(args.roles)
    except ValueError as e:
        ap.error(str(e))
    setup = None
    if random_players:
        # Its own RNG, so a seed's setup doesn't depend on the rest of the game (and vice versa).
        roles = random_setup(random_players, random.Random(f"setup|{seed}"), args.role_pool)
        setup = {"kind": "random", "players": random_players, "pool": args.role_pool}
    else:
        roles = [r.strip() for r in args.roles.split(",")]
    unknown = [r for r in roles if r not in ROLES]
    if unknown:
        ap.error(f"unknown roles: {unknown}")
    if not 1 <= len(roles) <= len(PLAYER_NAMES):
        ap.error(f"a game has 1 to {len(PLAYER_NAMES)} players (one name each), not {len(roles)}")
    try:
        # Efforts resolved here, so the log records what each model actually used.
        models = [resolve_effort(parse_model_spec(m), args.effort) for m in args.players.split(",")]
        moderator = resolve_effort(parse_model_spec(args.moderator), args.effort)
        fallback = (None if args.moderator_fallback == "none"
                    else resolve_effort(parse_model_spec(args.moderator_fallback), args.effort))
    except ValueError as e:
        ap.error(str(e))
    update_tips = (None if args.no_update_tips else args.update_tips or (
        MOCK_TIPS if args.mock else None if sync_logs.in_cloud() else DEFAULT_TIPS))
    client = MockClient(seed) if args.mock else OpenRouterClient(load_api_key(), effort=args.effort)
    try:
        player_tips = parse_player_tips(args.player_tips)
    except ValueError as e:
        ap.error(str(e))
    for f in [args.tips] + [f for _, f in player_tips]:
        if f and not f.is_file():
            ap.error(f"no such tips file {f}")
        try:
            if f:
                f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            ap.error(f"{f} isn't UTF-8 text; save it as UTF-8")
    try:  # the same check play_game makes, before a game log exists (seat order doesn't matter to it)
        assign_tips(PLAYER_NAMES[:len(roles)], [models[i % len(models)].model.short for i in range(len(roles))],
                    args.tips, args.tips_for, player_tips, random.Random(0))
    except ValueError as e:
        ap.error(str(e))
    if args.rules_quiz:
        if isinstance(client, OpenRouterClient):
            client.on_error = print_alert  # the quiz has no game log
        path = run_quiz(client, models + [moderator], moderator, RULES_PATH.read_text(encoding="utf-8"), LOG_DIR)
        print(f"Quiz results: {path}  Cost: {client.total_cost}")
        return
    with synced(args.sync and not args.mock, update_tips):
        play_game(client, models, moderator, roles, seed, debrief=args.debrief,
                  flag_issues=args.mod_flags, feedback_field=args.feedback_field, review=args.review,
                  lessons=args.lessons, max_days=args.max_days, check_nights=args.check_nights,
                  checkpoint=args.checkpoint, tips=args.tips, tips_for=args.tips_for,
                  player_tips=player_tips, update_tips=update_tips, setup=setup, moderator_fallback=fallback)


@contextmanager
def synced(sync: bool, update_tips: Path | None) -> Iterator[None]:
    """Runs a game, then (even if it crashed or was stopped) syncs it: see --sync and sync_logs.after_game."""
    try:
        yield
    finally:
        if sync:
            sync_logs.after_game(LOG_DIR, DEFAULT_TIPS.parent if update_tips == DEFAULT_TIPS else None,
                                 sync_logs.in_cloud())


if __name__ == "__main__":
    main()
