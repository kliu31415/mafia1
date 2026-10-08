"""OpenRouter client, the model list, and an offline mock client."""

import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
API_KEY_ENV_VAR = "OPENROUTER_API_KEY"


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


class LLMClient(Protocol):
    """What game code needs from a client: OpenRouterClient, MockClient, or a test's scripted client."""

    total_cost: dict[str, float]

    def chat(self, model: Model, messages: list[dict], *, tools: list[dict] | None = None,
             schema: dict | None = None, schema_name: str = "response") -> LLMReply: ...


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
    """Offline stand-in: random schema-valid answers for players; the moderator only carries out the
    Katana attack. Each answer is seeded by the seed and the prompt, not by call order, so a seed
    replays the same game even though players are asked in parallel threads."""

    def __init__(self, seed: int | None = None):
        self.seed = seed
        self.total_cost: dict[str, float] = {}

    def chat(self, model: Model, messages: list[dict], *, tools: list[dict] | None = None,
             schema: dict | None = None, schema_name: str = "response") -> LLMReply:
        rng = random.Random(f"{self.seed}|{model.value}|{json.dumps(messages, sort_keys=True)}")
        tool_calls = []
        content = None
        if tools:
            # Carry out the Katana attack (so mock games have night deaths), then end the phase.
            done = any(m.get("role") == "tool" for m in messages)
            args: dict[str, Any]
            name, args = ("end_phase", {"summary": "mock"}) if done else ("get_state", {})
            katana = re.search(r"Katana vote result: (\{.*?\})\n", messages[-1].get("content") or "")
            if not done and katana and (target := json.loads(katana[1]).get("attack")):
                name, args = "apply_changes", {"changes": [{"op": "kill", "player": target, "cause": "Katana"}]}
            tool_calls = [{"id": f"call_{rng.randrange(10**9)}", "type": "function",
                           "function": {"name": name, "arguments": json.dumps(args)}}]
        elif schema:
            content = json.dumps(self._sample(schema, rng))
        else:
            content = "ok"
        msg = {"role": "assistant", "content": content, "tool_calls": tool_calls or None}
        return LLMReply(content, None, tool_calls, msg, model.value, 0.0, {})

    def _sample(self, s: dict, rng: random.Random) -> Any:
        if "enum" in s:
            return rng.choice(s["enum"])
        if "anyOf" in s:
            return self._sample(rng.choice(s["anyOf"]), rng)
        t = s.get("type")
        if isinstance(t, list):
            # Mostly pick the non-null type so mocks actually do things.
            non_null = [x for x in t if x != "null"]
            t = "null" if rng.random() < 0.3 or not non_null else rng.choice(non_null)
        match t:
            case "object":
                return {k: self._sample(v, rng) for k, v in s.get("properties", {}).items()}
            case "array":
                return [self._sample(s["items"], rng) for _ in range(rng.randint(0, 1))]
            case "string":
                return rng.choice(["Hmm.", "I trust no one.", "Let's be careful today.", "blah " * 40,
                                        "long " * 900])
            case "integer":
                return rng.randint(s.get("minimum", 0), s.get("maximum", 1))
            case "boolean":
                return rng.random() < 0.5
            case _:
                return None
