"""Claude models through the Claude Code CLI (`claude -p`), so their calls use a Claude subscription's quota
instead of OpenRouter credits (--claude-code: the default where the CLI is installed; --no-claude-code turns it
off). Other models still go through OpenRouter, so one game can mix both routes.

Each call is a fresh, non-interactive `claude -p` process: no tools (so no file access and nothing to leak), the
game's own system prompt in place of Claude Code's (only a short environment note is added: working directory,
platform, date), no CLAUDE.md, settings, skills, plugins, hooks or MCP servers (--safe-mode, an empty working
directory, and none of the parent Claude Code session's CLAUDE* variables), and no saved session. Answers come
back as structured output (--json-schema). Nothing persists between calls, so a crash on either side loses at most
the calls in flight; the game's checkpoints cover the rest (--resume).

How it differs from an OpenRouter call:
- The conversation is one prompt: the system messages become the system prompt, a single user message the prompt;
  anything longer (a retry after a bad answer, the moderator's tool loop) is written out as a transcript.
- Tools: the CLI can't take the game's function tools, so the moderator answers with JSON listing its tool calls
  (one schema with an anyOf entry per tool), and their results come back as the next part of the transcript.
- Prompt caching is the CLI's own: it marks the system prompt and the prompt (1-hour TTL on a subscription), so
  a player's stable system text is reused, but the moderator's growing transcript isn't.
- max_tokens is the CLI's; effort is passed as --effort (low..max; "none"/"minimal" become low).
- Cost: calls are paid by the subscription, so they count $0; the list price the CLI reports is kept in the call's
  usage as list_cost_usd, with the subscription windows' utilization (five_hour, seven_day) as plan_utilization.
- Thinking comes back summarized (--thinking-display summarized), like Claude's through the API.
- Effort: both paths send Anthropic's native effort level (5.5 models reject thinking budgets), but answering through
  the CLI's StructuredOutput tool, plus a closing turn after it, costs more output than the API's constrained JSON. On
  one real night-action prompt (3 runs each, 2026-10-11; output tokens, reasoning in brackets, API -> CLI): Opus high
  1168 (376) -> 1740 (418), medium 1015 (313) -> 1346 (278), so Opus thinks the same; Haiku high 1164 (971) ->
  2213 (1572), medium 685 (494) -> 1459 (900). On long day turns Haiku's gap was ~3x (5k output tokens a call vs
  ~1.8k in API games, 23 s vs 9 s a turn, game_20261011_085841_783834). So CLI Haiku at medium matches API Haiku at
  high; Opus needs no change.
"""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from typing import Any

from llm import LLMClient, LLMReply, MockClient, Model, default_effort, text_of

CLI_EFFORTS = ("low", "medium", "high", "xhigh", "max")
CALL_DEADLINE_S = 900  # one call, CLI start-up and its own API retries included (Opus turns took up to ~210 s)
RETRIES = 2  # a call that failed (no answer at all) is tried this many more times
MAX_PLAN_WAIT_S = 6 * 3600  # waits this long at most for a subscription limit to reset; longer stops the game
# The parent Claude Code session's variables (session id, remote-session settings, ...) would make the child act
# as part of that session and add its context; these are the ones the child needs to sign in.
KEEP_ENV = {"CLAUDE_SESSION_INGRESS_TOKEN_FILE", "CLAUDE_CONFIG_DIR"}

Runner = Callable[[list[str], str, dict[str, str], str, float], tuple[int, str, str]]


class PlanLimitError(BaseException):
    """The subscription's usage limit won't reset soon enough. A BaseException, so it isn't taken for a bad answer
    (players' answers fall back to defaults on Exception): it stops the game, which can be resumed (--resume)."""


def available() -> bool:
    """Whether the Claude Code CLI is installed here (a `claude` command on PATH): then games use it by default."""
    return shutil.which("claude") is not None


def routes(model: Model) -> bool:
    """Whether the CLI can run this model: Claude models."""
    return model.value.startswith("anthropic/")


def route(client: object, model: Model) -> str:
    """How a client runs a model's calls, recorded per player in the log (setup and result "via"): claude_code
    (the CLI), mock, or api (OpenRouter, or a test's scripted client). Claude players play somewhat differently
    through the CLI (see Effort above), so analysis keeps the two apart."""
    if isinstance(client, ClaudeCodeClient) and routes(model):
        return "claude_code"
    return "mock" if isinstance(client, MockClient) else "api"


def cli_model(model: Model) -> str:
    """The CLI's id for a model: anthropic/claude-opus-5.5 -> claude-opus-5-5."""
    return model.value.split("/", 1)[1].replace(".", "-")


def cli_effort(effort: str) -> str:
    return effort if effort in CLI_EFFORTS else "low"


def child_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items()
            if not (k.startswith("CLAUDE") and k not in KEEP_ENV) and k != "AI_AGENT"}


def run_cli(argv: list[str], stdin: str, env: dict[str, str], cwd: str, timeout: float) -> tuple[int, str, str]:
    p = subprocess.run(argv, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=env, cwd=cwd, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def tools_schema(tools: list[dict]) -> dict:
    """The answer schema for a call with tools: the calls to make, in order, each one tool's name and arguments."""
    options = []
    for t in tools:
        f = t["function"]
        options.append({"type": "object", "additionalProperties": False, "required": ["name", "arguments"],
                        "properties": {"name": {"type": "string", "enum": [f["name"]]},
                                       "arguments": f.get("parameters") or {"type": "object", "properties": {}}}})
    return {"type": "object", "additionalProperties": False, "required": ["tool_calls"],
            "properties": {"tool_calls": {"type": "array", "items": {"anyOf": options}}}}


def tools_note(tools: list[dict]) -> str:
    lines = [f"- {t['function']['name']}: {t['function'].get('description', '')}" for t in tools]
    return ("\n\n---\n\nTools: call them by answering with JSON whose tool_calls lists the calls to make, in order "
            "(each one's arguments are in the answer format). Their results come back in the next message. An "
            "empty list makes no calls.\n" + "\n".join(lines))


def transcript(messages: list[dict]) -> str:
    """The non-system messages as one prompt. A lone user message is sent as it is."""
    if len(messages) == 1 and messages[0]["role"] == "user":
        return str(text_of(messages[0]["content"]))
    names: dict[str, str] = {}
    parts = ["The conversation so far, oldest first; answer its last message."]
    for m in messages:
        if m["role"] == "user":
            parts.append(f"=== Message ===\n{text_of(m['content'])}")
        elif m["role"] == "assistant":
            calls = m.get("tool_calls") or []
            for c in calls:
                names[c["id"]] = c["function"]["name"]
            said = [f"{c['function']['name']}({c['function'].get('arguments') or '{}'})" for c in calls]
            parts.append("=== Your answer ===\n" + (text_of(m.get("content")) or "") + "".join(
                f"\n{s}" for s in (["Tool calls:", *said] if said else [])))
        elif m["role"] == "tool":
            parts.append(f"=== Result of {names.get(m.get('tool_call_id', ''), 'a tool call')} ===\n"
                         f"{text_of(m['content'])}")
    return "\n\n".join(parts)


def unquote_empty(x: Any) -> Any:
    """The answer with each string that is just a pair of quotes made empty. Through the CLI, Haiku 5.5 wrote the
    two characters "" for "no change" in 63 of 220 answers (notepad, will, claim, feedback;
    game_20261011_085841_783834); texts.blank caught most, but one turn posted "" as a public message. Through the
    API's constrained decoding it never did (0 in ~1900 Haiku calls in ten games)."""
    if isinstance(x, str):
        return "" if x.strip() in ('""', "''") else x
    if isinstance(x, list):
        return [unquote_empty(v) for v in x]
    if isinstance(x, dict):
        return {k: unquote_empty(v) for k, v in x.items()}
    return x


class ClaudeCodeClient:
    """An LLMClient that runs Claude models through the Claude Code CLI and passes other models to `other` (an
    OpenRouterClient, or None when there's no key: then a non-Claude model is an error)."""

    def __init__(self, other: LLMClient | None, effort: str | None = None, timeout: float = CALL_DEADLINE_S,
                 runner: Runner = run_cli, cli: str | None = None):
        self.other = other
        self.effort = effort
        self.timeout = timeout
        self.runner = runner
        self.cli = cli or shutil.which("claude") or "claude"
        self.total_cost: dict[str, float] = other.total_cost if other else {}
        self.cost_lock = threading.Lock()
        self.cwd = tempfile.mkdtemp(prefix="mafia-claude-")  # empty, so no CLAUDE.md or project settings
        self._on_error: Callable[..., None] | None = None
        self.plan_utilization: dict[str, float] = {}  # the latest utilization of each subscription window

    @property
    def on_error(self) -> Callable[..., None] | None:
        return self._on_error

    @on_error.setter
    def on_error(self, f: Callable[..., None] | None) -> None:
        self._on_error = f
        if self.other is not None and hasattr(self.other, "on_error"):
            self.other.on_error = f  # type: ignore[attr-defined]

    def chat(self, model: Model, messages: list[dict], *, tools: list[dict] | None = None,
             schema: dict | None = None, schema_name: str = "response", effort: str | None = None) -> LLMReply:
        if not routes(model):
            if self.other is None:
                raise RuntimeError(f"{model.value} needs OpenRouter, but OPENROUTER_API_KEY isn't set")
            return self.other.chat(model, messages, tools=tools, schema=schema, schema_name=schema_name,
                                   effort=effort)
        system = "\n\n".join(str(text_of(m["content"])) for m in messages if m["role"] == "system")
        if tools:
            system += tools_note(tools)
            schema = tools_schema(tools)
        effort = cli_effort(effort or self.effort or default_effort(model, cli=True))
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as f:
            f.write(system)  # a file: a long system prompt passes Windows' 32k-character command-line limit
        try:
            argv = [self.cli, "-p", "--model", cli_model(model), "--effort", effort, "--tools", "",
                    "--system-prompt-file", f.name, "--safe-mode", "--strict-mcp-config", "--no-session-persistence",
                    "--thinking-display", "summarized", "--output-format", "stream-json", "--verbose"]
            if schema:
                argv += ["--json-schema", json.dumps(schema, separators=(",", ":"))]
            events = self._run(model, argv, transcript([m for m in messages if m["role"] != "system"]))
        finally:
            os.unlink(f.name)
        return self._reply(model, events, tools is not None and bool(tools), schema is not None)

    def _run(self, model: Model, argv: list[str], prompt: str) -> list[dict]:
        """The call's stream-json events, ending with its result. Retries a call that gave no answer, and waits
        out a subscription limit."""
        for attempt in range(RETRIES + 1):
            started = time.monotonic()
            try:
                code, out, err = self.runner(argv, prompt, child_env(), self.cwd, self.timeout)
            except subprocess.TimeoutExpired:
                code, out, err = -1, "", f"no answer after {self.timeout:g} s"
            except OSError as e:  # e.g. the CLI isn't installed
                raise RuntimeError(f"couldn't run the Claude Code CLI ({self.cli}): {e}") from e
            events = []
            for line in out.splitlines():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
            self._note_limits(events)
            result = next((e for e in reversed(events) if e.get("type") == "result"), None)
            if result and (result.get("subtype") == "success" and not result.get("is_error")
                           or "structured_output" in str(result.get("subtype"))):  # an unusable answer: no retry
                return events
            if "--thinking-display" in argv and "--thinking-display" in err:  # an older CLI without the option
                i = argv.index("--thinking-display")
                argv = argv[:i] + argv[i + 2:]
                continue
            error = (f"exit {code}, {(result or {}).get('subtype')}: "
                     f"{(result or {}).get('result') or (result or {}).get('errors') or err.strip()[-300:]}")
            if wait := self._limit_wait(events, error):
                if self.on_error:
                    self.on_error("plan_limit", f"the Claude subscription's usage limit was reached; waiting "
                                  f"{wait / 60:.0f} min for it to reset ({error[:200]})", model=model.value,
                                  wait_s=round(wait))
                time.sleep(wait)
                continue
            if attempt < RETRIES:
                if self.on_error:
                    self.on_error("api_retry", f"a {model.value} call through Claude Code failed after "
                                  f"{time.monotonic() - started:.0f} s (attempt {attempt + 1}), retrying: "
                                  f"{error[:300]}", model=model.value, attempt=attempt)
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"Claude Code call to {model.value} failed: {error[:500]}")
        raise RuntimeError(f"Claude Code call to {model.value} failed after waiting for the usage limit")

    def _note_limits(self, events: list[dict]) -> None:
        for e in events:
            if e.get("type") == "rate_limit_event":
                windows = (e.get("rate_limit_info") or {}).get("unifiedWindows") or {}
                for name, w in windows.items():
                    if isinstance(w, dict) and "utilization" in w:
                        self.plan_utilization[name] = w["utilization"]

    def _limit_wait(self, events: list[dict], error: str) -> float | None:
        """Seconds until the subscription limit that refused this call resets, or None if it wasn't refused."""
        info = next((e.get("rate_limit_info") or {} for e in reversed(events) if e.get("type") == "rate_limit_event"),
                    {})
        if info.get("status") not in ("rejected", "blocked") and "usage limit" not in error.lower():
            return None
        resets = info.get("resetsAt")
        if not isinstance(resets, (int, float)):
            raise PlanLimitError(f"the Claude subscription's usage limit was reached, reset time unknown: {error}")
        wait = resets - time.time() + 60
        if wait > MAX_PLAN_WAIT_S:
            raise PlanLimitError(f"the Claude subscription's usage limit resets in {wait / 3600:.1f} h; resume the "
                                 f"game (--resume) after that: {error}")
        return max(wait, 60)

    def _reply(self, model: Model, events: list[dict], tools: bool, structured: bool) -> LLMReply:
        result = events[-1] if events and events[-1].get("type") == "result" else next(
            e for e in reversed(events) if e.get("type") == "result")
        thinking = [b.get("thinking", "") for e in events if e.get("type") == "assistant"
                    for b in (e.get("message") or {}).get("content") or [] if b.get("type") == "thinking"]
        stops = [(e.get("message") or {}).get("stop_reason") for e in events if e.get("type") == "assistant"]
        out = unquote_empty(result.get("structured_output"))
        tool_calls: list[dict] = []
        content: str | None
        if tools:
            calls = out.get("tool_calls") if isinstance(out, dict) else None
            for i, c in enumerate(calls or []):
                if isinstance(c, dict):
                    tool_calls.append({"id": f"call_{i}_{time.monotonic_ns()}", "type": "function", "function": {
                        "name": c.get("name"), "arguments": json.dumps(c.get("arguments") or {})}})
            content = None if tool_calls else (result.get("result") or "(no tool calls)")
        elif structured:
            content = json.dumps(out) if out is not None else None
        else:
            content = result.get("result")
        u = result.get("usage") or {}
        cached = u.get("cache_read_input_tokens") or 0
        usage: dict[str, Any] = {
            "prompt_tokens": (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0) + cached,
            "prompt_tokens_details": {"cached_tokens": cached,
                                      "cache_write_tokens": u.get("cache_creation_input_tokens") or 0},
            "completion_tokens": u.get("output_tokens") or 0,
            "completion_tokens_details": {"reasoning_tokens": (u.get("output_tokens_details") or {}).get(
                "thinking_tokens") or 0},
            "via": "claude_code", "list_cost_usd": result.get("total_cost_usd"),
            # turns: 2 when the answer came on the first try; more when the CLI had the model redo an answer that broke
            # the schema (its tokens add up over the turns)
            "duration_api_ms": result.get("duration_api_ms"), "turns": result.get("num_turns"),
            "plan_utilization": dict(self.plan_utilization)}
        with self.cost_lock:
            self.total_cost[model.value] = self.total_cost.get(model.value, 0.0)
        message: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            message["tool_calls"] = tool_calls
        return LLMReply(content=content, reasoning="".join(thinking) or None, tool_calls=tool_calls, message=message,
                        model=model.value, cost=0.0, usage=usage,
                        stop_note=f"Claude Code: {result.get('subtype')}, stop_reason {result.get('stop_reason')}"
                        + (f", {str(result['errors'])[:300]}" if result.get("errors") else ""),
                        finish_reason="length" if "max_tokens" in stops else None)
