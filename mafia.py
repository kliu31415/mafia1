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
    roles.py       role definitions and the default setup
    state.py       game state, events with visibility, deaths, win checks
    players.py     player prompts, output schemas, notepads
    day.py         speaking budget, chat turns, nominations, votes
    night.py       Yakuza chat, night actions, Katana vote
    moderator.py   LLM moderator and its tools
    gamelog.py     JSONL log plus live .txt; log_viewer.py renders .txt/.html

Usage:
    uv run mafia.py --mock                                   # offline run, no API calls
    uv run mafia.py --players haiku-5.5,gpt-6-luna --moderator haiku-5.5
"""

import argparse
import random
from datetime import datetime
from pathlib import Path

from day import run_day
from gamelog import GameLog
from llm import DEFAULT_EFFORT, MockClient, Model, OpenRouterClient, load_api_key, parse_model
from moderator import Moderator
from night import run_night
from players import Players
from roles import DEFAULT_SETUP, ROLES
from state import setup_game

ROOT = Path(__file__).resolve().parent
RULES_PATH = ROOT / "rules_1.txt"
LOG_DIR = ROOT / "logs"


MAX_DAYS = 10
STALL_LIMIT = 6  # rules: everyone loses after three nights and three days with no deaths


def play_game(client, models: list[Model], moderator_model: Model, roles: list[str],
              seed: int | None) -> Path:
    rng = random.Random(seed)
    prefix = "mock" if isinstance(client, MockClient) else "game"  # mock games say random filler text
    log = GameLog(LOG_DIR / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}_{seed}.jsonl")
    rules = RULES_PATH.read_text(encoding="utf-8")
    game = setup_game(roles, models, rng, log)
    players = Players(game, client, rules)
    moderator = Moderator(game, client, players, moderator_model, rules)
    for p in game.players:
        print(f"  {p.name:<8} {p.role:<17} {p.model.short}")

    while game.day <= MAX_DAYS:
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
            game.announce_dawn()  # reveal the night's deaths before the game ends
            game.winners = winners
            break
        if game.death_count() == deaths_before:
            game.phases_without_death += 2

    print(f"Winners: {game.winners}")
    log.write("result", winners=game.winners, days=game.day, cost=client.total_cost,
              roles={p.name: p.role for p in game.players},
              models={p.name: p.model.value for p in game.players})
    log.close()
    print(f"Cost by model: {client.total_cost}")
    print(f"Logs: {log.path} (+ .txt, .html)")
    return log.path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--players", default="haiku-5.5",
                    help="comma-separated models, cycled over the seats (seats are shuffled)")
    ap.add_argument("--moderator", default="haiku-5.5")
    ap.add_argument("--roles", default=",".join(DEFAULT_SETUP), help="comma-separated role names")
    ap.add_argument("--effort", default=DEFAULT_EFFORT)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--mock", action="store_true", help="no API calls; random player outputs")
    args = ap.parse_args()

    roles = [r.strip() for r in args.roles.split(",")]
    unknown = [r for r in roles if r not in ROLES]
    if unknown:
        ap.error(f"unknown roles: {unknown}")
    models = [parse_model(m.strip()) for m in args.players.split(",")]
    seed = args.seed if args.seed is not None else random.randrange(10**6)
    client = MockClient(seed) if args.mock else OpenRouterClient(load_api_key(), effort=args.effort)
    play_game(client, models, parse_model(args.moderator), roles, seed)


if __name__ == "__main__":
    main()
