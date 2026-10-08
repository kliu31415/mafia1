"""Test helpers: a scripted LLM client and a game with known seats and roles."""

import json
import random
import re
from collections.abc import Callable

import pytest

from gamelog import GameLog
from llm import LLMReply, Model
from players import Players
from roles import ROLES, Alignment
from state import Game, setup_game

# decide(player name, task, schema) -> the fields to set in that player's answer, or None for defaults
Decide = Callable[[str, str, dict], dict | None]


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

    def chat(self, model: Model, messages: list[dict], *, tools: list[dict] | None = None,
             schema: dict | None = None, schema_name: str = "response") -> LLMReply:
        if tools:
            name, args = self.moderator_calls.pop(0) if self.moderator_calls else ("end_phase", {"summary": ""})
            calls = [{"id": f"call_{len(messages)}", "type": "function",
                      "function": {"name": name, "arguments": json.dumps(args)}}]
            msg = {"role": "assistant", "content": None, "tool_calls": calls}
            return LLMReply(None, None, calls, msg, model.value, 0.0, {})
        assert schema is not None
        player = re.search(r"You are (\w+) \(seat", messages[0]["content"])[1]
        task = messages[-1]["content"].rsplit("---\n\n", 1)[-1]
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
        p.role, p.tokens, p.status = role, dict(ROLES[role].tokens), {}
    yakuza = [p.name for p in game.players if p.info.alignment is Alignment.EVIL]
    game.katana_holder = yakuza[0] if yakuza else None
    return game, Players(game, client or ScriptedClient(), rules="(rules)")


@pytest.fixture
def game_factory(tmp_path):
    return lambda roles, client=None: make_game(tmp_path, roles, client)
