"""claude_code.ClaudeCodeClient with a fake CLI: what each call runs, sends and gets back."""

import json
import time

import pytest

import claude_code
from claude_code import CLI_NOTE, ClaudeCodeClient, PlanLimitError
from llm import MockClient, Model, answer_json, cache_block


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
    assert argv[argv.index("--effort") + 1] == "medium"  # Haiku's cli_effort in MODELS
    assert argv[argv.index("--tools") + 1] == ""  # no tools: no file access
    assert {"--safe-mode", "--no-session-persistence", "--strict-mcp-config"} <= set(argv)
    assert json.loads(argv[argv.index("--json-schema") + 1]) == SCHEMA
    assert run["system"] == "RULES and your role" + CLI_NOTE and run["prompt"] == "Vote now."
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


def test_a_pair_of_quotes_for_no_change_is_read_as_empty():
    cli = FakeCli({"vote": "Bob", "notepad": '""', "claim": "said \"\" twice"})
    reply = ClaudeCodeClient(None, runner=cli).chat(Model.HAIKU_5_5, player_messages(), schema={"type": "object"})
    assert json.loads(reply.content or "") == {"vote": "Bob", "notepad": "", "claim": 'said "" twice'}


def test_each_seat_records_how_its_model_ran():
    from gamelogs import players
    from llm import MockClient
    cc = ClaudeCodeClient(None, runner=FakeCli())
    assert claude_code.route(cc, Model.OPUS_5_5) == "claude_code"
    assert claude_code.route(cc, Model.GPT_6_LUNA) == "api"
    assert claude_code.route(MockClient(0), Model.OPUS_5_5) == "mock"
    setup = {"kind": "setup", "settings": {}, "players": [
        {"name": "Alice", "seat": 0, "model": Model.OPUS_5_5.value, "role": "Sheriff", "via": "claude_code"},
        {"name": "Bob", "seat": 1, "model": Model.OPUS_5_5.value, "role": "Grunt"}]}  # before log version 47
    assert [p["via"] for p in players([setup])] == ["claude_code", "api"]
    setup["settings"] = {"claude_code": True}  # log version 46 had only the setting
    assert [p["via"] for p in players([setup])] == ["claude_code", "claude_code"]


def test_haiku_defaults_to_medium_only_through_the_cli():
    from llm import ModelSpec
    from mafia import resolve_effort
    assert resolve_effort(ModelSpec(Model.HAIKU_5_5), None, cli=True).effort == "medium"
    assert resolve_effort(ModelSpec(Model.HAIKU_5_5), None).effort == "high"
    assert resolve_effort(ModelSpec(Model.OPUS_5_5), None, cli=True).effort == "high"
    assert resolve_effort(ModelSpec(Model.HAIKU_5_5, "high"), None, cli=True).effort == "high"


def test_games_use_the_cli_by_default_where_it_is_installed(monkeypatch):
    from mafia import build_parser, via_claude_code
    assert build_parser().parse_args([]).claude_code is None  # neither --claude-code nor --no-claude-code
    assert build_parser().parse_args(["--no-claude-code"]).claude_code is False
    monkeypatch.setattr(claude_code, "available", lambda: True)
    assert via_claude_code(None) and via_claude_code(True)
    assert not via_claude_code(False)
    assert not via_claude_code(None, mock=True)
    monkeypatch.setattr(claude_code, "available", lambda: False)  # e.g. GitHub's runners: OpenRouter as before
    assert not via_claude_code(None)
    with pytest.raises(ValueError, match="no `claude` command"):
        via_claude_code(True)


def used(five_hour, week, resets_in=3600.0, week_left=0.5):
    """A call that answers and reports this much of each subscription window used (week_left: days to its reset)."""
    return ("events", [{"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "unifiedWindows": {
                "five_hour": {"utilization": five_hour, "resetsAt": time.time() + resets_in},
                "seven_day": {"utilization": week, "resetsAt": time.time() + week_left * 86400}}}},
            {"type": "result", "subtype": "success", "is_error": False, "structured_output": {"vote": "Bob"},
             "result": "ok", "usage": {}}])


def test_games_stop_using_the_subscription_at_its_cap(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    errors = []
    cli = FakeCli(used(0.5, 0.3), used(0.75, 0.3), {"vote": "Bob"}, {"vote": "Bob"})
    client = ClaudeCodeClient(None, runner=cli)
    client.on_error = lambda kind, summary, **kw: errors.append((kind, kw.get("window")))
    assert "5-hour window 50% used (games start below 70%)" in client.check_plan()  # a game may start
    client.chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA)  # this call takes the 5-hour window past its cap
    assert not slept
    client.chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA)  # so the next waits for that window's reset
    assert errors == [("plan_cap", "five_hour")] and 3600 < slept[0] < 3700
    client.chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA)  # and after it calls go on as usual
    assert len(slept) == 1 and len(cli.runs) == 4

    week = ClaudeCodeClient(None, runner=FakeCli(used(0.2, 0.9, week_left=3), {"vote": "Bob"}))
    with pytest.raises(PlanLimitError, match="not starting.*7-day window, which is 90% used"):
        week.check_plan()
    with pytest.raises(PlanLimitError, match="--resume"):  # mid-game: the week resets too late to wait for
        week.chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA)
    off = ClaudeCodeClient(None, runner=FakeCli(used(0.95, 0.95), {"vote": "Bob"}),
                           caps={"five_hour": 1.0, "seven_day": 1.0})
    off.check_plan()
    off.chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA)  # --plan-cap 100,100: only Anthropic's own limit


def test_plan_cap_option():
    from mafia import parse_plan_cap
    assert parse_plan_cap(None) is None
    assert parse_plan_cap("80,70") == {"five_hour": 0.8, "seven_day": 0.7}
    for bad in ("80", "0,50", "120,50", "a,b"):
        with pytest.raises(ValueError):
            parse_plan_cap(bad)


@pytest.mark.parametrize("days_left, start_cap", [(7, 0.1), (5.25, 0.25), (3.5, 0.4), (1.75, 0.55), (0, 0.7)])
def test_the_weekly_start_cap_rises_evenly_from_10_percent_at_the_reset_to_the_cap_at_the_end(days_left, start_cap):
    client = ClaudeCodeClient(None)
    client.plan_resets = {"five_hour": time.time() + 3600, "seven_day": time.time() + days_left * 86400}
    assert client.start_cap("seven_day") == pytest.approx(start_cap, abs=1e-4)
    assert client.start_cap("five_hour") == 0.7  # the 5-hour window has no ramp
    client.caps = {"five_hour": 0.5, "seven_day": 0.4}  # --plan-cap 50,40: the ramp ends at the weekly cap given
    assert client.start_cap("seven_day") == pytest.approx(0.1 + (start_cap - 0.1) / 2, abs=1e-4)  # 10% to 40%
    client.caps = {"five_hour": 0.5, "seven_day": 0.05}  # a weekly cap under the starting figure: flat
    assert client.start_cap("seven_day") == pytest.approx(0.05)


def test_a_new_game_needs_more_of_the_week_left_early_in_the_week():
    def start(week_used, days_left, caps=None):
        return ClaudeCodeClient(None, runner=FakeCli(used(0.1, week_used, week_left=days_left)), caps=caps).check_plan()
    assert "7-day window 5% used (games start below 10%)" in start(0.05, 7)  # the week has just begun
    with pytest.raises(PlanLimitError, match="12% .* 7.0 days left.* only below 10%"):
        start(0.12, 7)
    assert "7-day window 15% used (games start below 19%)" in start(0.15, 6)  # a day in: 10% + 60% x 1/7
    assert "games start below 40%" in start(0.35, 3.5)  # halfway
    with pytest.raises(PlanLimitError, match="only below 40%"):
        start(0.45, 3.5)
    assert "7-day window 60% used (games start below 66%)" in start(0.6, 0.5)  # late: nearly the cap itself
    assert "games start below 100%" in start(0.9, 7, caps={"five_hour": 1.0, "seven_day": 1.0})  # turned off
    running = ClaudeCodeClient(None, runner=FakeCli(used(0.1, 0.5, week_left=6), {"vote": "Bob"}))
    running.chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA)
    running.chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA)  # a game under way goes on up to the cap


# --- The subscription caps, at their edges and in a game ----------------------------------------------

def capped(*answers, caps=None):
    return ClaudeCodeClient(None, runner=FakeCli(*answers), caps=caps)


def test_a_cap_holds_from_exactly_its_figure_and_only_until_the_reset(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    under = capped(used(0.69, 0.1), {"vote": "Bob"})
    under.chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA)
    under.chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA)
    assert not slept and under.over_cap() is None
    at = capped(used(0.7, 0.1, resets_in=600), {"vote": "Bob"})
    at.chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA)
    assert at.over_cap()[:2] == ("five_hour", 0.7)
    at.chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA)
    assert len(slept) == 1 and 600 < slept[0] < 700  # the reset plus a margin, not the whole 5 hours
    stale = capped(used(0.9, 0.1, resets_in=-30), {"vote": "Bob"})  # the window has reset since it was read
    stale.chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA)
    stale.chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA)
    assert len(slept) == 1 and stale.over_cap() is None


def test_with_both_windows_at_their_caps_the_later_reset_decides(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: pytest.fail("waited for the 5-hour window alone"))
    both = capped(used(0.9, 0.9, resets_in=600, week_left=2), {"vote": "Bob"})
    both.chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA)
    assert both.over_cap()[0] == "seven_day"
    with pytest.raises(PlanLimitError, match="7-day window.*--resume"):  # waiting 10 minutes would not help
        both.chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA)


def test_caps_turned_off_never_hold_a_call_even_at_full_use(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: pytest.fail("held a call with the caps off"))
    off = capped(used(1.0, 1.0, week_left=6), used(1.0, 1.0, week_left=6), {"vote": "Bob"},
                 caps={"five_hour": 1.0, "seven_day": 1.0})
    assert "games start below 100%" in off.check_plan()
    off.chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA)
    off.chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA)
    assert off.over_cap() is None


def test_each_cap_is_set_on_its_own_and_the_weekly_ramp_scales_with_it():
    client = capped(used(0.75, 0.2, week_left=3.5), caps={"five_hour": 0.9, "seven_day": 0.5})
    line = client.check_plan()  # 75% is under a 90% 5-hour cap; halfway through the week 50% allows 30%
    assert "5-hour window 75% used (games start below 90%)" in line
    assert "7-day window 20% used (games start below 30%)" in line
    with pytest.raises(PlanLimitError, match="only below 30%.*rising to 50%"):
        capped(used(0.1, 0.35, week_left=3.5), caps={"five_hour": 0.9, "seven_day": 0.5}).check_plan()


def test_the_weekly_ramp_grows_through_the_week_and_never_passes_the_cap():
    client = capped()
    client.plan_utilization = {"seven_day": 0.0}
    seen = []
    for days_left in (7, 6, 5, 4, 3, 2, 1, 0.001):
        client.plan_resets = {"seven_day": time.time() + days_left * 86400}
        seen.append(client.start_cap("seven_day"))
    assert seen == sorted(seen) and seen[0] == pytest.approx(0.1, abs=1e-6) and seen[-1] == pytest.approx(0.7, abs=1e-3)
    assert seen[1] == pytest.approx(0.1 + 0.6 / 7) and seen[4] == pytest.approx(0.1 + 0.6 * 4 / 7)
    for odd in (9, -1):  # a reset time further off than a week, or already past: clamped to the week
        client.plan_resets = {"seven_day": time.time() + odd * 86400}
        assert 0.1 <= client.start_cap("seven_day") <= 0.7
    client.plan_resets = {}
    assert client.start_cap("seven_day") == 0.7  # no reset time reported: the flat cap
    assert client.start_cap("five_hour") == 0.7  # the 5-hour window has no ramp


def test_the_start_check_is_not_held_back_by_an_earlier_reading(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: pytest.fail("the start check waited"))
    client = capped(used(0.2, 0.1, week_left=3))
    client.plan_utilization = {"five_hour": 0.95}  # e.g. read by an earlier game in this process
    client.plan_resets = {"five_hour": time.time() + 900}
    assert "5-hour window 20% used" in client.check_plan()  # the fresh figure decides
    assert client.caps == claude_code.PLAN_CAPS  # and the caps are back for the game's calls


def test_calls_made_at_once_all_wait_at_a_cap_and_report_it_once(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    errors = []
    client = capped(used(0.8, 0.1, resets_in=1200), *[{"vote": "Bob"}] * 6)
    client.on_error = lambda kind, summary, **kw: errors.append(kind)
    client.chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA)
    with ThreadPoolExecutor(6) as pool:
        answers = list(pool.map(lambda _: answer_json(client.chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA)),
                                range(6)))
    assert answers == [{"vote": "Bob"}] * 6
    assert errors == ["plan_cap"] and 1 <= len(slept) <= 6 and all(1200 < s < 1300 for s in slept)


def test_other_makers_models_are_never_held_by_the_claude_caps(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: pytest.fail("held a call to another maker"))

    class Other:
        total_cost: dict[str, float] = {}

        def chat(self, model, messages, **kw):
            return "from openrouter"
    client = ClaudeCodeClient(Other(), runner=FakeCli(used(0.99, 0.99, week_left=3)))
    client.chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA)
    assert client.chat(Model.GPT_6_LUNA, player_messages(), schema=SCHEMA) == "from openrouter"


def run_main(monkeypatch, argv, catch_up=lambda *a, **k: []):
    import sys

    import mafia
    monkeypatch.setattr(sys, "argv", ["mafia.py", *argv])
    monkeypatch.setattr(mafia.sync_logs, "catch_up", catch_up)  # a PC game's pre-game pull: no real repo here
    with pytest.raises(SystemExit):
        mafia.main()


def test_a_game_at_the_cap_does_not_start_and_leaves_no_log(tmp_path, monkeypatch, capsys):
    import mafia
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(claude_code, "available", lambda: True)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    seen = {}

    def client_for(cli):
        def api_client(effort, via, plan_cap=None):
            seen["via"], seen["caps"] = via, plan_cap
            return ClaudeCodeClient(None, runner=cli, caps=plan_cap)
        monkeypatch.setattr(mafia, "api_client", api_client)
    game = ["--players", "haiku-5.5", "--moderator", "opus-5.5"]
    client_for(FakeCli(used(0.1, 0.5, week_left=5)))  # two days into the week, half of it used
    run_main(monkeypatch, game)
    err = capsys.readouterr().err
    assert seen == {"via": True, "caps": None}  # Claude Code and the default caps, with no flag given
    assert "not starting: 50% of the Claude subscription's 7-day window is used with 5.0 days left" in err
    assert "only below 27%" in err and "--no-claude-code" in err
    client_for(FakeCli(used(0.75, 0.05, week_left=1)))
    run_main(monkeypatch, game)
    assert "cap of 70% of the Claude subscription's 5-hour window, which is 75% used" in capsys.readouterr().err
    client_for(FakeCli(used(0.1, 0.5, week_left=0.5)))
    run_main(monkeypatch, [*game, "--plan-cap", "70,30"])
    assert seen["caps"] == {"five_hour": 0.7, "seven_day": 0.3}
    assert "cap of 30% of the Claude subscription's 7-day window, which is 50% used" in capsys.readouterr().err
    client_for(FakeCli(*[("fail", "not signed in")] * (claude_code.RETRIES + 1)))  # the CLI itself is broken
    run_main(monkeypatch, game)
    assert "not signed in" in capsys.readouterr().err
    run_main(monkeypatch, [*game, "--plan-cap", "eighty"])
    assert "--plan-cap takes two percents" in capsys.readouterr().err
    assert not (tmp_path / "logs").exists()


def test_the_pre_game_catch_up_uses_the_game_s_plan_cap_and_its_plan_limit_doesnt_stop_the_start_check(
        tmp_path, monkeypatch, capsys):
    import mafia
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(claude_code, "available", lambda: True)
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)  # a PC game, which catches up first
    monkeypatch.setattr(time, "sleep", lambda s: None)
    order: list[tuple] = []
    monkeypatch.setattr(mafia, "api_client",
                        lambda effort, via, plan_cap=None: ClaudeCodeClient(None, runner=FakeCli(used(0.75, 0.05)),
                                                                            caps=plan_cap))

    def catch_up(repo, log_dir, tips_dir, model, plan_cap=None):
        order.append(("catch_up", plan_cap))
        raise PlanLimitError("the tips build hit the cap")  # a BaseException: used to escape and stop main
    real_check = mafia.check_plan

    def check_plan(*a):
        order.append(("check_plan",))
        real_check(*a)
    monkeypatch.setattr(mafia, "check_plan", check_plan)
    run_main(monkeypatch, ["--players", "haiku-5.5", "--moderator", "opus-5.5", "--plan-cap", "70,30"], catch_up)
    assert order == [("catch_up", {"five_hour": 0.7, "seven_day": 0.3}), ("check_plan",)]
    out = capsys.readouterr()
    assert "ALERT sync_error" in out.out and "the tips build hit the cap" in out.out  # flagged, not raised
    assert "5-hour window, which is 75% used" in out.err  # then the game's own check stops it


def test_tools_outside_games_take_a_plan_cap(monkeypatch):
    import tips
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(claude_code, "available", lambda: True)
    default, game_s = tips.tool_client(), tips.tool_client(caps={"five_hour": 1.0, "seven_day": 1.0})
    assert isinstance(default, ClaudeCodeClient) and isinstance(game_s, ClaudeCodeClient)
    assert default.caps == claude_code.PLAN_CAPS and game_s.caps == {"five_hour": 1.0, "seven_day": 1.0}


def test_a_timed_out_call_kills_the_cli_a_launcher_started(tmp_path):
    import os
    import subprocess
    import sys
    pidfile = tmp_path / "pid"
    # a launcher that doesn't exec the real CLI (like a wrapper script): the "CLI" is its child
    launcher = ("import subprocess, sys; p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']);"
                f"open({str(pidfile)!r}, 'w').write(str(p.pid)); p.wait()")
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        claude_code.run_cli([sys.executable, "-c", launcher], "", dict(os.environ), str(tmp_path), 2)
    assert time.monotonic() - started < 10
    pid = int(pidfile.read_text())
    def gone() -> bool:  # killed: gone, or a zombie until its parent (also killed) is reaped
        try:
            with open(f"/proc/{pid}/stat") as f:
                return f.read().split(") ")[1][0] == "Z"
        except OSError:  # no such process (it may vanish between checks)
            return True
    for _ in range(50):
        if sys.platform == "win32" or gone():
            break
        time.sleep(0.1)
    else:
        os.kill(pid, 9)
        pytest.fail("the CLI the launcher started kept running after the timeout")


def test_run_cli_returns_the_cli_s_output(tmp_path):
    import os
    import sys
    code, out, err = claude_code.run_cli(
        [sys.executable, "-c", "import sys; print(sys.stdin.read().upper()); sys.exit(3)"], "hi", dict(os.environ),
        str(tmp_path), 30)
    assert (code, out.strip()) == (3, "HI")


def test_the_start_check_runs_only_for_claude_seats_through_the_cli(capsys):
    import argparse

    import mafia
    from llm import ModelSpec
    ap = argparse.ArgumentParser()
    cli = FakeCli(used(0.2, 0.1, week_left=3))
    client = ClaudeCodeClient(None, runner=cli)
    mafia.check_plan(ap, client, [Model.GPT_6_LUNA, ModelSpec(Model.GPT_6_LUNA)])  # no Claude seat: no call
    mafia.check_plan(ap, MockClient(0), [Model.OPUS_5_5])  # not through the CLI
    assert not cli.runs and not capsys.readouterr().out
    mafia.check_plan(ap, client, [Model.GPT_6_LUNA, ModelSpec(Model.OPUS_5_5)])
    [run] = cli.runs
    assert run["argv"][run["argv"].index("--model") + 1] == "claude-haiku-5-5"  # the cheapest model reads it
    assert "5-hour window 20% used (games start below 70%)" in capsys.readouterr().out


def test_a_game_stopped_at_the_weekly_cap_can_be_resumed(tmp_path, monkeypatch):
    import mafia
    from checkpoint import load
    from roles import DEFAULT_SETUP
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)

    class HitsTheCap(MockClient):
        calls = 0

        def chat(self, model, messages, **kw):
            self.calls += 1
            if self.calls == 60:  # some way into the game
                raise PlanLimitError("games have a cap of 70% of the Claude subscription's 7-day window")
            return super().chat(model, messages, **kw)
    seed = 7
    config = mafia.GameConfig([Model.HAIKU_5_5], Model.HAIKU_5_5, DEFAULT_SETUP, seed)
    with pytest.raises(PlanLimitError):  # not swallowed as a bad answer from a player
        mafia.play_game(HitsTheCap(seed), config)
    [ckpt_path] = tmp_path.glob("*.ckpt")
    log = ckpt_path.with_suffix(".jsonl")
    crash = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()][-1]
    assert crash["kind"] == "crash" and "7-day window" in crash["error"] and "--resume" in crash["error"]
    ckpt = load(ckpt_path)
    mafia.play_game(MockClient(seed), mafia.GameConfig.from_checkpoint(ckpt), resume=ckpt)
    assert json.loads(log.read_text(encoding="utf-8").splitlines()[-1])["kind"] == "result"


def test_a_plan_limit_after_the_game_skips_the_later_post_game_calls_but_writes_the_result(tmp_path, monkeypatch):
    """The checkpoint is gone once the game is decided, so a stop there would lose the game's result for good."""
    import mafia
    from roles import DEFAULT_SETUP
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    ran = []

    def debrief(*a, **k):
        ran.append("debrief")
        raise PlanLimitError("games have a cap of 70% of the Claude subscription's 7-day window")
    monkeypatch.setattr(mafia, "run_debrief", debrief)
    monkeypatch.setattr(mafia, "run_lessons", lambda *a, **k: ran.append("lessons"))
    monkeypatch.setattr(mafia, "build_tips", lambda *a, **k: ran.append("tips"))
    config = mafia.GameConfig([Model.HAIKU_5_5], Model.HAIKU_5_5, DEFAULT_SETUP, 7, debrief=True,
                              update_tips=tmp_path / "tips.md")
    log = mafia.play_game(MockClient(7), config)
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert ran == ["debrief"]  # lessons, review and the tips build were skipped
    [stop] = [r for r in records if r["kind"] == "plan_limit"]
    assert stop["alert"] and "7-day window" in stop["error"]
    result = next(r for r in records if r["kind"] == "result")
    assert result["errors"]["plan_limit"] == 1
    assert not any(r["kind"] in ("crash", "tips_update") for r in records)


def test_an_answer_cut_off_at_the_output_cap_comes_back_as_length_without_a_retry():
    """The CLI reports its output cap as a failed call; retrying it the same way fails again, so it comes back like
    OpenRouter's finish_reason "length", for the caller's retry at lower effort (Players.ask, tips.ask)."""
    cut = {"type": "result", "subtype": "success", "is_error": True, "stop_reason": "stop_sequence",
           "result": "API Error: Claude's response exceeded the 200 output token maximum. To configure this behavior, "
                     "set the CLAUDE_CODE_MAX_OUTPUT_TOKENS environment variable."}
    cli = FakeCli(("events", [cut]))
    client = ClaudeCodeClient(None, runner=cli, max_tokens=200)
    reply = client.chat(Model.OPUS_5_5, player_messages(), schema=SCHEMA)
    assert reply.finish_reason == "length" and reply.content is None and len(cli.runs) == 1
    assert cli.runs[0]["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "200"  # set although CLAUDE* variables are dropped


def test_tools_outside_games_use_the_cli_where_it_s_installed(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(claude_code, "available", lambda: True)
    client = claude_code.default_client(max_tokens=64_000)
    assert isinstance(client, ClaudeCodeClient) and client.other is None and client.max_tokens == 64_000
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setattr(claude_code, "available", lambda: False)
    assert not isinstance(claude_code.default_client(), ClaudeCodeClient)
