"""Claude models through the Claude Code CLI (`claude -p`), so their calls use a Claude subscription's quota
instead of OpenRouter credits (--claude-code: the default where the CLI is installed; --no-claude-code turns it
off). Other models still go through OpenRouter, so one game can mix both routes.

Each call is a fresh, non-interactive `claude -p` process: no tools (so no file access and nothing to leak), the
game's own system prompt in place of Claude Code's (the CLI still adds a short environment note, working directory,
platform and date, and the signed-in account's email, with no switch to turn them off; CLI_NOTE tells the model to
ignore them, since a player reported the email as a bug in game_20261011_225511_1253), no CLAUDE.md, settings,
skills, plugins, hooks or MCP servers (--safe-mode, an empty working directory, and none of the parent Claude Code
session's CLAUDE* variables), and no saved session. Answers come back as structured output (--json-schema). Nothing
persists between calls, so a crash on either side loses at most the calls in flight; the game's checkpoints cover
the rest (--resume).

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
- Caps: games leave part of the subscription for other work. Once a window's utilization reaches its cap (PLAN_CAPS:
  70% of the 5-hour and of the 7-day window; --plan-cap), no call starts until that window resets: a game doesn't
  start (check_plan, one small Haiku call that reads the utilization), and a running one waits, or stops for
  --resume when the reset is more than 6 hours away. Starting a game is stricter early in the week, so the week's
  share isn't spent in its first days: the 7-day cap for a new game grows with the week (start_cap: 10% at the
  reset, 40% halfway, the full 70% at the next reset); a game already running only stops at the full cap.
- Thinking comes back summarized (--thinking-display summarized), like Claude's through the API.
- Effort: both paths send Anthropic's native effort level (5.5 models reject thinking budgets), but answering through
  the CLI's StructuredOutput tool, plus a closing turn after it, costs more output than the API's constrained JSON. On
  one real night-action prompt (3 runs each, 2026-10-11; output tokens, reasoning in brackets, API -> CLI): Opus high
  1168 (376) -> 1740 (418), medium 1015 (313) -> 1346 (278), so Opus thinks the same; Haiku high 1164 (971) ->
  2213 (1572), medium 685 (494) -> 1459 (900). On long day turns Haiku's gap was ~3x (5k output tokens a call vs
  ~1.8k in API games, 23 s vs 9 s a turn, game_20261011_085841_783834). So CLI Haiku at medium matches API Haiku at
  high; Opus needs no change.
"""

import atexit
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from typing import Any

from llm import (API_KEY_ENV_VAR, DEFAULT_MAX_TOKENS, LLMClient, LLMReply, MockClient, Model, OpenRouterClient,
                 default_effort, load_api_key, text_of)

CLI_EFFORTS = ("low", "medium", "high", "xhigh", "max")
CALL_DEADLINE_S = 900  # one call, CLI start-up and its own API retries included (Opus turns took up to ~210 s)
RETRIES = 2  # a call that failed (no answer at all) is tried this many more times
MAX_PLAN_WAIT_S = 6 * 3600  # waits this long at most for a subscription limit to reset; longer stops the game
# A program safeguard, not Anthropic's limit: the share of each subscription window that games may use up
# (utilization 0-1), so other Claude Code work isn't locked out by games. 1 turns a cap off.
PLAN_CAPS = {"five_hour": 0.7, "seven_day": 0.7}
WINDOW_NAMES = {"five_hour": "5-hour", "seven_day": "7-day"}
WEEK_S = 7 * 86400
WEEK_START = 0.1  # the 7-day utilization below which a game may start right after the week's reset
# The parent Claude Code session's variables (session id, remote-session settings, ...) would make the child act
# as part of that session and add its context; these are the ones the child needs to sign in
# (CLAUDE_CODE_OAUTH_TOKEN is a headless sign-in made with `claude setup-token`).
KEEP_ENV = {"CLAUDE_SESSION_INGRESS_TOKEN_FILE", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN"}
# An API key would make `claude -p` bill the API instead of the subscription, while the logs record these calls
# at $0, so the child never sees one.
DROP_ENV = {"AI_AGENT", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"}

Runner = Callable[[list[str], str, dict[str, str], str, float], tuple[int, str, str]]


class PlanLimitError(BaseException):
    """The subscription's usage limit won't reset soon enough. A BaseException, so it isn't taken for a bad answer
    (players' answers fall back to defaults on Exception): it stops the game, which can be resumed (--resume)."""


CLI_NOTE = ("\n\n(Program note: the program that delivers these messages may add an email address, a working "
            "directory, a platform or a date. They aren't part of this task: ignore them and don't report them.)")


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
            if not (k.startswith("CLAUDE") and k not in KEEP_ENV) and k not in DROP_ENV}


def run_cli(argv: list[str], stdin: str, env: dict[str, str], cwd: str, timeout: float) -> tuple[int, str, str]:
    """Runs the CLI in its own process group, so a timeout kills the whole tree: `claude` may be a launcher that
    starts the real CLI as a child instead of exec-ing it (as on Kevin's PC), and subprocess.run's timeout kills
    only the direct child, which would leave the real CLI running (and using the subscription)."""
    # sys.platform, not os.name: mypy follows it, so each system's checks see only the names that system has.
    group: dict = {"start_new_session": True}
    if sys.platform == "win32":
        group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace", env=env, cwd=cwd, **group)
    try:
        out, err = p.communicate(stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
        else:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        p.kill()
        p.communicate()
        raise
    return p.returncode, out, err


def cut_off(result: dict) -> bool:
    """Whether the CLI stopped the answer at its output cap (CLAUDE_CODE_MAX_OUTPUT_TOKENS): it reports that as a
    failed call ("API Error: Claude's response exceeded the N output token maximum"), not as a max_tokens stop. Like
    OpenRouter's finish_reason "length", it comes back as a reply with no answer, so a caller can retry at lower
    effort (llm.lower_effort) instead of the same call failing again."""
    return "output token maximum" in str(result.get("result") or "")


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


def default_client(effort: str | None = None, max_tokens: int = DEFAULT_MAX_TOKENS,
                   timeout: float | None = None, caps: dict[str, float] | None = None) -> LLMClient:
    """The client for tools outside a game (tips builds, grading, script revisions): Claude models through the
    Claude Code CLI where it's installed, as games do (Kevin, Oct 11 2026: the subscription instead of paid API
    calls; the PLAN_CAPS apply), and other models, or every model without the CLI, through OpenRouter. timeout:
    one call's deadline (None: each client's default). caps: the CLI's plan caps (None: PLAN_CAPS), e.g. a game's
    --plan-cap for the tips build before it starts."""
    def openrouter() -> OpenRouterClient:
        client = OpenRouterClient(load_api_key(), effort=effort, max_tokens=max_tokens)
        client.timeout = timeout or client.timeout
        return client
    if not available():
        return openrouter()
    return ClaudeCodeClient(openrouter() if os.environ.get(API_KEY_ENV_VAR, "").strip() else None, effort=effort,
                            timeout=timeout or CALL_DEADLINE_S, max_tokens=max_tokens, caps=caps)


class ClaudeCodeClient:
    """An LLMClient that runs Claude models through the Claude Code CLI and passes other models to `other` (an
    OpenRouterClient, or None when there's no key: then a non-Claude model is an error)."""

    def __init__(self, other: LLMClient | None, effort: str | None = None, timeout: float = CALL_DEADLINE_S,
                 runner: Runner = run_cli, cli: str | None = None, caps: dict[str, float] | None = None,
                 max_tokens: int | None = None):
        self.other = other
        self.max_tokens = max_tokens  # None: the CLI's own output cap
        self.caps = dict(PLAN_CAPS if caps is None else caps)
        self.plan_resets: dict[str, float] = {}  # when each window resets (epoch seconds)
        self.cap_lock = threading.Lock()
        self.cap_reported = 0.0  # the reset time of the last cap wait that was reported, so each is reported once
        self.effort = effort
        self.timeout = timeout
        self.runner = runner
        self.cli = cli or shutil.which("claude") or "claude"
        self.total_cost: dict[str, float] = other.total_cost if other else {}
        self.cost_lock = threading.Lock()
        self.cwd = tempfile.mkdtemp(prefix="mafia-claude-")  # empty, so no CLAUDE.md or project settings
        atexit.register(shutil.rmtree, self.cwd, ignore_errors=True)  # else every game leaves one in the temp dir
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
        system = "\n\n".join(str(text_of(m["content"])) for m in messages if m["role"] == "system") + CLI_NOTE
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
            self._hold_for_caps(model)
            started = time.monotonic()
            try:
                env = child_env()
                if self.max_tokens:  # child_env drops CLAUDE* variables, so the cap is set here
                    env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(self.max_tokens)
                code, out, err = self.runner(argv, prompt, env, self.cwd, self.timeout)
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
            if result and cut_off(result):  # retrying the same call would be cut off again: the caller decides
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
                        if isinstance(w.get("resetsAt"), (int, float)):
                            self.plan_resets[name] = w["resetsAt"]

    def over_cap(self) -> tuple[str, float, float | None] | None:
        """The window whose utilization has reached its cap (the one that resets last, if both have): its name,
        utilization and reset time. None while games may go on using the subscription."""
        now = time.time()
        # copies: other threads' calls update these meanwhile (a dict changing size mid-iteration raises)
        resets = dict(self.plan_resets)
        over = [(name, used, resets.get(name)) for name, used in list(self.plan_utilization.items())
                if used >= self.caps.get(name, 1.0) < 1 and (resets.get(name) or now + 1) > now]
        return max(over, key=lambda o: o[2] or float("inf")) if over else None

    def cap_text(self, over: tuple[str, float, float | None]) -> str:
        name, used, resets = over
        when = f"resets in {(resets - time.time()) / 3600:.1f} h" if resets else "reset time unknown"
        return (f"games have a cap of {self.caps[name]:.0%} of the Claude subscription's "
                f"{WINDOW_NAMES.get(name, name)} window, which is {used:.0%} used ({when}); --plan-cap changes it")

    def _hold_for_caps(self, model: Model) -> None:
        """Before a call: waits until a window that has reached its cap resets, or stops the game when that is
        too far off (as for the subscription's own limit)."""
        while over := self.over_cap():
            name, _, resets = over
            if resets is None or resets - time.time() + 60 > MAX_PLAN_WAIT_S:
                raise PlanLimitError(f"{self.cap_text(over)}. Resume the game (--resume) after the reset")
            wait = max(resets - time.time() + 60, 60)
            with self.cap_lock:
                report, self.cap_reported = self.cap_reported != resets, resets
            if report and self.on_error:
                self.on_error("plan_cap", f"{self.cap_text(over)}; waiting {wait / 60:.0f} min",
                              model=model.value, window=name, wait_s=round(wait))
            time.sleep(wait)
            if self.plan_resets.get(name) == resets:  # the window has reset: its old figure no longer counts
                self.plan_utilization.pop(name, None)

    def start_cap(self, name: str) -> float:
        """The utilization below which a new game may start. The 5-hour window's is its cap; the 7-day window's
        follows the week, so early games can't use up the week's share: it rises evenly from WEEK_START at the
        reset to the cap at the next one (70%: 10% at the reset, 40% halfway, 70% at the end)."""
        cap = self.caps.get(name, 1.0)
        resets = self.plan_resets.get(name)
        if name != "seven_day" or cap >= 1 or resets is None:
            return cap
        passed = min(max(1 - (resets - time.time()) / WEEK_S, 0.0), 1.0)
        first = min(WEEK_START, cap)
        return first + (cap - first) * passed

    def check_plan(self) -> str:
        """Before a game: reads the subscription's utilization with one small Haiku call (which also shows the CLI
        works and is signed in) and returns a line about it. PlanLimitError if a window is at its cap, or the
        7-day window is past what this point of the week allows (start_cap)."""
        self.caps, caps = {}, self.caps  # this call itself isn't held back
        try:
            self.chat(Model.HAIKU_5_5, [{"role": "system", "content": "Reply with the word ok."},
                                        {"role": "user", "content": "Go."}], effort="low")
        finally:
            self.caps = caps
        if over := self.over_cap():
            raise PlanLimitError(f"not starting: {self.cap_text(over)}")
        week, allowed = self.plan_utilization.get("seven_day", 0.0), self.start_cap("seven_day")
        if week >= allowed < 1:
            left = (self.plan_resets["seven_day"] - time.time()) / 86400
            raise PlanLimitError(
                f"not starting: {week:.0%} of the Claude subscription's 7-day window is used with {left:.1f} days "
                f"left in it, and games start only below {allowed:.0%} at this point (rising to "
                f"{self.caps['seven_day']:.0%} by the week's end); --plan-cap changes the cap, 100 turns it off")
        used = ", ".join(f"{WINDOW_NAMES.get(n, n)} window {u:.0%} used (games start below {self.start_cap(n):.0%})"
                         for n, u in self.plan_utilization.items())
        return f"Claude subscription: {used or 'utilization not reported'}"

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
                        finish_reason="length" if "max_tokens" in stops or cut_off(result) else None)
