"""OpenRouter client, the model list, and an offline mock client."""

import http.client
import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from collections.abc import Callable
from typing import Any, Protocol


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
API_KEY_ENV_VAR = "OPENROUTER_API_KEY"


class Model(str, Enum):
    """OpenRouter model ids. All of these accept every reasoning.effort in EFFORTS (OpenRouter maps
    them to each provider's setting). The cheap ones are for testing the harness."""

    OPUS_5_5 = "anthropic/claude-opus-5.5"
    SONNET_5_5 = "anthropic/claude-sonnet-5.5"
    GPT_6_1_SOL = "openai/gpt-6.1-sol"
    # GEMINI_4_ARGON = "google/gemini-4-argon"  # Google's frontier model (Sep 30, 2026); not on OpenRouter as
    #     of 2026-10-09. When it is: uncomment, add it to MODEL_SHORT_NAMES and to STRENGTH in tips.py (5).
    GROK_4_7 = "x-ai/grok-4.7"
    QWEN_3_8_MAX_PRIME = "qwen/qwen3.8-max-prime"  # same weights as QWEN_3_8_MAX at twice the price
    QWEN_3_8_MAX = "qwen/qwen3.8-max-0902"
    KIMI_K3 = "moonshotai/kimi-k3"
    GLM_5_3 = "z-ai/glm-5.3"
    GEMINI_3_8_FLASH = "google/gemini-3.8-flash"
    # Cheap models for smoke tests.
    HAIKU_5_5 = "anthropic/claude-haiku-5.5"
    GPT_6_LUNA = "openai/gpt-6-luna"
    # Cheap models tried 2026-10-09 on one real Day 2 turn and one night action each (seconds, $ per call):
    # DeepSeek V4.1 Flash 8-11 s/$0.002-0.004, Luna Pro 14-23 s/$0.0025; sensible play. Turned down: Qwen 3.8
    # Flash and GLM-5.3 Flash (ran out of tokens, unparsable answers), Seed 2.1 Turbo (90-100 s a call), Nemotron
    # 3.5 Lightning and Command A+ (claimed their role and announced their target in public chat on Day 2),
    # Mistral Large 4 ($0.01 a call, about 70 s). Solar Pro 4 and MiMo V2.6 Flash passed the test but in their
    # first game (2026-10-09) often filled strict-schema answers with runs of tabs or whitespace up to the token
    # limit (unparsable, minutes per call), so they were dropped. DeepSeek V4.1 Flash does the same less often:
    # 4 of 65 calls (2 fell back after the retry) in game_20261009_160331_601852, via Together; 36 replays of
    # that game's turns all parsed on Together, DeepInfra and Fireworks, so it isn't one provider's grammar.
    DEEPSEEK_V4_1_FLASH = "deepseek/deepseek-v4.1-flash"
    GPT_6_LUNA_PRO = "openai/gpt-6-luna-pro"

    @property
    def short(self) -> str:
        return MODEL_SHORT_NAMES[self]


MODEL_SHORT_NAMES = {
    Model.OPUS_5_5: "opus-5.5",
    Model.SONNET_5_5: "sonnet-5.5",
    Model.GPT_6_1_SOL: "gpt-6.1-sol",
    Model.GROK_4_7: "grok-4.7",
    Model.QWEN_3_8_MAX_PRIME: "qwen-3.8-max-prime",
    Model.QWEN_3_8_MAX: "qwen-3.8-max",
    Model.KIMI_K3: "kimi-k3",
    Model.GLM_5_3: "glm-5.3",
    Model.GEMINI_3_8_FLASH: "gemini-3.8-flash",
    Model.HAIKU_5_5: "haiku-5.5",
    Model.GPT_6_LUNA: "gpt-6-luna",
    Model.DEEPSEEK_V4_1_FLASH: "deepseek-v4.1-flash",
    Model.GPT_6_LUNA_PRO: "gpt-6-luna-pro",
}


# The one OpenRouter provider each model maker's models use: the maker's own endpoint (all support
# structured outputs, tools and reasoning; checked 2026-10-09). Letting OpenRouter pick caused trouble:
# its Azure route for Claude refuses any output schema with a "thoughts" field as distillation (Ivan's
# player_errors in game_20261009_004910_895267). Moonshot's own Kimi endpoint costs more than the
# cheapest hosts ($3/$15 vs about $0.75/$13 per million tokens), which run quantized versions.
PROVIDERS = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "google": "Google AI Studio",
    "x-ai": "xAI",
    "qwen": "Alibaba",
    "moonshotai": "Moonshot AI",
    "z-ai": "Together",  # the exception: Z.AI's own endpoint doesn't take structured outputs (2026-10-09)
    "deepseek": "Together",  # DeepSeek's own endpoint doesn't take structured outputs either (2026-10-09)
}


def parse_model(name: str) -> Model:
    for m in Model:
        if name in (m.short, m.value, m.name.lower()):
            return m
    raise ValueError(f"Unknown model {name!r}; choose from {[m.short for m in Model]}")


DEFAULT_EFFORT = "medium"  # for a model missing from MODEL_EFFORT
# reasoning.effort values OpenRouter accepts for every model (it maps them to each provider's own
# setting; checked 2026-10-08: anything else is rejected with HTTP 400).
EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True)
class ModelSpec:
    """A model plus its reasoning effort; effort None means the client's default (--effort, else the
    model's own default_effort)."""

    model: Model
    effort: str | None = None

    def __str__(self) -> str:
        return self.model.short + (f":{self.effort}" if self.effort else "")


def parse_model_spec(text: str) -> ModelSpec:
    """'opus-5.5' or 'opus-5.5:high'."""
    name, _, effort = text.strip().partition(":")
    if effort and effort not in EFFORTS:
        raise ValueError(f"Unknown effort {effort!r} in {text!r}; choose from {list(EFFORTS)}")
    return ModelSpec(parse_model(name), effort or None)
# Each model's reasoning effort when nothing sets one (a model:effort spec or --effort). From one real
# day-2 speaking turn (~12-18k-token prompt), 3 runs per model and effort, 2026-10-09. Medium -> high:
#   model          s/turn     output tokens (reasoning)   extra $ per seat in a 12p game (~50 calls)
#   opus-5.5       19 -> 21   1214 (461) -> 1687 (840)    +$0.47 (+18%)
#   sonnet-5.5      7 -> 16    495 (0)   -> 1773 (1256)   +$0.64 (+58%)  no reasoning at all at medium
#   gpt-6.1-sol    25 -> 42    825 (101) -> 1689 (1002)   +$0.43 (+45%)  barely reasons at medium
#   glm-5.3        20 -> 20    518 (97)  -> 3270 (2290)   +$0.60
#   kimi-k3        92 -> 118  3010       -> 3434          +$0.32 (+35%)
#   grok-4.7       93 -> 136  4995       -> 7976          +$0.89 (+40%)
#   qwen-3.8-max   72 -> 552  2556       -> 14621         ~5x; hit the 16k max_tokens cap with no answer on
#                                                         1 of 3 runs, so Qwen stays at medium
#   gemini-3.8-flash 25 -> 84 2390 (1736)-> 11098 (10482) +$1.80 (~4x); low: 8 s, 402 (0). High nears the
#                                                         16k cap and scores no better (AA index 40 vs 41), so medium
#   haiku-5.5      10 -> 23   1276 (800) -> 4158 (3470)   +$0.07
#   gpt-6-luna     19 -> 33   1272 (891) -> 2449 (2070)   +$0.03
# Times are with 12 requests at once. Speaking turns run one at a time (~260 in a 7-day 12p game), so
# s/turn sets a game's length: Grok and Kimi seats are slow at any effort. Artificial Analysis'
# Intelligence Index (Oct 2026) also rises with effort, e.g. Sonnet 5.5 41 at medium, 47 high, 56 max.
MODEL_EFFORT = {m: "high" for m in Model} | {Model.QWEN_3_8_MAX: "medium", Model.QWEN_3_8_MAX_PRIME: "medium",
                                              Model.GEMINI_3_8_FLASH: "medium", Model.DEEPSEEK_V4_1_FLASH: "medium"}


def default_effort(model: Model) -> str:
    return MODEL_EFFORT.get(model, DEFAULT_EFFORT)


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
    # Why an empty answer is empty, e.g. "finish_reason content_filter via Azure: <refusal text>".
    stop_note: str | None = None


def clean_json(x: Any) -> Any:
    """Parsed JSON with each string made encodable: a lone UTF-16 surrogate (e.g. half of an emoji, which
    JSON's \\ud83d allows) becomes U+FFFD, instead of failing whenever the text is written to a file."""
    if isinstance(x, str):
        return x.encode("utf-8", "surrogatepass").decode("utf-8", "replace") if any(
            "\ud800" <= ch <= "\udfff" for ch in x) else x
    if isinstance(x, list):
        return [clean_json(v) for v in x]
    if isinstance(x, dict):
        return {clean_json(k): clean_json(v) for k, v in x.items()}
    return x


JSON_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def schema_errors(value: object, schema: dict, path: str = "answer") -> list[str]:
    """Where a JSON answer breaks its schema (the subset our schemas use: type, enum, properties, required,
    additionalProperties, items, anyOf, minimum, maximum). Providers are asked for strict structured output,
    but one that ignores it would otherwise feed the game an unknown name or a missing field."""
    if "anyOf" in schema:
        options = [schema_errors(value, s, path) for s in schema["anyOf"]]
        return [] if any(not e for e in options) else min(options, key=len)
    t = schema.get("type")
    if t == "integer":
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif t == "number":
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    else:
        ok = t is None or isinstance(value, JSON_TYPES[t]) and not (t != "boolean" and isinstance(value, bool))
    if not ok:
        return [f"{path} should be {t}, not {json.dumps(value)[:60]}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path} is {json.dumps(value)[:60]}, not one of {schema['enum']}"]
    if isinstance(value, (int, float)) and not schema.get("minimum", value) <= value <= schema.get("maximum", value):
        return [f"{path} is {value}, outside {schema.get('minimum')}..{schema.get('maximum')}"]
    errors = []
    if isinstance(value, dict):
        props = schema.get("properties", {})
        errors += [f"{path} is missing {k!r}" for k in schema.get("required", []) if k not in value]
        if schema.get("additionalProperties") is False:
            errors += [f"{path} has an unknown field {k!r}" for k in value if k not in props]
        for k, v in value.items():
            if k in props:
                errors += schema_errors(v, props[k], f"{path}.{k}")
    if isinstance(value, list) and "items" in schema:
        for i, v in enumerate(value):
            errors += schema_errors(v, schema["items"], f"{path}[{i}]")
    return errors


def answer_json(reply: LLMReply, schema: dict | None = None) -> Any:
    """The JSON answer of a structured-output call. An empty or unparsable answer, or one that breaks
    `schema`, raises RuntimeError saying why (a refusal, the token limit, ...)."""
    if not reply.content:
        raise RuntimeError(f"empty answer ({reply.stop_note or 'no reason given'})")
    try:
        out = clean_json(json.loads(reply.content))
    except json.JSONDecodeError as e:  # e.g. cut off at the token limit
        raise RuntimeError(f"unparsable answer ({e}; {reply.stop_note}): {reply.content[-200:]!r}") from None
    if schema and (errors := schema_errors(out, schema)):
        raise RuntimeError(f"the answer doesn't match its schema: {'; '.join(errors[:5])}")
    return out


class LLMClient(Protocol):
    """What game code needs from a client: OpenRouterClient, MockClient, or a test's scripted client."""

    total_cost: dict[str, float]

    def chat(self, model: Model, messages: list[dict], *, tools: list[dict] | None = None,
             schema: dict | None = None, schema_name: str = "response", effort: str | None = None) -> LLMReply:
        """effort: reasoning effort for this call (one of EFFORTS); None means the client's default."""
        ...


# Makers whose models cache only prompt prefixes ending at a cache_block. Results of real calls on
# 2026-10-09 (repeated ~5-9k-token prompts through each maker's own provider; no need to re-test soon):
# - Claude (Haiku 5.5): caches up to marked blocks only. With just one mark at the end of the prompt it
#   wrote the cache on every call (1.25x input price) and never read it, since history grows mid-prompt.
#   Marks on shared parts (the rules) hit across players.
# - Gemini (3.8 Flash): no implicit caching at all; with a mark, ~100% hits, cheap writes. Seems to use only
#   the last mark (a different player's call hit only its own block).
# - OpenAI (Luna, 6.1 Sol): automatic, but only the whole system message is reused, never part of a later
#   message, and content blocks or splitting into more messages don't change that. Writes cost 1.25x.
#   cache_control is accepted and ignored.
# - Qwen 3.8 Max, Kimi K3: automatic prefix caching, ~5120 of ~5300 tokens hit on the second call.
# - Grok 4.7: unreliable. Repeats of an identical prompt hit 1152, 0 or the full ~6270 tokens at random
#   (likely depends on which server takes the request); prompt_cache_key and `user` didn't help.
# - GLM-5.3 (via Together): automatic but patchy; a repeat of the same player's prompt missed while another
#   player's call hit the shared rules (5184 tokens). Not worth marks: Together ignores them.
CACHE_MARKERS = ("anthropic", "google")


def cache_block(text: str) -> dict:
    """A text block that ends a cacheable prompt prefix. Claude caches a prefix only if it ends exactly
    where an earlier call marked one (at most 4 marks per request, 5-minute TTL), so mark the ends of
    parts that many calls repeat: the rules (shared by players, moderator and judge), then each
    caller's stable parts. Models of makers outside CACHE_MARKERS get plain strings (flat_messages):
    they cache on their own (OpenAI only the system message, so stable text goes there)."""
    return {"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}


def rules_system(rules: str, rest: str | list[dict]) -> dict:
    """A system message that starts with the rules, cached on their own so every call can share them."""
    tail = [{"type": "text", "text": f"\n\n---\n\n{rest}"}] if isinstance(rest, str) else rest
    return {"role": "system", "content": [cache_block(rules), *tail]}


def text_of(content: Any) -> Any:
    """A message's content as one string, if it's a list of text blocks."""
    if isinstance(content, list) and all(isinstance(b, dict) and b.get("type") == "text" for b in content):
        return "".join(b["text"] for b in content)
    return content


def flat_messages(messages: list[dict]) -> list[dict]:
    return [{**m, "content": text_of(m["content"])} if "content" in m else m for m in messages]


# Structured outputs (strict JSON schemas) stay on for every call, by choice (2026-10-09): the schema is the
# model's only description of an answer's format (prompts don't repeat it), and it limits fields such as a
# vote, a target or a role guess to valid names, so near-misses ("Alice (dead)", "Medic?") don't cost a
# retry, which in sequential speaking turns delays the whole game. schema_errors + one retry still check
# every answer, so a provider without strict mode could fall back to a schema described in the prompt.
# Providers that haven't played nice with strict schemas, found in live games and test calls:
# - Azure (an OpenRouter route for Claude) refused any schema with a "thoughts" field as distillation and
#   the player silently did nothing (game_20261009_004910_895267). Fixed by PROVIDERS pinning Anthropic.
# - Gemini answers HTTP 400 "invalid argument" (no reason given) to anyOf [enum, null] once the enum has
#   more than ~20 values; every night action failed (game_20261009_084630_739772). flat_nullable_enums.
# - Claude rejects that flat form ({"type": ["string", "null"], "enum": [..., null]}), so only Gemini gets it;
#   Grok, Qwen, Kimi, GLM and OpenAI accept both.
# - Z.AI's own GLM endpoint doesn't support structured outputs at all; GLM goes through Together.
# - Not a schema problem but looks like one: a model that reasons past max_tokens returns an empty or
#   cut-off answer (Qwen 3.8 Max and nearly Gemini Flash at high effort; see MODEL_EFFORT).
# Gemini's limit was found by testing (5-20 values fine, 30+ rejected); its error text never says why.

# Anthropic's distillation filter (seen 2026-10-09, game_20261009_084630_739772): Claude answers can come back empty
# or cut off with finish_reason content_filter and "...reverse engineering or duplicating model outputs" (no cost).
# It runs on Anthropic's side; neither OpenRouter nor a BYOK key can turn it off. It hit 3 of ~300 Claude calls
# in a 12-player Opus/Sonnet/Sol/Flash/Haiku game (all Opus: 2 moderator calls, 1 player answer), and none of
# ~2000 Claude calls in earlier Haiku/Luna games. It's intermittent: the same request replayed 8 times was never
# blocked. Likely triggers are prompts full of other models' text and answers that write out reasoning, so player
# answers have no "thoughts" field and the moderator never gets players' private fields (gamelog v23). Handling:
# a blocked moderator call is retried unchanged, then the moderator switches to its fallback model (moderator.py);
# a blocked player answer is retried once, then the default answer is used.
# Reasoning that comes back (player_call "reasoning"), measured 2026-10-09 at default effort: every model reasons
# on every call (36/36 test calls; at medium effort Sonnet 5.5 didn't reason at all). Claude returns summarized
# thinking, Gemini thought summaries, Grok/Qwen/Kimi their reasoning text. OpenAI (Sol, Luna) returns only
# encrypted reasoning, plus a summary on about 1 call in 8 even with reasoning.summary "auto" or "detailed",
# so every player answer has a "reason" field for the logs: why the player chose it.
# Players give a long "reason" by default (players.LONG_REASON_NOTE: a dense paragraph of up to ~150 words, with
# the options weighed, reads and plan), since for a model whose reasoning doesn't come back it's all we see of its
# thinking. Kevin (2026-10-09) would rather get API errors (alerted, retried, checkpointed) than lose that content,
# so a model gets the short note (players.REASON_NOTE) only when it's in SHORT_REASON below: its full reasoning
# comes back, or its API filters strictly. In game 121338 (Haiku/Luna) the short "reason" had a median of 18 words
# against 88 for returned reasoning, which held the alternatives and reads that "reason" left out. The long note
# asks for an explanation of a choice already made, not a transcript of reasoning. A new model gets the long one
# until it's checked.


# Models whose players give the short "reason" (see the note above). Claude: its thinking comes back summarized,
# and long written-out reasoning in answers is a likely trigger of Anthropic's distillation filter. Grok, Qwen and
# Kimi: their reasoning text comes back in full. Not here, so long: OpenAI (encrypted reasoning, a summary on about
# 1 call in 8), Gemini (brief thought summaries only) and GLM (not checked).
SHORT_REASON = frozenset({Model.OPUS_5_5, Model.SONNET_5_5, Model.HAIKU_5_5, Model.GROK_4_7,
                          Model.QWEN_3_8_MAX_PRIME, Model.QWEN_3_8_MAX, Model.KIMI_K3})


def flat_nullable_enums(schema: Any) -> Any:
    """Gemini rejects (HTTP 400) a nullable enum written as anyOf [enum, null] once the enum has more than
    about 20 values (e.g. guessed_role, a role name), but takes {"type": ["string", "null"], "enum": [..., null]}.
    Claude rejects that form, so only Gemini's requests get it (checked 2026-10-09)."""
    if isinstance(schema, list):
        return [flat_nullable_enums(x) for x in schema]
    if not isinstance(schema, dict):
        return schema
    options = schema.get("anyOf")
    if (isinstance(options, list) and len(options) == 2 and {"type": "null"} in options and len(schema) == 1):
        enum = next(o for o in options if o != {"type": "null"})
        if set(enum) == {"type", "enum"} and isinstance(enum["type"], str):
            return {"type": [enum["type"], "null"], "enum": [*enum["enum"], None]}
    return {k: flat_nullable_enums(v) for k, v in schema.items()}


def byok_cost(usage: dict) -> float | None:
    """What a call cost, or None if the answer didn't say. With BYOK (the account's own provider key), OpenRouter's
    `cost` is only its own fee and the provider bills the rest, reported as upstream_inference_cost; count both,
    so games compare the same whoever pays."""
    cost = usage.get("cost")
    upstream = (usage.get("cost_details") or {}).get("upstream_inference_cost")
    if usage.get("is_byok") and upstream is not None:
        return float(cost or 0) + float(upstream)
    return None if cost is None else float(cost)


RETRY_CODES = (408, 429, 500, 502, 503, 504)  # HTTP statuses (or error codes in an answer) worth retrying


class OpenRouterClient:
    def __init__(self, api_key: str, effort: str | None = None, max_tokens: int = DEFAULT_MAX_TOKENS,
                 timeout: float = 600, retries: int = 4):
        self.api_key = api_key
        self.effort = effort
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.retries = retries
        self.total_cost: dict[str, float] = {}
        self.cost_lock = threading.Lock()  # chat() is called from several threads
        # Told about problems that don't stop a request: on_error(kind, summary, **fields), e.g. a retry.
        # The game logs them with GameLog.error.
        self.on_error: Callable[..., None] | None = None

    def chat(self, model: Model, messages: list[dict], *, tools: list[dict] | None = None,
             schema: dict | None = None, schema_name: str = "response", effort: str | None = None) -> LLMReply:
        body: dict[str, Any] = {
            "model": model.value,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "reasoning": {"effort": effort or self.effort or default_effort(model)},
            "usage": {"include": True},
        }
        if model.value.split("/")[0] not in CACHE_MARKERS:
            body["messages"] = flat_messages(messages)  # others cache prefixes by themselves
        body["provider"] = {"order": [PROVIDERS[model.value.split("/")[0]]], "allow_fallbacks": False}
        if tools:
            body["tools"] = tools
        if schema:
            if model.value.startswith("google/"):
                schema = flat_nullable_enums(schema)
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            }
        data = self._post(body)
        if not isinstance(data, dict) or "error" in data:
            raise RuntimeError(f"OpenRouter error from {model.value}: "
                               f"{data.get('error') if isinstance(data, dict) else data!r:.300}")
        if not data.get("choices"):
            raise RuntimeError(f"OpenRouter answer from {model.value} has no choices: {json.dumps(data)[:300]}")
        choice = data["choices"][0]
        msg = choice["message"]
        usage = data.get("usage") or {}
        cost = byok_cost(usage)
        # The cost tables would quietly undercount; a blocked answer (content_filter) is free and reported anyway.
        if cost is None and self.on_error and choice.get("finish_reason") != "content_filter":
            self.on_error("api_error", f"a {model.value} answer reported no cost, so it counts as $0",
                          model=model.value, usage=usage)
        cost = cost or 0.0
        with self.cost_lock:
            self.total_cost[model.value] = self.total_cost.get(model.value, 0) + cost
        return LLMReply(
            content=msg.get("content"),
            reasoning=msg.get("reasoning"),
            tool_calls=msg.get("tool_calls") or [],
            message=msg,
            model=data.get("model", model.value),
            cost=cost,
            usage=usage,
            stop_note=(f"finish_reason {choice.get('finish_reason')} via {data.get('provider')}: "
                       f"{msg.get('refusal') or 'no refusal text'}"),
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
                    data = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:500]
                if e.code in RETRY_CODES and attempt < self.retries:
                    self._retrying(body, attempt, f"HTTP {e.code}: {detail}")
                    continue
                raise RuntimeError(f"OpenRouter HTTP {e.code}: {detail}") from None
            # A dropped or cut-off connection while reading the answer (urllib only wraps errors while
            # sending in URLError), or a body that isn't JSON (e.g. a proxy's HTML error page).
            except (OSError, http.client.HTTPException, json.JSONDecodeError, UnicodeDecodeError) as e:
                if attempt < self.retries:
                    self._retrying(body, attempt, f"{type(e).__name__}: {e}")
                    continue
                raise RuntimeError(f"OpenRouter request failed after {attempt + 1} attempts: "
                                   f"{type(e).__name__}: {e}") from e
            error = data.get("error") if isinstance(data, dict) else {"message": f"not a JSON object: {data!r:.200}"}
            if error and attempt < self.retries and (not isinstance(error, dict) or error.get("code") in RETRY_CODES):
                self._retrying(body, attempt, f"error in the answer: {json.dumps(error)[:300]}")
                continue  # e.g. the provider failed partway through generating
            return data
        raise AssertionError("unreachable")

    def _retrying(self, body: dict, attempt: int, error: str) -> None:
        if self.on_error:
            self.on_error("api_retry", f"a {body['model']} request failed (attempt {attempt + 1}), retrying: "
                          f"{error[:300]}", model=body["model"], attempt=attempt)
        time.sleep(2 ** (attempt + 1))


class MockClient:
    """Offline stand-in: random schema-valid answers for players; the moderator only carries out the
    Katana attack. Each answer is seeded by the seed and the prompt, not by call order, so a seed
    replays the same game even though players are asked in parallel threads."""

    def __init__(self, seed: int | None = None):
        self.seed = seed
        self.total_cost: dict[str, float] = {}

    def chat(self, model: Model, messages: list[dict], *, tools: list[dict] | None = None,
             schema: dict | None = None, schema_name: str = "response", effort: str | None = None) -> LLMReply:
        messages = flat_messages(messages)
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
                name, args = "apply_changes", {"changes": [{"op": "kill", "player": target, "cause": "Katana",
                                                           "by": json.loads(katana[1])["holder"], "katana": True}]}
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
            case "number":
                return rng.random()
            case "boolean":
                return rng.random() < 0.5
            case _:
                return None
