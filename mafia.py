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
    feedback.py    debriefs, log review, lessons and the rules quiz
    tests/         offline scenario and hidden-information tests (uv run pytest)

Usage:
    uv run pytest                                            # offline tests
    uv run mafia.py --mock                                   # offline run, no API calls
    uv run mafia.py --list-roles                             # which roles are implemented
    uv run mafia.py --players haiku-5.5,gpt-6-luna --moderator haiku-5.5
"""

import argparse
import random
from datetime import datetime
from pathlib import Path

from day import run_day
from feedback import run_debrief, run_lessons, run_quiz, run_review, write_report
from gamelog import GameLog
from llm import DEFAULT_EFFORT, LLMClient, MockClient, Model, OpenRouterClient, load_api_key, parse_model
from moderator import Moderator
from night import run_night
from players import Players
from roles import DEFAULT_SETUP, ROLES, role_status_table
from events import PHASE
from state import setup_game

ROOT = Path(__file__).resolve().parent
RULES_PATH = ROOT / "rules_1.txt"
LOG_DIR = ROOT / "logs"


# Safeguard against games that never end (not a rule from rules_1.txt): by default a game stops
# after (number of players + EXTRA_DAYS) days, with no winner. Override with --max-days.
EXTRA_DAYS = 10
STALL_LIMIT = 6  # rules: everyone loses after three nights and three days with no deaths


def play_game(client: LLMClient, models: list[Model], moderator_model: Model, roles: list[str],
              seed: int | None, debrief: bool = False, flag_issues: bool = False,
              feedback_field: bool = False, review: bool = False, lessons: bool = False,
              max_days: int | None = None) -> Path:
    rng = random.Random(seed)
    prefix = "mock" if isinstance(client, MockClient) else "game"  # mock games say random filler text
    log = GameLog(LOG_DIR / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}_{seed}.jsonl")
    rules = RULES_PATH.read_text(encoding="utf-8")
    game = setup_game(roles, models, rng, log)
    players = Players(game, client, rules, feedback_field=feedback_field)
    moderator = Moderator(game, client, players, moderator_model, rules, flag_issues=flag_issues)
    for p in game.players:
        print(f"  {p.name:<8} {p.role:<17} {p.model.short}")

    max_days = max_days or len(roles) + EXTRA_DAYS
    while game.day <= max_days:
        # The stall rule is checked when a day begins; a winner is checked after every death,
        # i.e. after the day's execution and after the night's (simultaneous) deaths.
        if game.phases_without_death >= STALL_LIMIT:
            game.winners = []
            game.emit("Nobody died for three days and three nights. Everyone loses.")
            break
        print(f"Day {game.day}...")
        deaths_before = game.death_count()
        run_day(game, players)
        if (winners := game.check_winner()) is not None:
            game.winners = winners
            break
        print(f"Night {game.day}...")
        run_night(game, players, moderator)
        if (winners := game.check_winner()) is not None:
            # Reveal the night's deaths at a proper dawn before the game ends.
            game.phase = "day"
            game.emit(f"Day {game.day} begins.", cat=PHASE)
            game.announce_dawn()
            game.winners = winners
            break
        if game.death_count() == deaths_before:
            game.phases_without_death += 2
    else:
        game.winners = []
        game.emit(f"The game reached its limit of {max_days} days, a safeguard of this program rather "
                  "than a rule, so it ends with no winner.")

    winner_names = ", ".join(game.winners or []) or "nobody"
    game.emit(f"The game is over. Winners: {winner_names}.")
    print(f"Winners: {game.winners}")
    if debrief:
        print("Debriefing players and moderator...")
        run_debrief(game, players, moderator)
    if lessons:
        print("Collecting lessons from players...")
        lessons_file = LOG_DIR / ("mock_lessons.jsonl" if isinstance(client, MockClient) else "lessons.jsonl")
        run_lessons(game, players, lessons_file)
    if review:
        print("Reviewing the log...")
        run_review(game, client, moderator_model, rules, log.path.with_suffix(".txt"))
    log.write("result", winners=game.winners, days=game.day, cost=client.total_cost,
              roles={p.name: p.role for p in game.players},
              models={p.name: p.model.value for p in game.players})
    log.close()
    print(f"Cost by model: {client.total_cost}")
    print(f"Logs: {log.path} (+ .txt, .html)")
    if report := write_report(log.path):
        print(f"Feedback: {report}")
    return log.path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--players", default="haiku-5.5",
                    help="comma-separated models, cycled over the seats (seats are shuffled)")
    ap.add_argument("--moderator", default="opus-5.5")
    ap.add_argument("--roles", default=",".join(DEFAULT_SETUP), help="comma-separated role names")
    ap.add_argument("--effort", default=DEFAULT_EFFORT)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--max-days", type=int, default=None,
                    help=f"stop a game that runs this long, with no winner (default: players + {EXTRA_DAYS})")
    ap.add_argument("--mock", action="store_true", help="no API calls; random player outputs")
    ap.add_argument("--list-roles", action="store_true", help="print which roles are implemented, and how")
    fb = ap.add_argument_group("feedback from the models (written to logs/<game>_feedback.md); on by default, "
                             "turn one off with --no-<flag>")
    fb.add_argument("--debrief", action=argparse.BooleanOptionalAction, default=True, help="after the game, ask every player and the moderator "
                    "what was confusing, missing or broken")
    fb.add_argument("--mod-flags", action=argparse.BooleanOptionalAction, default=True, help="give the moderator a flag_issue tool for rules "
                    "ambiguities and missing tools during the game")
    fb.add_argument("--feedback-field", action=argparse.BooleanOptionalAction, default=True, help="add an optional out-of-game feedback field "
                    "to every player response")
    fb.add_argument("--lessons", action=argparse.BooleanOptionalAction, default=True, help="after the game, ask every player for tips they wish "
                    "they'd known; also appended to logs/lessons.jsonl across games for analysis")
    fb.add_argument("--review", action=argparse.BooleanOptionalAction, default=True, help="after the game, have the moderator model review the "
                    "whole log for problems")
    fb.add_argument("--rules-quiz", action="store_true", help="instead of a game, quiz the --players and "
                    "--moderator models on the rules (graded by the moderator model)")
    args = ap.parse_args()
    if args.list_roles:
        print(role_status_table())
        return

    roles = [r.strip() for r in args.roles.split(",")]
    unknown = [r for r in roles if r not in ROLES]
    if unknown:
        ap.error(f"unknown roles: {unknown}")
    models = [parse_model(m.strip()) for m in args.players.split(",")]
    seed = args.seed if args.seed is not None else random.randrange(10**6)
    client = MockClient(seed) if args.mock else OpenRouterClient(load_api_key(), effort=args.effort)
    if args.rules_quiz:
        moderator = parse_model(args.moderator)
        path = run_quiz(client, models + [moderator], moderator, RULES_PATH.read_text(encoding="utf-8"), LOG_DIR)
        print(f"Quiz results: {path}  Cost: {client.total_cost}")
        return
    play_game(client, models, parse_model(args.moderator), roles, seed, debrief=args.debrief,
              flag_issues=args.mod_flags, feedback_field=args.feedback_field, review=args.review,
              lessons=args.lessons, max_days=args.max_days)


if __name__ == "__main__":
    main()
