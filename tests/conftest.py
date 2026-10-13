"""Test helpers: a scripted LLM client and a game with known seats and roles."""

import json
import random
import re
from collections.abc import Callable, Collection
from pathlib import Path

import pytest

import records
from gamelog import GameLog
from llm import LLMReply, Model, flat_messages
from moderator import Moderator
from players import Players
from roles import ROLES, Alignment
from state import Game, setup_game

FAKE_HOME = Path("/home/someuser")


@pytest.fixture(autouse=True)
def fake_home(monkeypatch):
    """Every test runs with the same made-up home folder, so none depends on who runs it or where: logs replace
    the home folder's path with "~" (records.redact), and pytest's tmp_path is under the real one on Windows."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: FAKE_HOME))
    records.home_dirs.cache_clear()
    yield
    records.home_dirs.cache_clear()


def pytest_addoption(parser):
    parser.addoption("--update-prompts", action="store_true",
                     help="rewrite the prompt snapshots in tests/prompts/ (test_prompts.py) instead of comparing")
    parser.addoption("--update-versions", action="store_true",
                     help="record the current log and checkpoint fields in tests/versions.json (test_versions.py), "
                     "after bumping LOG_VERSION or CHECKPOINT_VERSION")


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
    queued tool calls in order, then ends the phase (at night, recording no visits first unless it did)."""

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
            if name == "end_phase" and "Resolve Night" in json.dumps(messages[:2]) and not any(
                    c["function"]["name"] == "record_visits" for m in messages for c in m.get("tool_calls") or []):
                name, args = "record_visits", {"visits": []}  # unless the test recorded them
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

def apply_ops(game: Game, players: Players, *changes: dict) -> dict:
    """Has a scripted moderator apply these apply_changes ops at once (raises ValueError if they're refused)."""
    return Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)").dispatch(
        "apply_changes", {"changes": list(changes)})


def told(game: Game, name: str) -> list[str]:
    """The texts of the private events (results, notices) `name` has been shown, oldest first."""
    return [e.text for e in game.events if e.visible_to is not None and name in e.visible_to]


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
