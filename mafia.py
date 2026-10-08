"""Scaffolding for LLM-played games of the Mafia variant in rules_1.txt.

Design: code owns the game state, the RNG and who can see which message. Day phases (chat,
nominations, votes) run in code. Night actions are collected from players as structured output,
then an LLM moderator resolves them through tools (get_state, apply_changes, random_choice, tell,
ask_player, end_phase), since the role interactions are too varied to hand-code yet.

All LLM calls go through OpenRouter. The API key is read from the OPENROUTER_API_KEY
environment variable.

Usage:
    uv run mafia.py --mock                                   # offline run, no API calls
    uv run mafia.py --players haiku-5.5,gpt-6-luna --moderator haiku-5.5
"""

import argparse
import json
import os
import random
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import log_viewer

ROOT = Path(__file__).resolve().parent
RULES_PATH = ROOT / "rules_1.txt"
LOG_DIR = ROOT / "logs"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
API_KEY_ENV_VAR = "OPENROUTER_API_KEY"


# ---------------------------------------------------------------------------------------------
# Models and the OpenRouter client
# ---------------------------------------------------------------------------------------------


class Model(str, Enum):
    """OpenRouter model ids. All of these accept reasoning.effort = "medium" (checked against
    GET /api/v1/models on 2026-10-08). The cheap ones are for testing the harness."""

    OPUS_5_5 = "anthropic/claude-opus-5.5"
    SONNET_5_5 = "anthropic/claude-sonnet-5.5"
    GPT_6_1_SOL = "openai/gpt-6.1-sol"
    GEMINI_3_1_PRO = "google/gemini-3.1-pro-preview"
    GROK_4_7 = "x-ai/grok-4.7"
    QWEN_3_8_MAX = "qwen/qwen3.8-max-prime"
    # Cheap models for smoke tests.
    HAIKU_5_5 = "anthropic/claude-haiku-5.5"
    GPT_6_LUNA = "openai/gpt-6-luna"

    @property
    def short(self) -> str:
        return MODEL_SHORT_NAMES[self]


MODEL_SHORT_NAMES = {
    Model.OPUS_5_5: "opus-5.5",
    Model.SONNET_5_5: "sonnet-5.5",
    Model.GPT_6_1_SOL: "gpt-6.1-sol",
    Model.GEMINI_3_1_PRO: "gemini-3.1-pro",
    Model.GROK_4_7: "grok-4.7",
    Model.QWEN_3_8_MAX: "qwen-3.8-max",
    Model.HAIKU_5_5: "haiku-5.5",
    Model.GPT_6_LUNA: "gpt-6-luna",
}


def parse_model(name: str) -> Model:
    for m in Model:
        if name in (m.short, m.value, m.name.lower()):
            return m
    raise ValueError(f"Unknown model {name!r}; choose from {[m.short for m in Model]}")


DEFAULT_EFFORT = "medium"
DEFAULT_MAX_TOKENS = 16_000  # reasoning + answer; Anthropic needs this above the reasoning budget


def load_api_key() -> str:
    """Read the OpenRouter key from the environment. Never print the result."""
    key = os.environ.get(API_KEY_ENV_VAR, "").strip()
    if not key:
        raise SystemExit(
            f"{API_KEY_ENV_VAR} is not set. Set it to your OpenRouter API key, e.g.\n"
            f"  PowerShell (this session):  $env:{API_KEY_ENV_VAR} = \"sk-or-...\"\n"
            f"  PowerShell (persistent):    setx {API_KEY_ENV_VAR} \"sk-or-...\"  (then open a new terminal)\n"
            f"  bash:                       export {API_KEY_ENV_VAR}=sk-or-...\n"
            "Or pass --mock to run without API calls."
        )
    return key


@dataclass
class LLMReply:
    content: str | None
    reasoning: str | None
    tool_calls: list[dict]
    message: dict  # raw assistant message, sent back as-is in tool loops (keeps reasoning_details)
    model: str
    cost: float
    usage: dict


class OpenRouterClient:
    def __init__(self, api_key: str, effort: str = DEFAULT_EFFORT, max_tokens: int = DEFAULT_MAX_TOKENS,
                 timeout: float = 600, retries: int = 4):
        self.api_key = api_key
        self.effort = effort
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.retries = retries
        self.total_cost: dict[str, float] = {}

    def chat(self, model: Model, messages: list[dict], *, tools: list[dict] | None = None,
             schema: dict | None = None, schema_name: str = "response") -> LLMReply:
        body: dict[str, Any] = {
            "model": model.value,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "reasoning": {"effort": self.effort},
            "usage": {"include": True},
        }
        if model.value.startswith("anthropic/"):
            # Claude needs an opt-in for caching (other providers cache automatically). The top-level
            # field caches the prompt up to the last block, 5-minute TTL.
            body["cache_control"] = {"type": "ephemeral"}
        if tools:
            body["tools"] = tools
        if schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            }
        data = self._post(body)
        if "error" in data:
            raise RuntimeError(f"OpenRouter error from {model.value}: {data['error']}")
        msg = data["choices"][0]["message"]
        usage = data.get("usage", {})
        cost = float(usage.get("cost") or 0)
        self.total_cost[model.value] = self.total_cost.get(model.value, 0) + cost
        return LLMReply(
            content=msg.get("content"),
            reasoning=msg.get("reasoning"),
            tool_calls=msg.get("tool_calls") or [],
            message=msg,
            model=data.get("model", model.value),
            cost=cost,
            usage=usage,
        )

    def _post(self, body: dict) -> dict:
        req = urllib.request.Request(
            OPENROUTER_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-Title": "mafia1",
            },
        )
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:500]
                if e.code in (408, 429, 500, 502, 503, 504) and attempt < self.retries:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise RuntimeError(f"OpenRouter HTTP {e.code}: {detail}") from None
            except (urllib.error.URLError, TimeoutError):
                if attempt < self.retries:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise
        raise AssertionError("unreachable")


class MockClient:
    """Offline stand-in: random schema-valid answers for players, a no-op moderator."""

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        self.total_cost: dict[str, float] = {}

    def chat(self, model: Model, messages: list[dict], *, tools: list[dict] | None = None,
             schema: dict | None = None, schema_name: str = "response") -> LLMReply:
        tool_calls = []
        content = None
        if tools:
            # Look at the state once, then end the phase.
            done = any(m.get("role") == "tool" for m in messages)
            name, args = ("end_phase", {"summary": "mock"}) if done else ("get_state", {})
            tool_calls = [{"id": f"call_{self.rng.randrange(10**9)}", "type": "function",
                           "function": {"name": name, "arguments": json.dumps(args)}}]
        elif schema:
            content = json.dumps(self._sample(schema))
        else:
            content = "ok"
        msg = {"role": "assistant", "content": content, "tool_calls": tool_calls or None}
        return LLMReply(content, None, tool_calls, msg, model.value, 0.0, {})

    def _sample(self, s: dict) -> Any:
        if "enum" in s:
            return self.rng.choice(s["enum"])
        if "anyOf" in s:
            return self._sample(self.rng.choice(s["anyOf"]))
        t = s.get("type")
        if isinstance(t, list):
            # Mostly pick the non-null type so mocks actually do things.
            non_null = [x for x in t if x != "null"]
            t = "null" if self.rng.random() < 0.3 or not non_null else self.rng.choice(non_null)
        match t:
            case "object":
                return {k: self._sample(v) for k, v in s.get("properties", {}).items()}
            case "array":
                return [self._sample(s["items"]) for _ in range(self.rng.randint(0, 1))]
            case "string":
                return self.rng.choice(["Hmm.", "I trust no one.", "Let's be careful today.", "blah " * 40,
                                        "long " * 900])
            case "integer":
                return self.rng.randint(s.get("minimum", 0), s.get("maximum", 1))
            case "boolean":
                return self.rng.random() < 0.5
            case _:
                return None


# ---------------------------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------------------------


class Alignment(str, Enum):
    GOOD = "Good"  # the Village faction
    EVIL = "Evil"  # the Yakuza faction
    NEUTRAL = "Neutral"  # each Neutral player is their own faction


@dataclass(frozen=True)
class RoleInfo:
    alignment: Alignment
    category: str
    sheriff_evil: bool  # how the role appears to a Sheriff, before Katana/Fabricator effects
    defense: str = "None"
    tokens: dict[str, int] = field(default_factory=dict)
    acts_at_night: bool = False


ROLES: dict[str, RoleInfo] = {
    # Village
    "Vanilla Villager": RoleInfo(Alignment.GOOD, "Townsfolk", False),
    "Sheriff": RoleInfo(Alignment.GOOD, "Investigative", False, acts_at_night=True),
    "Tracker": RoleInfo(Alignment.GOOD, "Investigative", False, acts_at_night=True),
    "Lookout": RoleInfo(Alignment.GOOD, "Investigative", False, acts_at_night=True),
    "Seer": RoleInfo(Alignment.GOOD, "Investigative", False, tokens={"seer": 1}, acts_at_night=True),
    "Fortune Teller": RoleInfo(Alignment.GOOD, "Investigative", False),
    "Oracle": RoleInfo(Alignment.GOOD, "Investigative", False, acts_at_night=True),
    "Medic": RoleInfo(Alignment.GOOD, "Combat", False, tokens={"medic": 2}, acts_at_night=True),
    "Trapper": RoleInfo(Alignment.GOOD, "Combat", False, acts_at_night=True),
    "Vigilante": RoleInfo(Alignment.GOOD, "Combat", False, tokens={"vigilante": 3}, acts_at_night=True),
    "Prosecutor": RoleInfo(Alignment.GOOD, "Misc", False, tokens={"prosecutor": 2}, acts_at_night=True),
    "Party Animal": RoleInfo(Alignment.GOOD, "Misc", False, acts_at_night=True),
    "Roleplayer": RoleInfo(Alignment.GOOD, "Outsider", False, acts_at_night=True),
    "Ex-Con": RoleInfo(Alignment.GOOD, "Outsider", True),
    "Cardinal": RoleInfo(Alignment.GOOD, "Outsider", False),
    # Yakuza
    "Grunt": RoleInfo(Alignment.EVIL, "Yakuza", True),
    "Pharmacist": RoleInfo(Alignment.EVIL, "Yakuza", True, acts_at_night=True),
    "Ritualist": RoleInfo(Alignment.EVIL, "Yakuza", True, tokens={"ritual": 2}, acts_at_night=True),
    "Puppeteer": RoleInfo(Alignment.EVIL, "Yakuza", True, tokens={"puppet": 1}, acts_at_night=True),
    "Fabricator": RoleInfo(Alignment.EVIL, "Yakuza", True, tokens={"fabricator": 1}, acts_at_night=True),
    "Clerk": RoleInfo(Alignment.EVIL, "Yakuza", True, tokens={"clerk": 1}, acts_at_night=True),
    "Diviner": RoleInfo(Alignment.EVIL, "Yakuza", True, acts_at_night=True),
    "Mortician": RoleInfo(Alignment.EVIL, "Yakuza", True, tokens={"mortician": 2}, acts_at_night=True),
    # Neutral
    "Serial Killer": RoleInfo(Alignment.NEUTRAL, "Neutral", False, defense="Standard", acts_at_night=True),
    "Arsonist": RoleInfo(Alignment.NEUTRAL, "Neutral", False, defense="Standard", acts_at_night=True),
    "Jester": RoleInfo(Alignment.NEUTRAL, "Neutral", True, defense="Basic"),
    "Executioner": RoleInfo(Alignment.NEUTRAL, "Neutral", True, defense="Basic"),
}

# Neutrals that never block a win (rules: "if we ignore Jesters and Executioners...").
NON_BLOCKING_ROLES = {"Jester", "Executioner"}

DEFAULT_SETUP = [
    "Sheriff", "Medic", "Lookout", "Vigilante", "Vanilla Villager", "Vanilla Villager",
    "Grunt", "Pharmacist", "Fabricator",
    "Jester",
]

PLAYER_NAMES = ["Alice", "Bob", "Carol", "Dave", "Erin", "Frank", "Grace", "Heidi", "Ivan", "Judy",
                "Mallory", "Niaj", "Olivia", "Peggy", "Rupert", "Sybil"]


# ---------------------------------------------------------------------------------------------
# Game state
# ---------------------------------------------------------------------------------------------


@dataclass
class Player:
    name: str
    seat: int
    model: Model
    role: str
    alive: bool = True
    tokens: dict[str, int] = field(default_factory=dict)
    status: dict[str, Any] = field(default_factory=dict)  # free-form flags, e.g. doused, fake_role
    last_will: str = ""
    notepad: str = ""  # private notes the player keeps across turns
    speaking_budget: float = 0.0

    @property
    def info(self) -> RoleInfo:
        return ROLES[self.role]

    @property
    def faction(self) -> str:
        match self.info.alignment:
            case Alignment.GOOD:
                return "Village"
            case Alignment.EVIL:
                return "Yakuza"
            case _:
                return f"Neutral:{self.name}"


@dataclass
class Event:
    """Something that happened, and who may see it. visible_to=None means public."""

    day: int
    phase: str
    text: str
    visible_to: frozenset[str] | None = None

    def visible(self, name: str) -> bool:
        return self.visible_to is None or name in self.visible_to


class GameLog:
    """Writes every event and LLM call as one JSON line, for later analysis, plus a live
    human-readable .txt next to it. close() also renders an expandable .html view."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.f = path.open("w", encoding="utf-8")
        self.txt = path.with_suffix(".txt").open("w", encoding="utf-8")

    def write(self, kind: str, **data: Any) -> None:
        line = json.dumps({"t": time.time(), "kind": kind, **data}, default=str)
        self.f.write(line + "\n")
        self.f.flush()
        if (text := log_viewer.text_line(json.loads(line))) is not None:
            self.txt.write(text + "\n")
            self.txt.flush()

    def close(self) -> None:
        self.f.close()
        self.txt.close()
        log_viewer.render_html(self.path)


@dataclass
class Game:
    players: list[Player]  # in circle (seat) order
    rng: random.Random
    log: GameLog
    day: int = 1
    phase: str = "day"
    events: list[Event] = field(default_factory=list)
    katana_holder: str | None = None
    phases_without_death: int = 0  # day and night phases since the last death
    winners: list[str] | None = None
    pending_announcements: list[str] = field(default_factory=list)
    pending_deaths: list[tuple[str, str]] = field(default_factory=list)  # (name, cause), revealed at dawn
    personal_winners: list[str] = field(default_factory=list)  # Jester / Executioner
    pending_revenge: list[tuple[str, list[str]]] = field(default_factory=list)  # (source, Guilty voters)

    # --- lookups --------------------------------------------------------------------------

    def player(self, name: str) -> Player:
        for p in self.players:
            if p.name == name:
                return p
        raise KeyError(name)

    def alive(self) -> list[Player]:
        return [p for p in self.players if p.alive]

    def alive_names(self) -> list[str]:
        return [p.name for p in self.alive()]

    def death_count(self) -> int:
        return sum(not p.alive and not p.status.get("left") for p in self.players)

    def yakuza(self) -> list[Player]:
        return [p for p in self.alive() if p.info.alignment is Alignment.EVIL]

    def clockwise_from(self, name: str) -> list[Player]:
        """Alive players in circle order, starting at `name` (who must be alive)."""
        alive = self.alive()
        i = next(i for i, p in enumerate(alive) if p.name == name)
        return alive[i:] + alive[:i]

    # --- events ---------------------------------------------------------------------------

    def emit(self, text: str, visible_to: list[str] | set[str] | None = None, kind: str = "event") -> None:
        """kind="notice" marks events that the readable logs skip (they duplicate another event)."""
        vis = frozenset(visible_to) if visible_to is not None else None
        self.events.append(Event(self.day, self.phase, text, vis))
        self.log.write(kind, day=self.day, phase=self.phase, text=text,
                       visible_to=sorted(vis) if vis is not None else "all")

    def history_for(self, name: str) -> str:
        lines = []
        for e in self.events:
            if e.visible(name):
                lines.append(f"[Day {e.day} {e.phase}] {e.text}")
        return "\n".join(lines) if lines else "(nothing yet)"

    # --- state changes ----------------------------------------------------------------------

    def kill(self, name: str, cause: str, public: bool = True,
             guilty_voters: list[str] | None = None) -> None:
        """guilty_voters is set only for an execution by hanging."""
        p = self.player(name)
        if not p.alive:
            return
        p.alive = False
        hanged = guilty_voters is not None
        if hanged and p.role == "Jester":
            self.personal_winners.append(name)
            self.pending_revenge.append((name, guilty_voters))
        for exe in self.alive():
            if exe.role == "Executioner" and exe.status.get("target") == name:
                if hanged:
                    self.personal_winners.append(exe.name)
                    self.pending_revenge.append((exe.name, guilty_voters))
                    exe.alive = False  # leaves the game; not a death
                    exe.status["left"] = True
                    self.emit(f"{exe.name} was the Executioner, whose target was {name}. "
                              f"They win and leave the game.")
                else:
                    # Our reading of "if you die of other means": the target dying otherwise.
                    exe.role = "Jester"
                    self.emit("Your target died other than by hanging. You are now a Jester.", [exe.name])
        self.phases_without_death = 0
        self.log.write("death", player=name, role=p.role, cause=cause, day=self.day, phase=self.phase)
        if not public:
            pass  # caller (e.g. moderator after a Mortician clean) announces it differently
        elif self.phase == "night":
            # Revealed at dawn, so a will forged later the same night still applies.
            self.pending_deaths.append((name, cause))
        else:
            self.emit(self.death_reveal(name, cause))
        if self.katana_holder == name:
            remaining = self.yakuza()
            self.katana_holder = self.rng.choice(remaining).name if remaining else None
            if self.katana_holder:
                self.emit(f"The Katana passed to {self.katana_holder}.", [y.name for y in remaining])
        # TODO: Cardinal.

    def announce_dawn(self) -> None:
        """Publicly reveal the night's deaths and queued announcements."""
        for name, cause in self.pending_deaths:
            self.emit(self.death_reveal(name, cause))
        self.pending_deaths.clear()
        for text in self.pending_announcements:
            self.emit(text)
        self.pending_announcements.clear()

    def death_reveal(self, name: str, cause: str) -> str:
        p = self.player(name)
        if p.status.get("cleaned"):
            return f"{name} died. Their role and last will were cleaned by a Mortician."
        reveal = f"{name} died ({cause}). Their role was {p.role}."
        if p.last_will:
            reveal += f" Last will: {p.last_will!r}"
        return reveal

    def resolve_revenge(self) -> None:
        """Jester / Executioner revenge: a Divine Attack on a random Guilty voter, the night after."""
        for source, voters in self.pending_revenge:
            targets = [v for v in voters if self.player(v).alive]
            if targets:
                victim = self.rng.choice(targets)
                self.log.write("revenge", source=source, victim=victim)
                self.kill(victim, f"{self.player(source).role}'s revenge")
        self.pending_revenge.clear()

    def check_winner(self) -> list[str] | None:
        """Called at the start of each day. Returns the winning player names, or None.
        Jester / Executioner wins are personal: they don't end the game, but are added at the end."""
        alive = self.alive()
        blocking = {p.faction for p in alive if p.role not in NON_BLOCKING_ROLES}
        if len(blocking) <= 1:
            faction = next(iter(blocking), None)
            return [p.name for p in self.players if faction and p.faction == faction] + self.personal_winners
        return None

    def public_state(self) -> dict:
        return {
            "day": self.day,
            "phase": self.phase,
            "players": [{"name": p.name, "seat": p.seat, "alive": p.alive,
                         "revealed_role": None if p.alive else p.role} for p in self.players],
        }

    def full_state(self) -> dict:
        """Everything, for the moderator."""
        return {
            "day": self.day,
            "phase": self.phase,
            "katana_holder": self.katana_holder,
            "players": [{
                "name": p.name, "seat": p.seat, "alive": p.alive, "role": p.role, "faction": p.faction,
                "base_defense": p.info.defense, "sheriff_appears_evil": p.info.sheriff_evil,
                "tokens": p.tokens, "status": p.status, "last_will": p.last_will,
            } for p in self.players],
        }


def setup_game(roles: list[str], models: list[Model], rng: random.Random, log: GameLog) -> Game:
    if len(models) > len(roles):
        raise ValueError(f"{len(roles)} roles but {len(models)} models")
    models = [models[i % len(models)] for i in range(len(roles))]  # cycle models over the seats
    names = PLAYER_NAMES[:len(roles)]
    shuffled = roles[:]
    rng.shuffle(shuffled)
    seat_models = models[:]
    rng.shuffle(seat_models)
    players = [Player(n, i, m, r, tokens=dict(ROLES[r].tokens))
               for i, (n, m, r) in enumerate(zip(names, seat_models, shuffled))]
    game = Game(players, rng, log)
    yakuza = game.yakuza()
    if yakuza:
        game.katana_holder = rng.choice(yakuza).name
    for p in players:
        if p.role == "Executioner":
            p.status["target"] = rng.choice([q.name for q in players if q is not p])
        if p.role == "Roleplayer":
            p.status["fake_role"] = rng.choice(
                [r for r, i in ROLES.items() if i.category == "Investigative"])
    log.write("setup", players=[{"name": p.name, "seat": p.seat, "model": p.model.value, "role": p.role,
                                 "status": p.status} for p in players], katana=game.katana_holder)
    return game


# ---------------------------------------------------------------------------------------------
# Players: prompts and structured outputs
# ---------------------------------------------------------------------------------------------

# Speaking budget. A message costs round_multiplier * (MESSAGE_BASE_COST + length_cost(words)),
# times PRIVATE_COST_FACTOR if private. Players earn BUDGET_PER_ROUND each round, carrying over up
# to BUDGET_MAX; the budget resets to 0 each day.
BUDGET_PER_ROUND = 2.5
BUDGET_MAX = 8.0
MESSAGE_BASE_COST = 1.0
PRIVATE_COST_FACTOR = 0.25
MAX_MESSAGE_WORDS = 800
FULL_PRICE_ROUNDS = 3  # rounds at 1x; each later round costs ROUND_COST_GROWTH times the previous
ROUND_COST_GROWTH = 2.0
MAX_DAY_ROUNDS = 10  # the day also ends after a full go-around in which nobody sends a message
FREE_DEFENSE_WORDS = 150  # the accused's first message on trial is free up to this length
MIN_TRUNCATED_WORDS = 3  # a message truncated below this is dropped instead
MAX_TRIALS_PER_DAY = 3
NOMINATION_COST = 1.0  # times the round multiplier, paid from the speaking budget; deters spam

YAKUZA_CHAT_ROUNDS = 3
YAKUZA_MESSAGE_WORDS = 200  # Yakuza chat is free but each message is capped at this length
LAST_WILL_WORDS = 300  # longer wills are truncated
NOTEPAD_WORDS = 300  # longer notepads are truncated


def word_count(text: str) -> int:
    return len(text.split())


def length_cost(words: int) -> float:
    """Cheap for short and medium messages, superlinear for long ones."""
    return words / 60 + (words / 200) ** 2


def round_multiplier(rnd: int) -> float:
    """rnd is 1-based."""
    return ROUND_COST_GROWTH ** max(0, rnd - FULL_PRICE_ROUNDS)


def message_cost(words: int, rnd: int, private: bool, free_words: int = 0) -> float:
    if words == 0:
        return 0.0
    cost = MESSAGE_BASE_COST + length_cost(words)
    if free_words:
        cost = 0.0 if words <= free_words else length_cost(words) - length_cost(free_words)
    return cost * round_multiplier(rnd) * (PRIVATE_COST_FACTOR if private else 1.0)


def truncate_words(text: str, words: int) -> str:
    return " ".join(text.split()[:words]) + " [truncated]"


def price_table(rnd: int) -> str:
    rows = [f"  {w:>3} words: public {message_cost(w, rnd, False):.2f}, private {message_cost(w, rnd, True):.2f}"
            for w in (10, 25, 50, 100, 200, 400, MAX_MESSAGE_WORDS)]
    nxt = round_multiplier(rnd + 1)
    return (f"Message prices this round (round {rnd}, {round_multiplier(rnd):.2f}x; next round "
            f"{nxt:.2f}x):\n" + "\n".join(rows))


def nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def obj(**props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


STR = {"type": "string"}
BOOL = {"type": "boolean"}


def name_enum(names: list[str]) -> dict:
    return {"type": "string", "enum": names}


def day_turn_schema(game: Game, me: str, can_nominate: bool) -> dict:
    others = [n for n in game.alive_names() if n != me]
    props = {
        "thoughts": STR,  # private scratchpad, never shown to other players
        "public_message": nullable(STR),
        "private_messages": {"type": "array", "items": obj(to=name_enum(others), text=STR)},
    }
    if can_nominate:
        props["nominate"] = nullable(name_enum(game.alive_names()))
    return obj(**props)


VOTE_SCHEMA = obj(thoughts=STR, vote=BOOL)
LAST_WILL_SCHEMA = obj(last_will=STR)
ANSWER_SCHEMA = obj(answer=STR)


def night_action_schema(game: Game, p: Player) -> dict:
    """One generic shape for every role; the moderator interprets it using the rules."""
    names = game.alive_names()
    props = {
        "thoughts": STR,
        "act": BOOL,
        "target": nullable(name_enum(names)),
        "second_target": nullable(name_enum(names)),
        "guessed_role": nullable(name_enum(list(ROLES))),
        "tokens_to_spend": {"type": "integer"},
        "details": STR,  # anything else the action needs, e.g. "ignite" or a forged last will
    }
    if p.info.alignment is Alignment.EVIL:
        yakuza = [y.name for y in game.yakuza()]
        props["katana_vote_holder"] = name_enum(yakuza)
        props["katana_vote_target"] = nullable(name_enum(names))
    return obj(**props)


def role_briefing(game: Game, p: Player) -> str:
    lines = [f"You are {p.name} (seat {p.seat})."]
    if p.role == "Roleplayer":
        lines.append(f"Your role is {p.status['fake_role']}.")  # they're told the fake role
    else:
        lines.append(f"Your role is {p.role} ({p.info.alignment.value}).")
    if p.tokens:
        lines.append(f"Your tokens: {p.tokens}.")
    if p.info.alignment is Alignment.EVIL:
        team = ", ".join(f"{y.name} ({y.role})" for y in game.players if y.info.alignment is Alignment.EVIL)
        lines.append(f"Yakuza members: {team}. Katana holder: {game.katana_holder}.")
    if p.role == "Executioner":
        lines.append(f"Your target is {p.status['target']}.")
    return " ".join(lines)


def player_messages(game: Game, p: Player, rules: str, task: str) -> list[dict]:
    order = ", ".join(f"{q.name}{'' if q.alive else ' (dead)'}" for q in game.players)
    system = (
        f"{rules}\n\n---\n\nYou are a player in this game. Your only goal is to win by your role's win "
        "condition. This is a social deduction game, so lying, bluffing, false role claims, misleading "
        "arguments and betraying people's trust are all legitimate tactics, and you should use them "
        "whenever they help you win. Nobody is harmed by in-game deception, and other players will "
        "deceive you too. Play to win, not to be agreeable or transparent. "
        f"Seating order (clockwise): {order}.\n{role_briefing(game, p)}"
    )
    notepad = p.notepad or "(empty)"
    user = (f"Everything you have seen so far:\n{game.history_for(p.name)}\n\n---\n\n"
            f"Your private notepad (only you can see it; it carries over between turns):\n{notepad}\n\n"
            f"Every response has a 'notepad' field: set it to replace your notepad (max {NOTEPAD_WORDS} "
            "words; longer is truncated), or null to keep it as is. Use it for plans, suspicions and "
            f"anything you want to remember.\n\n---\n\n{task}")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def with_notepad(schema: dict) -> dict:
    """Adds the 'notepad' field every player response carries."""
    return {**schema, "properties": {**schema["properties"], "notepad": nullable(STR)},
            "required": [*schema["required"], "notepad"]}


class Players:
    """Asks player LLMs for decisions. Retries once on unparsable output, then uses a fallback."""

    def __init__(self, game: Game, client, rules: str):
        self.game = game
        self.client = client
        self.rules = rules

    def ask(self, p: Player, task: str, schema: dict, fallback: dict) -> dict:
        messages = player_messages(self.game, p, self.rules, task)
        schema = with_notepad(schema)
        for attempt in range(2):
            try:
                reply = self.client.chat(p.model, messages, schema=schema)
                out = json.loads(reply.content or "")
                self.game.log.write("player_call", player=p.name, model=p.model.value, task=task,
                                    output=out, reasoning=reply.reasoning, cost=reply.cost,
                                    usage=reply.usage)
                if isinstance(note := out.pop("notepad", None), str):
                    p.notepad = truncate_words(note, NOTEPAD_WORDS) if word_count(note) > NOTEPAD_WORDS else note
                return out
            except (json.JSONDecodeError, RuntimeError) as e:
                self.game.log.write("player_error", player=p.name, attempt=attempt, error=str(e))
        return fallback

    def ask_many(self, jobs: list[tuple[Player, str, dict, dict]]) -> list[dict]:
        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(lambda j: self.ask(*j), jobs))


# ---------------------------------------------------------------------------------------------
# Day phase (runs in code)
# ---------------------------------------------------------------------------------------------


def run_day(game: Game, players: Players) -> None:
    game.phase = "day"
    game.emit(f"Day {game.day} begins.")
    game.announce_dawn()

    # Last wills, written once at the beginning of each day (including day 1).
    task = (f"Write or update your last will (max {LAST_WILL_WORDS} words). If you die, it is revealed "
            "to ALL players, including other factions.")
    outs = players.ask_many([(p, task, LAST_WILL_SCHEMA, {"last_will": p.last_will}) for p in game.alive()])
    for p, out in zip(game.alive(), outs):
        will = out["last_will"]
        p.last_will = truncate_words(will, LAST_WILL_WORDS) if word_count(will) > LAST_WILL_WORDS else will

    for p in game.alive():
        p.speaking_budget = 0.0
    trials = 0
    # TODO: Prosecutor trials, Clerk rigging and Puppeteer chat substitution happen here.
    for rnd in range(1, MAX_DAY_ROUNDS + 1):
        for p in game.alive():
            p.speaking_budget = min(BUDGET_MAX, p.speaking_budget + BUDGET_PER_ROUND)
        order = game.alive()
        game.rng.shuffle(order)
        active = False  # did anyone send a message or nominate this go-around?
        for p in order:
            if not p.alive:
                continue
            sent, nominee = chat_turn(game, players, p, rnd, can_nominate=trials < MAX_TRIALS_PER_DAY)
            active |= sent > 0 or nominee is not None
            if nominee:
                outcome = run_nomination(game, players, nominator=p, nominee=nominee, rnd=rnd)
                if outcome == "executed":
                    return  # an execution ends the day
                trials += outcome == "innocent"  # failed nominations don't count toward the limit
                if trials >= MAX_TRIALS_PER_DAY:
                    game.emit("Three trials ended in Innocent verdicts. The day ends.")
                    return
        if not active:
            game.emit("A full round passed with no messages. The day ends.")
            return
    game.emit("Discussion time is over. The day ends.")


def planned_messages(out: dict) -> list[tuple[str | None, str]]:
    """(recipient or None for public, text), public message first."""
    msgs: list[tuple[str | None, str]] = []
    if out.get("public_message"):
        msgs.append((None, out["public_message"]))
    msgs += [(pm["to"], pm["text"]) for pm in out.get("private_messages", []) if pm.get("text")]
    return msgs


def chat_turn(game: Game, players: Players, p: Player, rnd: int, can_nominate: bool,
              extra: str = "", free_defense: bool = False) -> tuple[int, str | None]:
    """One speaking turn. Returns (messages sent, nominee or None).

    If the planned messages cost more than the player's budget, they're warned and asked once to
    revise; anything still over budget is then truncated (later messages first) or dropped."""
    free_words = FREE_DEFENSE_WORDS if free_defense else 0

    def cost_of(i: int, to: str | None, words: int) -> float:
        return message_cost(words, rnd, private=to is not None, free_words=free_words if i == 0 and to is None else 0)

    nomination_fee = NOMINATION_COST * round_multiplier(rnd)

    def total_cost(out: dict) -> float:
        fee = nomination_fee if can_nominate and out.get("nominate") else 0.0
        return fee + sum(cost_of(i, to, min(word_count(t), MAX_MESSAGE_WORDS))
                         for i, (to, t) in enumerate(planned_messages(out)))

    task = (f"It is Day {game.day}, round {rnd} of at most {MAX_DAY_ROUNDS}. It's your turn. Your speaking "
            f"budget is {p.speaking_budget:.2f}; you earn {BUDGET_PER_ROUND:g} per round, carrying over "
            f"up to {BUDGET_MAX:g}, and it resets each day. You may send one public message and any "
            f"number of private messages (everyone sees who you messaged, but only the recipient sees "
            f"the contents), or nothing. Messages are "
            f"capped at {MAX_MESSAGE_WORDS} words. Prices grow each round after round {FULL_PRICE_ROUNDS}, "
            "so late messages are only worth it if important. The day ends after a full round where "
            "nobody sends a message.\n" + price_table(rnd) + "\n"
            + (f"Your first public message now is free up to {FREE_DEFENSE_WORDS} words; beyond that you "
               "pay only for the extra length.\n" if free_defense else "")
            + (f"You may nominate a player for trial, which stops chat for a vote. Nominating costs "
               f"{nomination_fee:.2f} from your budget this round and is paid before your messages.\n"
               if can_nominate else "")
            + extra)
    schema = day_turn_schema(game, p.name, can_nominate)
    fallback = {"thoughts": "", "public_message": None, "private_messages": [], "nominate": None}
    out = players.ask(p, task, schema, fallback)
    planned = total_cost(out)
    if planned > p.speaking_budget + 1e-9:
        nominating = f" plus a nomination of {out['nominate']}" if can_nominate and out.get("nominate") else ""
        warning = (f"\n\nWARNING: your planned messages {json.dumps(planned_messages(out))}{nominating} "
                   f"cost {planned:.2f}, but your budget is {p.speaking_budget:.2f}. Revise them to fit. "
                   "If you still can't afford a nomination it won't happen, and messages over budget will "
                   "be truncated, starting with your last message.")
        game.log.write("budget_warning", player=p.name, planned=planned, budget=p.speaking_budget)
        out = players.ask(p, task + warning, schema, fallback)

    nominee = out.get("nominate") if can_nominate else None
    if nominee:
        if nomination_fee <= p.speaking_budget + 1e-9:
            p.speaking_budget -= nomination_fee
        else:
            game.log.write("nomination_dropped", player=p.name, nominee=nominee, budget=p.speaking_budget)
            game.emit(f"You couldn't afford to nominate {nominee}.", [p.name])
            nominee = None
    sent = 0
    for i, (to, text) in enumerate(planned_messages(out)):
        if to is not None and to not in game.alive_names():
            continue
        words = min(word_count(text), MAX_MESSAGE_WORDS)
        while words > 0 and cost_of(i, to, words) > p.speaking_budget + 1e-9:
            words -= 1
        if words == 0 or (words < word_count(text) and words < MIN_TRUNCATED_WORDS):
            game.log.write("message_dropped", player=p.name, to=to, words=word_count(text))
            continue
        if words < word_count(text):
            text = truncate_words(text, words)
        p.speaking_budget -= cost_of(i, to, words)
        sent += 1
        if to is None:
            game.emit(f"{p.name} (public): {text}")
        else:
            game.emit(f"{p.name} -> {to} (private): {text}", [p.name, to])
            # Everyone else sees that the message happened, but not its contents.
            game.emit(f"{p.name} sent {to} a private message.",
                      [q.name for q in game.players if q.name not in (p.name, to)], kind="notice")
    return sent, nominee


def majority(yes: int, total: int) -> bool:
    return yes * 2 > total  # strictly more than half


def run_nomination(game: Game, players: Players, nominator: Player, nominee: str, rnd: int) -> str:
    """Nomination vote, then trial and verdict. Returns "failed", "innocent" or "executed".
    Both votes are simultaneous: every voter decides without seeing the others, then all votes
    are revealed together."""
    game.emit(f"{nominator.name} nominated {nominee}. Everyone now votes Yes/No simultaneously.")
    others = [v for v in game.clockwise_from(nominator.name) if v is not nominator]
    task = (f"{nominator.name} nominated {nominee}. Vote true (Yes) to put them on trial, false (No) "
            "otherwise. Voting is simultaneous: you can't see anyone else's vote, and all votes are "
            f"revealed publicly once everyone has voted. {nominator.name} votes Yes automatically.")
    outs = players.ask_many([(v, task, VOTE_SCHEMA, {"thoughts": "", "vote": False}) for v in others])
    yes_voters = [nominator.name] + [v.name for v, o in zip(others, outs) if o["vote"]]
    no_voters = [v.name for v, o in zip(others, outs) if not o["vote"]]
    game.emit(f"Nomination votes on {nominee}: Yes - {', '.join(yes_voters)}; "
              f"No - {', '.join(no_voters) or 'nobody'}.")
    if not majority(len(yes_voters), len(game.alive())):
        game.emit(f"The nomination of {nominee} failed ({len(yes_voters)} Yes).")
        return "failed"

    game.emit(f"{nominee} is put on trial ({len(yes_voters)} Yes).")
    accused = game.player(nominee)
    chat_turn(game, players, accused, rnd, can_nominate=False, free_defense=True,
              extra="You are on trial. Defend yourself; you speak first.")
    for p in game.clockwise_from(accused.name)[1:]:
        chat_turn(game, players, p, rnd, can_nominate=False, extra=f"{nominee} is on trial.")

    voters = game.alive()
    task = (f"{nominee} is on trial. Vote true for Guilty (execute), false for Innocent. Voting is "
            "simultaneous: you can't see anyone else's vote, and all votes are revealed publicly once "
            "everyone has voted.")
    outs = players.ask_many([(v, task, VOTE_SCHEMA, {"thoughts": "", "vote": False}) for v in voters])
    guilty = [v.name for v, o in zip(voters, outs) if o["vote"]]
    innocent = [v.name for v, o in zip(voters, outs) if not o["vote"]]
    game.emit(f"Trial votes on {nominee}: Guilty - {', '.join(guilty) or 'nobody'}; "
              f"Innocent - {', '.join(innocent) or 'nobody'}.")
    if majority(len(guilty), len(game.alive())):
        game.emit(f"{nominee} is executed by hanging ({len(guilty)} Guilty).")
        game.kill(nominee, "executed by hanging", guilty_voters=guilty)
        return "executed"
    game.emit(f"{nominee} is found Innocent ({len(guilty)} Guilty).")
    return "innocent"


# ---------------------------------------------------------------------------------------------
# Night phase (actions in code, resolution by the LLM moderator)
# ---------------------------------------------------------------------------------------------


def run_night(game: Game, players: Players, moderator: "Moderator") -> None:
    game.phase = "night"
    game.emit(f"Night {game.day} begins.")
    if len(game.yakuza()) > 1:
        yakuza_chat(game, players, YAKUZA_CHAT_ROUNDS,
                    "Discuss tonight's plan: who holds the Katana, who it attacks, and your other actions.")

    actors = [p for p in game.alive() if p.info.acts_at_night or p.info.alignment is Alignment.EVIL]
    jobs = []
    for p in actors:
        task = (f"It is Night {game.day}. Choose your night action for your role, following the rules. "
                "Set act=false to do nothing. Fill only the fields your role needs.")
        if p.info.alignment is Alignment.EVIL:
            task += " Also vote on who should hold the Katana and who the Katana should attack (or null)."
        jobs.append((p, task, night_action_schema(game, p), {"act": False}))
    actions = dict(zip([p.name for p in actors], players.ask_many(jobs)))
    game.log.write("night_actions", day=game.day, actions=actions, roles={p.name: p.role for p in actors})

    katana = tally_katana(game, actions)
    yakuza = game.yakuza()
    if katana["attack"] is None and len(yakuza) > 1:
        # No majority: show the votes, one more round of chat, then a Katana-only revote.
        votes = "; ".join(f"{y.name}: holder {actions[y.name].get('katana_vote_holder')}, target "
                          f"{actions[y.name].get('katana_vote_target')}" for y in yakuza)
        game.emit(f"The Katana vote had no majority, so there would be no attack. Votes: {votes}.",
                  [y.name for y in yakuza])
        yakuza_chat(game, players, 1, "Agree on the Katana holder and target before the revote.")
        names = game.alive_names()
        revote_schema = obj(thoughts=STR, katana_vote_holder=name_enum([y.name for y in yakuza]),
                            katana_vote_target=nullable(name_enum(names)))
        outs = players.ask_many([(y, "Revote on the Katana holder and the Katana target (or null).",
                                  revote_schema, {"katana_vote_holder": y.name, "katana_vote_target": None})
                                 for y in yakuza])
        for y, out in zip(yakuza, outs):
            actions[y.name].update(katana_vote_holder=out["katana_vote_holder"],
                                   katana_vote_target=out["katana_vote_target"])
        katana = tally_katana(game, actions)
    game.log.write("katana", day=game.day, result=katana)
    moderator.run_phase(
        f"Resolve Night {game.day}. Submitted night actions (JSON, keyed by player):\n"
        f"{json.dumps(actions, indent=1)}\n\nKatana vote result: {json.dumps(katana)}\n\n"
        "Resolve all actions simultaneously per the rules (visits, role-blocks, attack vs defense, "
        "investigation results, Katana appearing Not Evil, Fabricator framing, etc). Use apply_changes "
        "for deaths and token/status changes, tell() for each private result, and end_phase when done. "
        "Deaths you apply are announced publicly at dawn automatically, including the kill's cause, so "
        "make the cause just the source as the rules allow it to be known (e.g. 'Katana', 'Vigilante', "
        "'Serial Killer', 'Trap'); don't tell() deaths to all. Tell each role-blocked player that they "
        "were role-blocked. "
        "Jester/Executioner revenge attacks are handled by code after you finish. Tell all Yakuza which "
        "actions each Yakuza performed but not the results; only the attacker learns whether the "
        "Katana attack succeeded."
    )
    game.resolve_revenge()
    game.day += 1


def yakuza_chat(game: Game, players: Players, rounds: int, topic: str) -> None:
    """Free Yakuza chat in seat order. Ends early once everyone says they're ready."""
    yakuza = game.yakuza()
    names = [y.name for y in yakuza]
    schema = obj(thoughts=STR, message=nullable(STR), ready=BOOL)
    for rnd in range(1, rounds + 1):
        ready = []
        for y in yakuza:
            out = players.ask(
                y, f"It is Night {game.day}. Yakuza chat, round {rnd} of at most {rounds}. {topic} "
                f"Send a message (max {YAKUZA_MESSAGE_WORDS} words; longer is truncated) or null. Set "
                "ready=true if you have nothing more to discuss; chat ends when everyone is ready.",
                schema, {"thoughts": "", "message": None, "ready": True})
            if msg := out.get("message"):
                if word_count(msg) > YAKUZA_MESSAGE_WORDS:
                    msg = truncate_words(msg, YAKUZA_MESSAGE_WORDS)
                game.emit(f"{y.name} (Yakuza chat): {msg}", names)
            ready.append(out.get("ready", True))
        if all(ready):
            return


def tally_katana(game: Game, actions: dict[str, dict]) -> dict:
    yakuza = [y.name for y in game.yakuza()]
    if not yakuza:
        return {"attack": None, "holder": game.katana_holder}
    holders = [actions.get(y, {}).get("katana_vote_holder") for y in yakuza]
    targets = [actions.get(y, {}).get("katana_vote_target") for y in yakuza]
    holder = next((h for h in set(holders) if h and majority(holders.count(h), len(yakuza))), None)
    target = next((t for t in set(targets) if t and majority(targets.count(t), len(yakuza))), None)
    if holder is None or target is None:
        return {"attack": None, "holder": game.katana_holder, "note": "no majority agreement; no attack"}
    game.katana_holder = holder
    return {"attack": target, "holder": holder, "attack_level": "Standard"}


# ---------------------------------------------------------------------------------------------
# Moderator (LLM with tools)
# ---------------------------------------------------------------------------------------------


def tool(name: str, description: str, **params: dict) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": params, "required": list(params)},
    }}


MODERATOR_TOOLS = [
    tool("get_state", "Full hidden game state: roles, tokens, statuses, katana holder."),
    tool("apply_changes", "Apply state changes. Ops: {op:'kill', player, cause} | "
         "{op:'set_tokens', player, token, value} | {op:'set_status', player, key, value} "
         "(value null deletes the key) | {op:'set_katana', player} | {op:'set_last_will', player, text} "
         "(e.g. a Fabricator forgery). For a Mortician clean, use set_status key 'cleaned' value true; "
         "the dawn reveal then hides the role, will and cause. Night deaths are revealed at dawn with the last will as it is "
         "then, so the order of ops within a night doesn't matter.",
         changes={"type": "array", "items": {"type": "object"}}),
    tool("random_choice", "Pick k distinct items uniformly at random using the game's RNG. "
         "Always use this instead of choosing 'randomly' yourself.",
         options={"type": "array", "items": {"type": "string"}}, k={"type": "integer"}),
    tool("tell", "Send a message. to = list of player names, or ['all'] for a public announcement.",
         to={"type": "array", "items": {"type": "string"}}, text={"type": "string"}),
    tool("ask_player", "Ask one player a question and get their free-text answer.",
         player={"type": "string"}, question={"type": "string"}),
    tool("end_phase", "Finish this phase. The summary is private to the game log.",
         summary={"type": "string"}),
]

MAX_MODERATOR_STEPS = 40


class Moderator:
    def __init__(self, game: Game, client, players: Players, model: Model, rules: str):
        self.game = game
        self.client = client
        self.players = players
        self.model = model
        self.rules = rules

    def run_phase(self, instructions: str) -> None:
        messages = [
            {"role": "system", "content": f"{self.rules}\n\n---\n\nYou are the omniscient moderator of "
             "this game. Code stores the state and runs the day phase; you resolve what code can't "
             "by calling tools. Be exact about the rules. Never reveal hidden information except "
             "as the rules allow. A private result contains only what the rules say its recipient "
             "learns, worded neutrally: never explain why a result came out as it did (e.g. never "
             "mention the Katana, framing or defenses to an investigator), and never name an attacker "
             "or reveal roles beyond what the rules allow."},
            {"role": "user", "content": f"{instructions}\n\nCurrent full state (call get_state to "
             f"refresh after changes):\n{json.dumps(self.game.full_state())}\n\nPublic history so far:\n"
             f"{self.game.history_for('__moderator_public__')}"},
        ]
        for _ in range(MAX_MODERATOR_STEPS):
            reply = self.client.chat(self.model, messages, tools=MODERATOR_TOOLS)
            self.game.log.write("moderator_call", model=self.model.value, content=reply.content,
                                reasoning=reply.reasoning, tool_calls=reply.tool_calls, cost=reply.cost,
                                usage=reply.usage)
            messages.append(reply.message)
            if not reply.tool_calls:
                messages.append({"role": "user", "content": "Call end_phase when you are finished."})
                continue
            for call in reply.tool_calls:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                    result = self.dispatch(name, args)
                except Exception as e:  # report tool errors back to the moderator
                    result = {"error": f"{type(e).__name__}: {e}"}
                self.game.log.write("moderator_tool", name=name, args=call["function"].get("arguments"),
                                    result=result)
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)})
                if name == "end_phase":
                    return
        self.game.log.write("moderator_error", error="step limit reached")

    def dispatch(self, name: str, args: dict) -> Any:
        g = self.game
        match name:
            case "get_state":
                return g.full_state()
            case "apply_changes":
                for c in args["changes"]:
                    p = g.player(c["player"])
                    match c["op"]:
                        case "kill":
                            g.kill(p.name, c.get("cause", "killed"))
                        case "set_tokens":
                            p.tokens[c["token"]] = int(c["value"])
                        case "set_status":
                            if c.get("value") is None:
                                p.status.pop(c["key"], None)
                            else:
                                p.status[c["key"]] = c["value"]
                        case "set_last_will":
                            p.last_will = c["text"]
                        case "set_katana":
                            g.katana_holder = p.name
                        case op:
                            raise ValueError(f"unknown op {op!r}")
                return {"ok": True}
            case "random_choice":
                return {"chosen": g.rng.sample(args["options"], int(args.get("k", 1)))}
            case "tell":
                to = args["to"]
                if to == ["all"] and g.phase == "night":
                    g.pending_announcements.append(f"Moderator: {args['text']}")  # read out at dawn
                elif to == ["all"]:
                    g.emit(f"Moderator: {args['text']}")
                else:
                    for n in to:
                        g.player(n)  # validate names
                    g.emit(f"Moderator (private): {args['text']}", to)
                return {"ok": True}
            case "ask_player":
                p = g.player(args["player"])
                out = self.players.ask(p, f"The moderator asks: {args['question']}", ANSWER_SCHEMA,
                                       {"answer": ""})
                return out
            case "end_phase":
                return {"ok": True}
        raise ValueError(f"unknown tool {name!r}")


# ---------------------------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------------------------

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
