"""claude_code.ClaudeCodeClient with a fake CLI: what each call runs, sends and gets back."""

import json
import time

import pytest

import claude_code
from claude_code import ClaudeCodeClient, PlanLimitError
from llm import Model, answer_json, cache_block


class FakeCli:
    """Answers each run with the next queued (structured_output | exception, extra result fields) and records
    what it was sent."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.runs: list[dict] = []

    def __call__(self, argv, stdin, env, cwd, timeout):
        system = open(argv[argv.index("--system-prompt-file") + 1], encoding="utf-8").read()
        self.runs.append({"argv": argv, "prompt": stdin, "env": env, "system": system})
        answer = self.answers.pop(0)
        if isinstance(answer, tuple) and answer[0] == "events":
            return 0, "\n".join(json.dumps(e) for e in answer[1]), ""
        if isinstance(answer, tuple) and answer[0] == "fail":
            return 1, "", answer[1]
        events = [
            {"type": "system", "subtype": "init"},
            {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "Bob is suspicious."}],
                                              "stop_reason": None}},
            {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "unifiedWindows": {
                "five_hour": {"utilization": 0.25}, "seven_day": {"utilization": 0.5}}}},
            {"type": "result", "subtype": "success", "is_error": False, "structured_output": answer,
             "result": json.dumps(answer), "total_cost_usd": 0.02, "stop_reason": "tool_use",
             "usage": {"input_tokens": 3, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 900,
                       "output_tokens": 50, "output_tokens_details": {"thinking_tokens": 20}}},
        ]
        return 0, "\n".join(json.dumps(e) for e in events), ""


SCHEMA = {"type": "object", "properties": {"vote": {"type": "string", "enum": ["Bob", "Carol"]}},
          "required": ["vote"], "additionalProperties": False}


def player_messages():
    return [{"role": "system", "content": [cache_block("RULES"), {"type": "text", "text": " and your role"}]},
            {"role": "user", "content": "Vote now."}]


def test_a_player_call_runs_a_toolless_cli_with_the_games_prompt(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "parent-session")
    monkeypatch.setenv("CLAUDE_SESSION_INGRESS_TOKEN_FILE", "/token")
    cli = FakeCli({"vote": "Bob"})
    client = ClaudeCodeClient(None, runner=cli, cli="claude")
    reply = client.chat(Model.HAIKU_5_5, player_messages(), schema=SCHEMA)
    run = cli.runs[0]
    argv = run["argv"]
    assert argv[argv.index("--model") + 1] == "claude-haiku-5-5"
    assert argv[argv.index("--effort") + 1] == "high"  # Haiku's default in MODELS
    assert argv[argv.index("--tools") + 1] == ""  # no tools: no file access
    assert {"--safe-mode", "--no-session-persistence", "--strict-mcp-config"} <= set(argv)
    assert json.loads(argv[argv.index("--json-schema") + 1]) == SCHEMA
    assert run["system"] == "RULES and your role" and run["prompt"] == "Vote now."
    assert "CLAUDE_CODE_SESSION_ID" not in run["env"] and run["env"]["CLAUDE_SESSION_INGRESS_TOKEN_FILE"] == "/token"
    assert answer_json(reply, SCHEMA) == {"vote": "Bob"}
    assert reply.reasoning == "Bob is suspicious." and reply.cost == 0
    assert reply.usage["prompt_tokens"] == 1003 and reply.usage["prompt_tokens_details"]["cached_tokens"] == 900
    assert reply.usage["completion_tokens_details"]["reasoning_tokens"] == 20
    assert reply.usage["list_cost_usd"] == 0.02
    assert reply.usage["plan_utilization"] == {"five_hour": 0.25, "seven_day": 0.5}
    assert client.total_cost == {Model.HAIKU_5_5.value: 0.0}


def test_effort_comes_from_the_call_then_the_client_then_the_model():
    cli = FakeCli({"vote": "Bob"}, {"vote": "Bob"}, {"vote": "Bob"})
    ClaudeCodeClient(None, runner=cli).chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA, effort="max")
    ClaudeCodeClient(None, effort="medium", runner=cli).chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA)
    ClaudeCodeClient(None, runner=cli).chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA, effort="minimal")
    assert [r["argv"][r["argv"].index("--effort") + 1] for r in cli.runs] == ["max", "medium", "low"]


def test_the_moderator_gets_its_tools_as_an_answer_schema_and_its_loop_as_a_transcript():
    tools = [{"type": "function", "function": {"name": "get_state", "description": "The state.",
                                               "parameters": {"type": "object", "properties": {}}}},
             {"type": "function", "function": {"name": "end_phase", "description": "Finish.", "parameters": {
                 "type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}}}]
    messages: list[dict] = [{"role": "system", "content": "You moderate."},
                            {"role": "user", "content": "Resolve the night."},
                {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "get_state", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "c1", "content": '{"alive": ["Bob"]}'}]
    cli = FakeCli({"tool_calls": [{"name": "end_phase", "arguments": {"summary": "quiet night"}}]})
    reply = ClaudeCodeClient(None, runner=cli).chat(Model.OPUS_5_5, messages, tools=tools)
    run = cli.runs[0]
    schema = json.loads(run["argv"][run["argv"].index("--json-schema") + 1])
    assert [o["properties"]["name"]["enum"] for o in schema["properties"]["tool_calls"]["items"]["anyOf"]] == [
        ["get_state"], ["end_phase"]]
    assert "- end_phase: Finish." in run["system"]
    assert "Resolve the night." in run["prompt"] and 'get_state({})' in run["prompt"]
    assert '=== Result of get_state ===\n{"alive": ["Bob"]}' in run["prompt"]
    assert [(c["function"]["name"], json.loads(c["function"]["arguments"])) for c in reply.tool_calls] == [
        ("end_phase", {"summary": "quiet night"})]
    assert reply.message["tool_calls"] == reply.tool_calls and reply.content is None


def test_other_makers_models_go_to_openrouter():
    class Other:
        total_cost: dict[str, float] = {}
        on_error = None

        def chat(self, model, messages, **kw):
            return f"openrouter {model.short}"
    other = Other()
    client = ClaudeCodeClient(other, runner=FakeCli())  # type: ignore[arg-type]
    assert client.chat(Model.GPT_6_LUNA, player_messages(), schema=SCHEMA) == "openrouter gpt-6-luna"
    client.on_error = print
    assert other.on_error is print and client.total_cost is other.total_cost
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        ClaudeCodeClient(None, runner=FakeCli()).chat(Model.GPT_6_LUNA, player_messages(), schema=SCHEMA)


def test_a_failed_run_is_retried_then_raises(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    errors = []
    cli = FakeCli(("fail", "connection reset"), {"vote": "Carol"})
    client = ClaudeCodeClient(None, runner=cli)
    client.on_error = lambda kind, summary, **kw: errors.append(kind)
    assert answer_json(client.chat(Model.HAIKU_5_5, player_messages(), schema=SCHEMA)) == {"vote": "Carol"}
    assert errors == ["api_retry"]
    cli = FakeCli(*[("fail", "boom")] * (claude_code.RETRIES + 1))
    with pytest.raises(RuntimeError, match="boom"):
        ClaudeCodeClient(None, runner=cli).chat(Model.HAIKU_5_5, player_messages(), schema=SCHEMA)


def test_an_unusable_structured_answer_comes_back_empty_without_a_retry():
    cli = FakeCli(("events", [{"type": "result", "subtype": "error_max_structured_output_retries", "is_error": True}]))
    reply = ClaudeCodeClient(None, runner=cli).chat(Model.HAIKU_5_5, player_messages(), schema=SCHEMA)
    assert reply.content is None and len(cli.runs) == 1
    with pytest.raises(RuntimeError, match="empty answer"):
        answer_json(reply)


def test_a_subscription_limit_is_waited_out_or_stops_the_game(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)

    def refused(resets_in):
        return ("events", [{"type": "rate_limit_event", "rate_limit_info": {
                    "status": "rejected", "resetsAt": time.time() + resets_in}},
                {"type": "result", "subtype": "success", "is_error": True, "result": "usage limit reached"}])
    errors = []
    client = ClaudeCodeClient(None, runner=FakeCli(refused(600), {"vote": "Bob"}))
    client.on_error = lambda kind, summary, **kw: errors.append(kind)
    assert answer_json(client.chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA)) == {"vote": "Bob"}
    assert errors == ["plan_limit"] and 600 < slept[0] < 700
    with pytest.raises(PlanLimitError):  # not an Exception, so a player's answer doesn't fall back on it
        ClaudeCodeClient(None, runner=FakeCli(refused(24 * 3600))).chat(Model.OPUS_5_5, player_messages(),
                                                                         schema=SCHEMA)


def test_an_older_cli_without_thinking_display_still_runs():
    cli = FakeCli(("fail", "error: unknown option '--thinking-display'"), {"vote": "Bob"})
    ClaudeCodeClient(None, runner=cli).chat(Model.HAIKU_5_5, player_messages(), schema=SCHEMA)
    assert "--thinking-display" in cli.runs[0]["argv"] and "--thinking-display" not in cli.runs[1]["argv"]


def test_a_retry_after_a_bad_answer_is_sent_as_a_transcript():
    cli = FakeCli({"vote": "Bob"})
    messages = player_messages() + [{"role": "assistant", "content": '{"vote": "Dave"}'},
                                    {"role": "user", "content": "That answer couldn't be used."}]
    ClaudeCodeClient(None, runner=cli).chat(Model.HAIKU_5_5, messages, schema=SCHEMA)
    prompt = cli.runs[0]["prompt"]
    assert prompt.index("Vote now.") < prompt.index('{"vote": "Dave"}') < prompt.index("couldn't be used")
