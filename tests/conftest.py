"""Test helpers: a scripted LLM client and a game with known seats and roles."""

import json
import random
import re
from collections.abc import Callable, Collection

import pytest

from gamelog import GameLog
from llm import LLMReply, Model, flat_messages
from players import Players
from roles import ROLES, Alignment
from state import Game, setup_game

def pytest_addoption(parser):
    parser.addoption("--update-prompts", action="store_true",
                     help="rewrite the prompt snapshots in tests/prompts/ (test_prompts.py) instead of comparing")


# decide(player name, or None for a non-player call such as the night check, task, schema) -> the fields
# to set in the answer, or None for defaults
Decide = Callable[[str | None, str, dict], dict | None]


def default_answer(schema: dict):
    """The 'do nothing' answer for a schema: null where allowed, else empty/false/first option."""
    if "anyOf" in schema:
        return None if {"type": "null"} in schema["anyOf"] else default_answer(schema["anyOf"][0])
    if "enum" in schema:
        return schema["enum"][0]
    match schema.get("type"):
        case "object":
            return {k: default_answer(v) for k, v in schema.get("properties", {}).items()}
        case "array":
            return []
        case "string":
            return ""
        case "integer":
            return 0
        case "boolean":
            return False
    return None


class ScriptedClient:
    """Players answer with defaults unless decide() overrides fields. The moderator makes the
    queued tool calls in order, then ends the phase."""

    def __init__(self, decide: Decide | None = None, moderator_calls: list[tuple[str, dict]] | None = None):
        self.decide = decide or (lambda name, task, schema: None)
        self.moderator_calls = list(moderator_calls or [])
        self.total_cost: dict[str, float] = {}
        self.asked: list[tuple[str, str]] = []  # (player, task) for every player call
        self.efforts: list[tuple[str, str | None]] = []  # (player name, "moderator" or "other"; effort) per call

    def chat(self, model: Model, messages: list[dict], *, tools: list[dict] | None = None,
             schema: dict | None = None, schema_name: str = "response", effort: str | None = None) -> LLMReply:
        messages = flat_messages(messages)
        if tools:
            self.efforts.append(("moderator", effort))
            name, args = self.moderator_calls.pop(0) if self.moderator_calls else ("end_phase", {"summary": ""})
            calls = [{"id": f"call_{len(messages)}", "type": "function",
                      "function": {"name": name, "arguments": json.dumps(args)}}]
            msg = {"role": "assistant", "content": None, "tool_calls": calls}
            return LLMReply(None, None, calls, msg, model.value, 0.0, {})
        assert schema is not None
        match = re.search(r"You are (\w+) \(seat", messages[0]["content"])
        player = match[1] if match else None  # None: not a player, e.g. the night check's judge
        task = messages[-1]["content"].rsplit("---\n\n", 1)[-1]
        self.efforts.append((player or "other", effort))
        if player:
            self.asked.append((player, task))
        out = default_answer(schema)
        out.update({k: v for k, v in (self.decide(player, task, schema) or {}).items() if k in out})
        content = json.dumps(out)
        return LLMReply(content, None, [], {"role": "assistant", "content": content}, model.value, 0.0, {})


def make_game(tmp_path, roles: list[str], client: ScriptedClient | None = None) -> tuple[Game, Players]:
    """A game whose seats are Alice, Bob, Carol, ... with exactly these roles in this order.
    The Katana starts with the first Yakuza."""
    log = GameLog(tmp_path / "test.jsonl")
    game = setup_game(roles, [Model.HAIKU_5_5], random.Random(0), log)
    for p, role in zip(game.players, roles):
        p.role, p.start_role, p.tokens, p.status = role, role, dict(ROLES[role].tokens), {}
    yakuza = [p.name for p in game.players if p.info.alignment is Alignment.EVIL]
    game.katana_holder = yakuza[0] if yakuza else None
    return game, Players(game, client or ScriptedClient(), rules="(rules)")


@pytest.fixture
def game_factory(tmp_path):
    return lambda roles, client=None: make_game(tmp_path, roles, client)


# Shared by several test files.

VILLAGE5 = ["Vanilla Villager"] * 5
TOWN4_GRUNT = ["Vanilla Villager"] * 4 + ["Grunt"]  # run_day needs two factions alive, or the game is over


def votes(guilty_for: Collection[str] = (), nominate: dict[str, str] | None = None):
    """A decide() where everyone votes Yes/Guilty on the given nominees, and the given players
    nominate once each."""
    nominated = set()

    def decide(name, task, schema):
        if "vote" in schema["properties"]:
            return {"vote": any(f"nominated {n}." in task or f"{n} is on trial" in task for n in guilty_for)}
        if nominate and name in nominate and name not in nominated and "nominate" in schema["properties"]:
            nominated.add(name)
            return {"nominate": nominate[name]}
        return None
    return decide
