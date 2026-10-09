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
    checkpoint.py  saves the game each day so a stopped game can continue (--resume)
    feedback.py    debriefs, log review, lessons, strategy review and the rules quiz
    tips.py        distills lessons from past games into a tips file; --tips gives it to players
    night_check.py a judge model checks each night's moderator resolution (--check-nights)
    tests/         offline scenario and hidden-information tests (uv run pytest)

Usage:
    uv run pytest                                            # offline tests
    uv run mafia.py --mock                                   # offline run, no API calls
    uv run mafia.py --list-roles                             # which roles are implemented
    uv run mafia.py --players haiku-5.5,gpt-6-luna --moderator haiku-5.5
    uv run mafia.py --players opus-5.5:high,haiku-5.5:low --moderator opus-5.5:medium
    uv run mafia.py --resume logs/<game>.ckpt                # continue a game that stopped
    uv run tips.py build                                     # tips file from past games' lessons
    uv run mafia.py --tips tips/tips.md --tips-for half      # half the seats play with those tips
"""

import argparse
import hashlib
import random
import subprocess
import time
import traceback
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from day import run_day
from checkpoint import load as load_checkpoint, save as save_checkpoint
from feedback import run_debrief, run_lessons, run_quiz, run_review, run_strategy_review, write_report
from gamelog import GameLog, usage_by_caller
from log_viewer import usage_lines
from llm import (DEFAULT_EFFORT, EFFORTS, LLMClient, MockClient, Model, ModelSpec, OpenRouterClient, load_api_key,
                 parse_model_spec)
from moderator import Moderator
from night_check import NightChecker
from night import run_night
from players import Players
from roles import DEFAULT_SETUP, ROLES, Status, role_status_table
from events import PHASE
from state import setup_game
from tips import choose_players, file_digest

ROOT = Path(__file__).resolve().parent
RULES_PATH = ROOT / "rules_1.txt"
LOG_DIR = ROOT / "logs"


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
              resume: dict | None = None, tips: Path | None = None, tips_for: str = "all") -> Path:
    """checkpoint: save the game at the start of each day to logs/<game>.ckpt (deleted when the game
    finishes). resume: a loaded checkpoint (checkpoint.load) to continue instead of starting a game.
    tips: a tips file (tips.py) put into the system prompt of the players tips_for picks (see
    tips.choose_players); resumed games keep the tips they started with."""
    play_args = {"models": models, "moderator_model": moderator_model, "roles": roles, "seed": seed,
                 "debrief": debrief, "flag_issues": flag_issues, "feedback_field": feedback_field,
                 "review": review, "lessons": lessons, "max_days": max_days, "check_nights": check_nights,
                 "tips": tips, "tips_for": tips_for}
    mod = moderator_model if isinstance(moderator_model, ModelSpec) else ModelSpec(moderator_model)
    specs = [m if isinstance(m, ModelSpec) else ModelSpec(m) for m in models]
    rules = RULES_PATH.read_text(encoding="utf-8")
    max_days = max_days or len(roles) + EXTRA_DAYS
    if resume:
        game = resume["game"]
        log = game.log = GameLog(resume["log_path"], resume_at=resume["log_offsets"])
        # Night checks of earlier nights that finished after the checkpoint stay; the rest is replayed.
        for r in log.cut_records:
            if r["kind"] == "night_check" and r["night"] < game.day:
                log.write_raw(r)
        log.write("resume", day=game.day, cut_records=len(log.cut_records))
        print(f"Resuming {log.path.stem} at day {game.day}")
        for model, cost in resume["cost"].items():
            client.total_cost[model] = client.total_cost.get(model, 0) + cost
        started = time.time() - resume["elapsed_s"]
        log.error_counts = resume["error_counts"]
    else:
        rng = random.Random(seed)
        prefix = "mock" if isinstance(client, MockClient) else "game"  # mock games say random filler text
        log = GameLog(LOG_DIR / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}_{seed}.jsonl")
        settings = {"moderator": mod.model.value, "moderator_effort": mod.effort,
                    "models": [{"model": m.model.value, "effort": m.effort} for m in specs], "roles": roles,
                    "seed": seed, "max_days": max_days, "effort": getattr(client, "effort", None),
                    "mock": isinstance(client, MockClient), "mod_flags": flag_issues,
                    "feedback_field": feedback_field, "check_nights": check_nights, "checkpoint": checkpoint,
                    "tips": str(tips) if tips else None, "tips_for": tips_for if tips else None}
        started = time.time()
        game = setup_game(roles, specs, rng, log, meta={"game_id": log.path.stem, **game_meta(rules, settings)})
        if tips:
            text = tips.read_text(encoding="utf-8")
            # Its own RNG, so choosing who gets tips doesn't change the rest of a seed's game.
            chosen = choose_players([p.name for p in game.players], [p.model.short for p in game.players],
                                    tips_for, random.Random(f"tips|{seed}"))
            for p in game.players:
                p.tips = text if p.name in chosen else ""
            log.write("tips", file=str(tips), sha256=file_digest(text), players=chosen, text=text)
    if isinstance(client, OpenRouterClient):
        client.on_retry = lambda model, attempt, error: log.error(
            "api_retry", f"a {model} request failed (attempt {attempt + 1}), retrying: {error[:300]}",
            model=model, attempt=attempt)
    players = Players(game, client, rules, feedback_field=feedback_field)
    moderator = Moderator(game, client, players, mod.model, rules, flag_issues=flag_issues, effort=mod.effort)
    if resume:
        moderator.flags = resume["moderator_flags"]
    # The judge is the moderator's model; checks run in the background while the game continues.
    checker = (NightChecker(client, mod.model, mod.model, rules, log, effort=mod.effort)
               if check_nights else None)
    for p in game.players:
        print(f"  {p.name:<8} {p.role:<17} {ModelSpec(p.model, p.effort)}" + ("  +tips" if p.tips else ""))
    ckpt_path = log.path.with_suffix(".ckpt")

    try:
        while game.day <= max_days:
            if checkpoint:
                save_checkpoint(ckpt_path, game, play_args=play_args, cost=dict(client.total_cost),
                                moderator_flags=list(moderator.flags), elapsed_s=time.time() - started,
                                error_counts=dict(log.error_counts),
                                client={"mock": isinstance(client, MockClient),
                                        "effort": getattr(client, "effort", None)})
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
    except BaseException as e:  # log it for whoever runs the game, then stop as before
        log.error("crash", f"the game stopped on day {game.day} {game.phase}: {type(e).__name__}: {e}"
                  + (f"; continue it with: uv run mafia.py --resume {ckpt_path}" if ckpt_path.exists() else ""),
                  traceback=traceback.format_exc())
        raise

    duration = time.time() - started  # the game itself, without the feedback steps below
    winner_names = ", ".join(game.winners or []) or "nobody"
    game.emit(f"The game is over. Winners: {winner_names}.")
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
    log.close()
    ckpt_path.unlink(missing_ok=True)
    print("\n".join(usage_lines(usage)))
    print(f"Errors: {log.error_counts} (see the top of the feedback report)" if log.error_counts else "Errors: none")
    print(f"Logs: {log.path} (+ .txt, .html)")
    if report := write_report(log.path):
        print(f"Feedback: {report}")
    return log.path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--players", default="haiku-5.5",
                    help="comma-separated models, cycled over the seats (seats are shuffled); each may set its "
                    "own reasoning effort, e.g. opus-5.5:high,haiku-5.5:low")
    ap.add_argument("--moderator", default="opus-5.5", help="model[:effort] for the moderator, and for the "
                    "night checks, review and quiz grading")
    ap.add_argument("--roles", default=",".join(DEFAULT_SETUP), help="comma-separated role names")
    ap.add_argument("--effort", default=DEFAULT_EFFORT, choices=EFFORTS,
                    help="reasoning effort for models that don't set their own")
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
    fb.add_argument("--rules-quiz", action="store_true", help="instead of a game, quiz the --players and "
                    "--moderator models on the rules (graded by the moderator model)")
    args = ap.parse_args()
    if args.list_roles:
        print(role_status_table())
        return
    if args.resume:
        ckpt = load_checkpoint(Path(args.resume))
        saved = ckpt["play_args"]
        resumed_client = (MockClient(saved["seed"]) if ckpt["client"]["mock"]
                          else OpenRouterClient(load_api_key(), effort=ckpt["client"]["effort"]))
        play_game(resumed_client, **saved, checkpoint=args.checkpoint, resume=ckpt)
        return

    roles = [r.strip() for r in args.roles.split(",")]
    unknown = [r for r in roles if r not in ROLES]
    if unknown:
        ap.error(f"unknown roles: {unknown}")
    try:
        models = [parse_model_spec(m) for m in args.players.split(",")]
        moderator = parse_model_spec(args.moderator)
    except ValueError as e:
        ap.error(str(e))
    seed = args.seed if args.seed is not None else random.randrange(10**6)
    client = MockClient(seed) if args.mock else OpenRouterClient(load_api_key(), effort=args.effort)
    if args.tips and not args.tips.is_file():
        ap.error(f"--tips: no such file {args.tips}")
    if args.rules_quiz:
        path = run_quiz(client, models + [moderator], moderator, RULES_PATH.read_text(encoding="utf-8"), LOG_DIR)
        print(f"Quiz results: {path}  Cost: {client.total_cost}")
        return
    play_game(client, models, moderator, roles, seed, debrief=args.debrief,
              flag_issues=args.mod_flags, feedback_field=args.feedback_field, review=args.review,
              lessons=args.lessons, max_days=args.max_days, check_nights=args.check_nights,
              checkpoint=args.checkpoint, tips=args.tips, tips_for=args.tips_for)


if __name__ == "__main__":
    main()
