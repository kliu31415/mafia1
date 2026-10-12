"""Scaffolding for LLM-played games of the Mafia variant in rules_1.txt.

Design: code owns the game state, the RNG and who can see which message. Day phases (chat,
nominations, votes) run in code. Night actions are collected from players as structured output,
then an LLM moderator resolves them through tools (get_state, apply_changes, random_choice, tell,
ask_player, end_phase), since the role interactions are too varied to hand-code yet.

All LLM calls go through OpenRouter, except Claude models': those run through the Claude Code CLI where it's
installed (--no-claude-code sends them through OpenRouter too).
The API key is read from the OPENROUTER_API_KEY environment variable.

Code layout:
    mafia.py       entry point: game loop and CLI
    llm.py         OpenRouter client, model list, offline mock client
    claude_code.py Claude models through the Claude Code CLI (--claude-code: a Claude subscription's quota)
    roles/         role definitions, the default setup, and per-role hooks (roles/base.py)
    traits.py      traits (rules R24, e.g. Martyr): extra abilities some players have on top of their role
    events.py      event categories for game.emit()
    state.py       game state, events with visibility, deaths, win checks
    variants.py    rule settings (--flips, --trial-votes, --nomination-votes): what deaths and votes reveal
    players.py     player prompts, output schemas, notepads
    day.py         speaking budget, chat turns, nominations, votes
    night.py       Yakuza chat, night actions, Katana vote
    moderator.py   LLM moderator and its tools
    gamelog.py     JSONL log plus live .txt; log_viewer.py renders .txt/.html
    texts.py       plain-text views shared by game code and the viewer: night actions, tips as players see them
    records.py     lenient JSONL reading (skips damaged lines) and console-safe printing
    gamelogs.py    reading game logs for analysis: which files are games, setup/result, players across log versions
    checkpoint.py  saves the game each day and night so a stopped game can continue (--resume)
    feedback.py    debriefs, log review, lessons, strategy review and the rules quiz
    tips.py        distills lessons from past games into a tips file; --tips gives it to players
    setups.py      setups: how roles are drawn (--roles standard[:N]) and what players are told about it
    role_power.py  each role's estimated effect on the Village's chance to win, which standard setups balance
    scripts.py     scripts (--script): the roles a game can use; its rules text lists only those
    stats.py       cross-game statistics: win rates by faction, role and model, per-decision skill
    grade.py       an LLM judge grades each player's play in finished games, blind to models (grades/)
    night_check.py a judge model checks each night's moderator resolution (--check-nights; --fix-nights corrects)
    game_index.py  logs/index.html: every game in one filterable table (by model tier, winner, ...); or `serve`
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
    uv run mafia.py --roles standard:8                       # a balanced standard setup scaled to 8 players
    uv run mafia.py --flips role --trial-votes public --nomination-votes public   # the old rules
    uv run stats.py                                          # win rates and decision skill across logs/
    uv run game_index.py build                               # logs/index.html: browse and filter every game
    uv run game_index.py serve                               # the same, always current, at localhost:8765
    uv run sync_logs.py pull                                 # cloud games' logs into logs/ (see sync_logs.py)
"""

import argparse
import hashlib
import os
import random
import subprocess
import time
import traceback
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

import alerts
import claude_code
import sync_logs
from day import run_day
from checkpoint import load as load_checkpoint, save as save_checkpoint
from feedback import run_debrief, run_lessons, run_quiz, run_review, run_strategy_review, write_report
from gamelog import GameLog, usage_by_caller
from log_viewer import render_html, usage_lines
from llm import (API_KEY_ENV_VAR, EFFORTS, LLMClient, MockClient, Model, ModelSpec, OpenRouterClient,
                 default_effort, load_api_key, parse_model_spec)
from moderator import Moderator
from night_check import NightChecker
from night import run_night
from players import Players, role_briefing
from roles import ROLES, Status, retired_entry, role_status_table
from setups import POOLS, SETUPS, draw_traits, parse_setup, players_for, setup_note
from events import PHASE
from records import read_records
from state import PLAYER_NAMES, Game, setup_game
from traits import TRAITS
import role_power
import scripts
import variants
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
    # tips/ is tracked but changes after every PC game; it isn't code, so it doesn't make a game "dirty"
    status = git("status", "--porcelain", "--untracked-files=no", "--", ".", ":!tips")
    return {"git_commit": git("rev-parse", "HEAD"), "git_dirty": bool(status) if status is not None else None,
            "rules_sha256": hashlib.sha256(rules.encode("utf-8")).hexdigest()[:16], "settings": settings}


@dataclass
class GameConfig:
    """A game's options: what play_game runs, what its checkpoint keeps so --resume plays on with the same
    options, and (through settings()) what the log records.
    tips: a tips file (tips.py) put into the system prompt of the players tips_for picks (see
    tips.choose_players); player_tips then sets (or, with None, removes) each named player's or model's
    tips file. Resumed games keep the tips they started with. update_tips: a tips sheet whose notebook
    to update with this game's lessons afterwards (tips.build), rewriting the sheet. setup: how roles
    was chosen, for the log (default {"kind": "fixed"}; setups.py makes {"kind": "random", "pool": ...}).
    max_days: None means players + EXTRA_DAYS."""
    models: Sequence[Model | ModelSpec]
    moderator: Model | ModelSpec
    roles: list[str]
    seed: int | None = None
    debrief: bool = False
    flag_issues: bool = False
    feedback_field: bool = False
    review: bool = False
    lessons: bool = False
    max_days: int | None = None
    check_nights: bool = False
    fix_nights: bool = False  # the night check runs before dawn and its findings go back to the moderator
    tips: Path | None = None
    tips_for: str = "all"
    player_tips: list[tuple[str, Path | None]] = field(default_factory=list)
    update_tips: Path | None = None
    setup: dict | None = None
    moderator_fallback: ModelSpec | None = DEFAULT_MODERATOR_FALLBACK
    # Rule settings (variants.py): what a death reveals, and whether trial and nomination votes are secret
    flips: str = variants.DEFAULTS["flips"]
    trial_votes: str = variants.DEFAULTS["trial_votes"]
    nomination_votes: str = variants.DEFAULTS["nomination_votes"]
    script: str = scripts.DEFAULT  # the roles the game can use (scripts.py)
    traits: list[str] = field(default_factory=list)  # traits dealt to random eligible players (traits.py, R24)

    def __post_init__(self) -> None:
        self.player_tips = self.player_tips or []
        self.models = [m if isinstance(m, ModelSpec) else ModelSpec(m) for m in self.models]
        if not isinstance(self.moderator, ModelSpec):
            self.moderator = ModelSpec(self.moderator)

    @property
    def mod(self) -> ModelSpec:
        assert isinstance(self.moderator, ModelSpec)  # __post_init__
        return self.moderator

    @property
    def specs(self) -> list[ModelSpec]:
        return [m for m in self.models if isinstance(m, ModelSpec)]  # all of them, after __post_init__

    @property
    def day_limit(self) -> int:
        return self.max_days if self.max_days is not None else len(self.roles) + EXTRA_DAYS

    def settings(self, client: LLMClient, checkpoint: bool) -> dict:
        """The "settings" in the log's setup record (game_meta); analysis reads these keys, so keep them."""
        mock = isinstance(client, MockClient)
        return {"moderator": self.mod.model.value, "moderator_effort": self.mod.effort,
                "moderator_fallback": str(self.moderator_fallback) if self.moderator_fallback else None,
                "models": [{"model": m.model.value, "effort": m.effort} for m in self.specs], "roles": self.roles,
                "seed": self.seed, "max_days": self.day_limit, "effort": getattr(client, "effort", None),
                "mock": mock, "claude_code": isinstance(client, claude_code.ClaudeCodeClient),
                "mod_flags": self.flag_issues, "feedback_field": self.feedback_field,
                "check_nights": self.check_nights, "fix_nights": self.check_nights and self.fix_nights,
                "checkpoint": checkpoint,
                "tips": str(self.tips) if self.tips else None, "tips_for": self.tips_for if self.tips else None,
                "player_tips": [[w, str(f) if f else None] for w, f in self.player_tips],
                "setup": self.setup or {"kind": "fixed"}, "traits": self.traits, **self.rule_settings}

    @property
    def rule_settings(self) -> dict[str, str]:
        """The rule settings (variants.py), the script and any roles the setup never draws (setup_off), which
        game.rule_settings and the log's settings keep."""
        random_setup = self.setup and self.setup.get("kind") == "random"
        off = SETUPS[self.setup.get("name", "standard")].off if self.setup and random_setup else ()
        return {**{name: getattr(self, name) for name in variants.SETTINGS}, "script": self.script,
                **({"setup_off": ",".join(off)} if off else {})}

    @classmethod
    def from_checkpoint(cls, ckpt: dict) -> "GameConfig":
        """The options a checkpointed game started with. Checkpoints keep them as a dict (a pickled GameConfig
        would name this module, which is __main__ when mafia.py runs as a script); before GameConfig they were
        play_game's keyword arguments, "play_args"."""
        if "config" in ckpt:
            config = cls(**{**variants.LEGACY, **ckpt["config"]})  # checkpoints from before the rule settings
        else:
            old = dict(ckpt["play_args"])
            old["moderator"] = old.pop("moderator_model")
            old["player_tips"] = old["player_tips"] or []
            config = cls(**{**variants.LEGACY, **old})
        if config.roles:  # a hand-picked list naming a role retired since (checkpoint.resume_retired renames players)
            config.roles = [found[1].now[0] if (found := retired_entry(r, ckpt.get("log_version", 0))) else r
                            for r in config.roles]
        return config


def play_game(client: LLMClient, config: GameConfig, *, checkpoint: bool = True,
              resume: dict | None = None, after_save: Callable[[], None] | None = None) -> Path:
    """Plays a game and its post-game steps; returns its log's path. checkpoint: save the game at the start
    of each day and night to logs/<game>.ckpt (deleted when the game finishes). resume: a loaded checkpoint
    (checkpoint.load) to continue instead of starting a game; config is then GameConfig.from_checkpoint's.
    after_save: called after each checkpoint is saved (synced: in the cloud, pushes it to the logs branch)."""
    full_rules = RULES_PATH.read_text(encoding="utf-8")
    rules = (scripts.rules_for(full_rules, config.script) + variants.rules_notes(config.rule_settings)
             + setup_note(config.setup, config.roles))
    if resume:
        log = GameLog(resume["log_path"], resume_at=resume["log_offsets"])
    else:
        prefix = "mock" if isinstance(client, MockClient) else "game"  # mock games say random filler text
        log = new_log(prefix, config.seed)
    ckpt_path = log.path.with_suffix(".ckpt")
    game: Game | None = None
    stage = "while setting it up"  # for the crash record
    try:
        if resume:
            game = resume["game"]
            game.log = log
            resume_log(game, log, resume, client, config.check_nights)
            if resume.get("forced"):  # a checkpoint from older code (--force-resume)
                log.error("resume_forced", f"{resume['forced']}; resumed anyway with --force-resume")
            if resume.get("retired"):  # roles retired since it was saved (checkpoint.resume_retired)
                log.write("resume_retired", changes=resume["retired"])
            started = time.time() - resume["elapsed_s"]
        else:
            started = time.time()
            game = start_game(client, config, rules, log, checkpoint)
            if scripts.stale(full_rules, config.script):  # after the setup record, which a log starts with
                log.error("script_stale", f"the {config.script} script's cached rules revision doesn't match "
                          "rules_1.txt, so this game plays by the plain cut; `uv run scripts.py revise` remakes it")
        game.rule_settings = dict(config.rule_settings)  # a resumed game's own (from_checkpoint)
        if isinstance(client, (OpenRouterClient, claude_code.ClaudeCodeClient)):
            client.on_error = log.error
        players = Players(game, client, rules, feedback_field=config.feedback_field,
                          shared=isinstance(client, (OpenRouterClient, claude_code.ClaudeCodeClient)))
        mod = config.mod
        moderator = Moderator(game, client, players, mod.model, rules, flag_issues=config.flag_issues,
                              effort=mod.effort, fallback=config.moderator_fallback)
        if resume:
            moderator.flags = resume["moderator_flags"]
        # The judge is the moderator's model; checks run in the background while the game continues, or before
        # dawn with --fix-nights.
        checker = (NightChecker(client, mod.model, mod.model, rules, log, effort=mod.effort, fix=config.fix_nights)
                   if config.check_nights else None)
        for p in game.players:
            print(f"  {p.name:<8} {p.role:<17} {ModelSpec(p.model, p.effort)}" + ("  +tips" if p.tips else ""))
        config_dict = {f.name: getattr(config, f.name) for f in fields(config)}

        def save(at: str, **extra: object) -> None:
            """A checkpoint at the start of a day or night (at: "day" or "night"); resuming replays from there."""
            assert game is not None
            if not checkpoint:
                return
            try:
                save_checkpoint(ckpt_path, game, config=config_dict, cost=dict(client.total_cost),
                                moderator_flags=list(moderator.flags), elapsed_s=time.time() - started,
                                error_counts=dict(log.error_counts), at=at,
                                client={"mock": isinstance(client, MockClient),
                                        "effort": getattr(client, "effort", None),
                                        "claude_code": isinstance(client, claude_code.ClaudeCodeClient)}, **extra)
            except Exception as e:  # the game goes on; it just can't be resumed from here
                log.error("checkpoint_error", f"saving the {at} {game.day} checkpoint failed: "
                          f"{type(e).__name__}: {e}", traceback=traceback.format_exc())
                return
            if after_save:
                try:
                    after_save()
                except Exception as e:  # the game goes on; a sandbox lost now loses the game since the last push
                    log.error("sync_error", f"pushing the {at} {game.day} checkpoint failed: {type(e).__name__}: "
                              f"{e}", traceback=traceback.format_exc())

        stage = "on day {day} {phase}"
        end_reason = run_game(game, players, moderator, checker, config.day_limit, save, resume)
        # The game is decided. Steps after it aren't resumable: replaying the last day would add its
        # lessons to lessons.jsonl twice.
        ckpt_path.unlink(missing_ok=True)
        stage = "after the game (in the post-game steps)"
        usage = after_game(game, client, config, players, moderator, checker, rules, end_reason,
                           duration=time.time() - started)  # the game itself, without the post-game steps
    except BaseException as e:  # log it for whoever runs the game, then stop as before
        where = stage.format(day=game.day, phase=game.phase) if game and "{" in stage else stage
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


def start_game(client: LLMClient, config: GameConfig, rules: str, log: GameLog, checkpoint: bool) -> Game:
    """A new game: seats and roles drawn from the seed, the setup record, and who gets which tips."""
    meta = game_meta(rules, config.settings(client, checkpoint))
    game = setup_game(config.roles, config.specs, random.Random(config.seed), log,
                      meta={"game_id": log.path.stem, **meta}, rule_settings=config.rule_settings,
                      via=lambda m: claude_code.route(client, m), traits=config.traits)
    if meta["git_commit"] is None:  # analysis across games groups them by code version
        log.error("setup_error", "couldn't read the git commit (is git installed and on PATH?), so this "
                  "game's code version isn't recorded")
    # Its own RNG, so choosing who gets tips doesn't change the rest of a seed's game.
    files = assign_tips([p.name for p in game.players], [p.model.short for p in game.players], config.tips,
                        config.tips_for, config.player_tips, random.Random(f"tips|{config.seed}"))
    if files:
        texts = {str(f): f.read_text(encoding="utf-8") for f in set(files.values())}
        for p in game.players:
            p.tips = texts[str(files[p.name])] if p.name in files else ""
        log.write("tips", players=list(files), files={n: str(f) for n, f in files.items()},
                  sha256={f: file_digest(t) for f, t in texts.items()}, texts=texts)
    # The texts every prompt is built on, which the log otherwise keeps only as rules_sha256: the rules as played
    # (the script's rules, the rule settings' notes and the setup note) and each player's opening role briefing.
    told = setup_note(config.setup, config.roles).strip().removeprefix("---").strip()
    log.write("briefing", rules=rules, setup_note=told,
              players={p.name: role_briefing(game, p) for p in game.players})
    return game


def run_game(game: Game, players: Players, moderator: Moderator, checker: NightChecker | None, max_days: int,
             save: Callable[..., None], resume: dict | None) -> str:
    """Days and nights until the game is decided; sets game.winners and returns the end reason
    ("win", "stall" or "day_limit")."""
    # A game resumed from a night checkpoint skips straight to that night.
    at_night = bool(resume and resume.get("at") == "night")
    deaths_before = resume.get("deaths_before", 0) if resume else 0
    while game.day <= max_days:
        if at_night:
            at_night = False
        else:
            save("day")
            # The stall rule (R14) is checked when a day begins; a winner (R1) is checked after every death,
            # i.e. after the day's execution and after the night's (simultaneous) deaths.
            if game.phases_without_death >= STALL_LIMIT:
                game.winners = []
                game.emit("Nobody died for three days and three nights. Everyone loses.")
                return "stall"
            deaths_before = game.death_count()
            print(f"Day {game.day}...")
            run_day(game, players)
            if (winners := game.check_winner()) is not None:
                game.winners = winners
                return "win"
        save("night", deaths_before=deaths_before)  # deaths_before: for the stall count after the night
        print(f"Night {game.day}...")
        run_night(game, players, moderator, checker)
        if (winners := game.check_winner()) is not None:
            # Reveal the night's deaths at a proper dawn before the game ends.
            game.phase = "day"
            game.emit(f"Day {game.day} begins.", cat=PHASE)
            game.announce_dawn()
            game.winners = winners
            return "win"
        if game.death_count() == deaths_before:
            game.phases_without_death += 2
    game.winners = []
    game.emit(f"The game reached its limit of {max_days} days, a safeguard of this program rather "
              "than a rule, so it ends with no winner.")
    return "day_limit"


def after_game(game: Game, client: LLMClient, config: GameConfig, players: Players, moderator: Moderator,
               checker: NightChecker | None, rules: str, end_reason: str, duration: float) -> list[dict]:
    """The post-game steps (debrief, lessons, night checks, review), the result record, then the tips
    update. Returns the usage by caller, for the console summary."""
    log, mod = game.log, config.mod
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

    mock = isinstance(client, MockClient)
    lessons_file = LOG_DIR / ("mock_lessons.jsonl" if mock else "lessons.jsonl")
    text_log = log.path.with_suffix(".txt")
    if config.debrief:
        step("Debriefing players and moderator", lambda: run_debrief(game, players, moderator))
    if config.lessons:
        step("Collecting lessons from players", lambda: run_lessons(game, players, lessons_file))
        step("Collecting the moderator's strategy review",
             lambda: run_strategy_review(game, client, mod.model, rules, text_log, lessons_file, effort=mod.effort))
    if checker:
        step("Waiting for night checks", checker.finish)
    if config.review:
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
              players=[{"name": p.name, "seat": p.seat, "model": p.model.value,
                        "via": claude_code.route(client, p.model), "start_role": p.start_role,
                        "final_role": p.role, "faction": p.faction, "alive": p.alive,
                        "left": bool(p.status.get(Status.LEFT)), "won": p.name in (game.winners or []),
                        "tips": bool(p.tips),
                        "death": p.death} for p in game.players],
              errors=dict(log.error_counts))
    if (update_tips := config.update_tips) and config.lessons:
        # After the result record, which it reads; its errors and cost miss the result.
        before = sum(client.total_cost.values())
        # main's notebook first, if another PC added games to it (then this PC's other games go on top again)
        again = sync_logs.rebase_tips(sync_logs.Repo(), update_tips.parent, LOG_DIR, on_error=log.error) \
            if update_tips == DEFAULT_TIPS and not mock else []
        step("Updating the tips notebook and sheet", lambda: build_tips(
            [*again, log.path], update_tips, client, mod, 800, include_mock=mock, on_error=log.error))
        log.write("tips_update", model=mod.model.value, cost=round(sum(client.total_cost.values()) - before, 6))
        if update_tips == DEFAULT_TIPS and not mock:  # next to the tips, so their commit and publish carry it
            step("Refitting the role powers", lambda: role_power.update(LOG_DIR))
    return usage


def new_log(prefix: str, seed: int | None) -> GameLog:
    """A new game's log, named by its start time (UTC, so names sort in start order across machines and time
    zones; logs named before Oct 12 2026 used the local time) and seed; never another game's (parallel games with the
    same seed can start in the same second)."""
    stem = f"{prefix}_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{seed}"
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
    at = resume.get("at", "day")
    log.write("resume", day=game.day, at=at, cut_records=len(log.cut_records), unreadable_lines=log.cut_unreadable,
              cut_cost=round(sum(cut_cost.values()), 6))
    print(f"Resuming {log.path.stem} at {at} {game.day}")
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


def resolve_effort(spec: ModelSpec, effort: str | None, cli: bool = False) -> ModelSpec:
    """A spec's own effort, else --effort, else the model's default (MODELS in llm.py); cli: run through the Claude
    Code CLI (--claude-code), whose defaults can differ (ModelInfo.cli_effort)."""
    via_cli = cli and claude_code.routes(spec.model)
    return ModelSpec(spec.model, spec.effort or effort or default_effort(spec.model, via_cli))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--players", default="haiku-5.5",
                    help="comma-separated models, cycled over the seats (seats are shuffled); each may set its "
                    "own reasoning effort, e.g. opus-5.5:high,haiku-5.5:low")
    ap.add_argument("--moderator", default="opus-5.5", help="model[:effort] for the moderator, and for the "
                    "night checks, review and quiz grading")
    ap.add_argument("--moderator-fallback", default=str(DEFAULT_MODERATOR_FALLBACK),
                    help="model[:effort] the moderator switches to for the rest of the game if a content filter "
                    "blocks it several times in a row, or 'none'")
    ap.add_argument("--roles", default="standard", help="a setup drawn from the seed: NAME (its usual player "
                    f"count) or NAME:N for N players, NAME one of {', '.join(SETUPS)} (random means classic)"
                    "; or comma-separated role names (see setups.py)")
    ap.add_argument("--yakuza", type=int, default=None, help="for the standard setup: exactly this many Yakuza "
                    "(players are still told the setup's usual range)")
    ap.add_argument("--script", default=scripts.DEFAULT, choices=scripts.SCRIPTS, help="the roles this game can "
                    "use (scripts.py): players see only these roles' rules, and every role in the game is one of "
                    "them; 'all' is every role")
    ap.add_argument("--traits", default=None, help="traits dealt to random eligible players (traits.py, rules "
                    "R24): comma-separated trait names (A+B: one player gets both), or 'none'; by default a drawn "
                    "setup draws 0-3 (setups.py) and a role list gets none")
    ap.add_argument("--role-pool", default="all", choices=POOLS, help="for a drawn setup, draw from every "
                    "role or only roles seen working in a live game")
    ap.add_argument("--effort", default=None, choices=EFFORTS,
                    help="reasoning effort for models that don't set their own (default: each model's own, "
                    "MODELS in llm.py)")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--max-days", type=int, default=None,
                    help=f"stop a game that runs this long, with no winner (default: players + {EXTRA_DAYS})")
    ap.add_argument("--flips", choices=variants.SETTINGS["flips"], default=variants.DEFAULTS["flips"],
                    help="what a death reveals: nothing but the cause and will (default), only the alignment (Good, "
                    "Evil or Neutral), or the role (rules R12)")
    ap.add_argument("--trial-votes", choices=variants.SETTINGS["trial_votes"],
                    default=variants.DEFAULTS["trial_votes"],
                    help="secret (default): only the Guilty/Innocent totals are announced; public: every vote (R4)")
    ap.add_argument("--nomination-votes", choices=variants.SETTINGS["nomination_votes"],
                    default=variants.DEFAULTS["nomination_votes"],
                    help="secret (default): only the nominator and the Yes count are announced; public: every vote")
    ap.add_argument("--mock", action="store_true", help="no API calls; random player outputs")
    ap.add_argument("--claude-code", action=argparse.BooleanOptionalAction, default=None,
                    help="run Claude models' calls through the Claude Code CLI on this machine (`claude -p`, the "
                    "signed-in Claude subscription's quota) instead of OpenRouter; other models still use OpenRouter "
                    "(claude_code.py). Default: on when the `claude` command is found; --no-claude-code sends "
                    "Claude models through OpenRouter too")
    ap.add_argument("--plan-cap", default=None, metavar="FIVE_HOUR,WEEK",
                    help="with Claude Code: the percent of the subscription's 5-hour and 7-day windows that games may "
                    "use up, leaving the rest for other work (default 70,70; 100,100 turns it off). At a cap a game "
                    "doesn't start, and a running one waits for the reset or stops for --resume. Early in the week "
                    "a game starts only below a lower 7-day figure, which rises evenly from 10%% at the week's "
                    "reset to the cap at the next one. A program safeguard, not a rule")
    ap.add_argument("--list-roles", action="store_true", help="print which roles are implemented, and how")
    ap.add_argument("--checkpoint", action=argparse.BooleanOptionalAction, default=True,
                    help="save the game at the start of each day and night to logs/<game>.ckpt, deleted when the game "
                    "finishes, so a stopped game can be continued with --resume")
    ap.add_argument("--resume", metavar="CKPT", help="continue a stopped game from its checkpoint, with the "
                    "settings it started with (other game options are ignored); replays the day or night it was "
                    "saved at")
    ap.add_argument("--force-resume", action="store_true", help="with --resume: resume a checkpoint saved by "
                    "older code (another checkpoint version) anyway, giving new fields their defaults, with a "
                    "warning; usually fine after small changes")
    fb = ap.add_argument_group("feedback from the models (written to logs/<game>_feedback.md); on by default, "
                             "turn one off with --no-<flag>")
    fb.add_argument("--debrief", action=argparse.BooleanOptionalAction, default=True,
                    help="after the game, ask every player and the moderator "
                    "what was confusing, missing or broken")
    fb.add_argument("--mod-flags", action=argparse.BooleanOptionalAction, default=True,
                    help="give the moderator a flag_issue tool for rules "
                    "ambiguities and missing tools during the game")
    fb.add_argument("--feedback-field", action=argparse.BooleanOptionalAction, default=True,
                    help="add an optional out-of-game feedback field "
                    "to every player response")
    fb.add_argument("--lessons", action=argparse.BooleanOptionalAction, default=True,
                    help="after the game, ask every player for tips they wish "
                    "they'd known, and the moderator model for a strategy review of the game; also "
                    "appended to logs/lessons.jsonl across games for analysis")
    fb.add_argument("--review", action=argparse.BooleanOptionalAction, default=True,
                    help="after the game, have the moderator model review the "
                    "whole log for problems")
    fb.add_argument("--check-nights", action=argparse.BooleanOptionalAction, default=True,
                    help="after each night, have the moderator model check the moderator's resolution against "
                    "the rules, in the background; results are logged as night_check records")
    fb.add_argument("--fix-nights", action=argparse.BooleanOptionalAction, default=True,
                    help="with --check-nights: check each night before dawn instead, and send its high-severity "
                    "findings back to the moderator to verify and correct (adds the check's time to each night)")
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
    return ap


def via_claude_code(flag: bool | None, mock: bool = False) -> bool:
    """Whether a game's Claude models run through the Claude Code CLI: --claude-code / --no-claude-code, else
    (the default) wherever the CLI is installed. Mock games make no calls."""
    if mock or flag is False:
        return False
    if flag and not claude_code.available():
        raise ValueError("--claude-code needs the Claude Code CLI, but no `claude` command was found on PATH")
    return claude_code.available()


def parse_plan_cap(text: str | None) -> dict[str, float] | None:
    """--plan-cap "80,70" as the share of each subscription window games may use; None (not given) is the default."""
    if text is None:
        return None
    try:
        five_hour, week = (float(x) / 100 for x in text.replace("%", "").split(","))
    except ValueError:
        raise ValueError(f"--plan-cap takes two percents, 5-hour then 7-day (e.g. 80,70), not {text!r}") from None
    if not (0 < five_hour <= 1 and 0 < week <= 1):
        raise ValueError(f"--plan-cap percents go from 1 to 100, not {text!r}")
    return {"five_hour": five_hour, "seven_day": week}


def api_client(effort: str | None, via_claude_code: bool, plan_cap: dict[str, float] | None = None) -> LLMClient:
    """OpenRouter, or with via_claude_code Claude models through the Claude Code CLI (claude_code.py) and the
    rest through OpenRouter, whose key is then needed only if a game seats another maker's model."""
    if not via_claude_code:
        return OpenRouterClient(load_api_key(), effort=effort)
    other = OpenRouterClient(load_api_key(), effort=effort) if os.environ.get(API_KEY_ENV_VAR, "").strip() else None
    return claude_code.ClaudeCodeClient(other, effort=effort, caps=plan_cap)


def check_plan(ap: argparse.ArgumentParser, client: LLMClient, models: Sequence[Model | ModelSpec]) -> None:
    """Before a live game that seats Claude models through Claude Code: stops if the subscription is at a cap
    (--plan-cap) or the CLI doesn't answer, and prints the utilization otherwise."""
    seated = [m.model if isinstance(m, ModelSpec) else m for m in models]
    if not isinstance(client, claude_code.ClaudeCodeClient) or not any(claude_code.routes(m) for m in seated):
        return
    try:
        print(f"{client.check_plan()}. Claude models run through the Claude Code CLI; --no-claude-code sends them "
              "through OpenRouter")
    except (claude_code.PlanLimitError, RuntimeError) as e:
        ap.error(f"{e} (--no-claude-code runs Claude models through OpenRouter)")


def resume_game(ap: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """--resume: continue a stopped game with the settings it started with."""
    try:
        ckpt = load_checkpoint(Path(args.resume), force=args.force_resume)
    except Exception as e:  # e.g. damaged, or pickled on another OS
        ap.error(f"can't resume from {args.resume}: {type(e).__name__}: {e}")
    if ckpt.get("forced"):
        print_alert("resume_forced", f"{ckpt['forced']}. Resuming anyway (--force-resume): watch for errors")
    if any(r["kind"] == "result" for r in read_records(ckpt["log_path"])[0]):  # e.g. a stale synced .ckpt
        ap.error(f"{ckpt['log_path']} already finished; resuming would replace its ending")
    saved = GameConfig.from_checkpoint(ckpt)
    if args.no_update_tips or sync_logs.in_cloud():  # the other options are the game's own
        saved.update_tips = None
    try:
        plan_cap = parse_plan_cap(args.plan_cap)
    except ValueError as e:
        ap.error(str(e))
    resumed_client = (MockClient(saved.seed) if ckpt["client"]["mock"]
                      else api_client(ckpt["client"]["effort"], ckpt["client"].get("claude_code", False), plan_cap))
    check_plan(ap, resumed_client, [*saved.models, saved.moderator])
    with synced(args.sync and not ckpt["client"]["mock"], saved.update_tips) as after_save:
        play_game(resumed_client, saved, checkpoint=args.checkpoint, resume=ckpt, after_save=after_save)


def choose_roles(ap: argparse.ArgumentParser, args: argparse.Namespace, seed: int) -> tuple[list[str], dict | None]:
    """The game's roles in seat order, from --roles (a named setup drawn from the seed, or a list), and the setup
    record for a drawn one (None for a list)."""
    try:
        named = parse_setup(args.roles)
    except ValueError as e:
        ap.error(str(e))
    setup = None
    if named:
        name, n = named
        n = players_for(name, n, seed)
        # Its own RNG, so a seed's setup doesn't depend on the rest of the game (and vice versa).
        options = {"yakuza": args.yakuza} if args.yakuza is not None else {}
        if options and name != "standard":
            ap.error("--yakuza only works with the standard setup")
        roles = SETUPS[name].draw(n, random.Random(f"setup|{seed}"), args.role_pool, script=args.script, **options)
        setup = {"kind": "random", "name": name, "players": n, "pool": args.role_pool, **options}
    else:
        roles = [r.strip() for r in args.roles.split(",")]
    unknown = [r for r in roles if r not in ROLES]
    if unknown:
        ap.error(f"unknown roles: {unknown}")
    if off := scripts.off_script(args.script, roles):
        ap.error(f"not on the {args.script} script: {', '.join(off)}")
    if not 1 <= len(roles) <= len(PLAYER_NAMES):
        ap.error(f"a game has 1 to {len(PLAYER_NAMES)} players (one name each), not {len(roles)}")
    return roles, setup


def choose_traits(ap: argparse.ArgumentParser, args: argparse.Namespace, roles: list[str], setup: dict | None,
                  seed: int) -> list[str]:
    """The traits to deal (rules R24): --traits, or by default drawn for a drawn setup and none for a role list."""
    if args.traits is None:
        # Its own RNG, so a seed's traits don't change the rest of its setup (and vice versa).
        return draw_traits(roles, random.Random(f"traits|{seed}")) if setup else []
    if setup:  # the setup note mustn't tell players the traits were drawn (setups.setup_note)
        setup["traits_given"] = True
    if args.traits == "none":
        return []
    names = [t.strip() for t in args.traits.split(",")]
    if unknown := [t for item in names for t in item.split("+") if t not in TRAITS]:
        ap.error(f"unknown traits: {unknown} (known: {', '.join(TRAITS)})")
    if repeated := [item for item in names if len(set(item.split("+"))) < len(item.split("+"))]:
        ap.error(f"a player holds a trait at most once (rules R24): {repeated}")
    return names


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()
    if args.list_roles:
        print(role_status_table())
        return
    if args.resume:
        resume_game(ap, args)
        return

    if args.max_days is not None and args.max_days < 1:
        ap.error("--max-days must be at least 1")
    if args.tips_for != "all" and not args.tips:
        ap.error("--tips-for picks who gets --tips, so it needs --tips")
    seed = args.seed if args.seed is not None else random.randrange(10**6)
    roles, setup = choose_roles(ap, args, seed)
    traits = choose_traits(ap, args, roles, setup, seed)
    try:
        args.claude_code = via_claude_code(args.claude_code, args.mock)
        plan_cap = parse_plan_cap(args.plan_cap)
        # Efforts resolved here, so the log records what each model actually used.
        models = [resolve_effort(parse_model_spec(m), args.effort, args.claude_code) for m in args.players.split(",")]
        moderator = resolve_effort(parse_model_spec(args.moderator), args.effort, args.claude_code)
        fallback = (None if args.moderator_fallback == "none"
                    else resolve_effort(parse_model_spec(args.moderator_fallback), args.effort, args.claude_code))
    except ValueError as e:
        ap.error(str(e))
    update_tips = (None if args.no_update_tips else args.update_tips or (
        MOCK_TIPS if args.mock else None if sync_logs.in_cloud() else DEFAULT_TIPS))
    client = MockClient(seed) if args.mock else api_client(args.effort, args.claude_code, plan_cap)
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
        if isinstance(client, (OpenRouterClient, claude_code.ClaudeCodeClient)):
            client.on_error = print_alert  # the quiz has no game log
        rules = scripts.rules_for(RULES_PATH.read_text(encoding="utf-8"), args.script)
        path = run_quiz(client, models + [moderator], moderator, rules, LOG_DIR)
        print(f"Quiz results: {path}  Cost: {client.total_cost}")
        return
    check_plan(ap, client, [*models, moderator])
    if args.sync and update_tips == DEFAULT_TIPS:  # a PC game: cloud games' lessons go in the tips first
        try:
            sync_logs.catch_up(sync_logs.Repo(), LOG_DIR, DEFAULT_TIPS.parent, args.moderator)
        except Exception as e:  # the game can still run with the tips it has
            print_alert("sync_error", f"getting cloud games' logs failed: {type(e).__name__}: {e}; "
                        "`uv run sync_logs.py pull` retries")
    with synced(args.sync and not args.mock, update_tips) as after_save:
        play_game(client, GameConfig(
            models, moderator, roles, seed, debrief=args.debrief, flag_issues=args.mod_flags,
            feedback_field=args.feedback_field, review=args.review, lessons=args.lessons, max_days=args.max_days,
            check_nights=args.check_nights, fix_nights=args.fix_nights, tips=args.tips, tips_for=args.tips_for,
            player_tips=player_tips,
            update_tips=update_tips, setup=setup, moderator_fallback=fallback, flips=args.flips,
            trial_votes=args.trial_votes, nomination_votes=args.nomination_votes, script=args.script,
            traits=traits),
            checkpoint=args.checkpoint, after_save=after_save)


@contextmanager
def synced(sync: bool, update_tips: Path | None) -> Iterator[Callable[[], None] | None]:
    """Runs a game, then (even if it crashed or was stopped) adds it to the game index and syncs it: see --sync
    and sync_logs.after_game. Yields what play_game calls after each checkpoint: in the cloud, a push of the
    logs (checkpoint included) to the logs branch, so a game whose sandbox is lost can resume elsewhere
    (`sync_logs.py get GAME`, then --resume); None otherwise."""
    def push() -> None:
        sync_logs.push(sync_logs.Repo(), LOG_DIR)
    try:
        yield push if sync and sync_logs.in_cloud() else None
    finally:
        sync_logs.rebuild_index(LOG_DIR)  # logs/index.html lists the game (game_index.py)
        if sync:
            sync_logs.after_game(LOG_DIR, DEFAULT_TIPS.parent if update_tips == DEFAULT_TIPS else None,
                                 sync_logs.in_cloud())


if __name__ == "__main__":
    main()
