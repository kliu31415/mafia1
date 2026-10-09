"""The OpenRouter client, with the network call replaced."""

import json

from llm import PROVIDERS, Model, ModelSpec, OpenRouterClient, byok_cost, text_of
from mafia import resolve_effort
from tests.conftest import make_game

REFUSAL = {"provider": "Azure", "choices": [{"finish_reason": "content_filter", "message": {
    "role": "assistant", "content": None, "refusal": "This request was blocked."}}], "usage": {"cost": 0}}


def test_claude_goes_only_to_anthropic_and_a_refusal_is_logged_with_its_reason(tmp_path, monkeypatch):
    client = OpenRouterClient("test-key")
    bodies: list[dict] = []

    def post(body: dict) -> dict:
        bodies.append(body)
        return REFUSAL
    monkeypatch.setattr(client, "_post", post)
    game, players = make_game(tmp_path, ["Vanilla Villager", "Grunt"], client)  # type: ignore[arg-type]
    out = players.ask(game.player("Alice"), "Vote.", {"type": "object", "properties": {}, "required": [],
                                                      "additionalProperties": False}, {"fallback": True})
    assert out == {"fallback": True}
    assert bodies[0]["provider"] == {"order": ["Anthropic"], "allow_fallbacks": False}
    game.log.close()
    errors = [r for r in map(json.loads, (tmp_path / "test.jsonl").read_text(encoding="utf-8").splitlines())
              if r["kind"] == "player_error"]
    assert len(errors) == 2 and "content_filter via Azure: This request was blocked." in errors[0]["error"]

    for m in Model:  # every model is pinned to one provider
        assert m.value.split("/")[0] in PROVIDERS
    client.chat(Model.GPT_6_LUNA, [], tools=[{"type": "function"}])
    assert bodies[-1]["provider"] == {"order": ["OpenAI"], "allow_fallbacks": False}


def test_errors_are_alerted_counted_and_reported(tmp_path, monkeypatch, capsys):
    import mafia
    from llm import MockClient
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    client = MockClient(3)
    real_chat = client.chat

    def chat(model, messages, **kw):  # Bob's answers are always empty; post-game reviews break
        reply = real_chat(model, messages, **kw)
        if kw.get("schema_name") == "review":
            raise RuntimeError("review broke")
        if "You are Bob" in json.dumps(messages) and kw.get("schema"):
            reply.content, reply.stop_note = None, "finish_reason content_filter via Azure: blocked"
        return reply
    monkeypatch.setattr(client, "chat", chat)
    roles = ["Vanilla Villager", "Vanilla Villager", "Vanilla Villager", "Grunt", "Grunt"]
    path = mafia.play_game(client, [Model.HAIKU_5_5], Model.HAIKU_5_5, roles, seed=3, review=True)
    out = capsys.readouterr().out
    assert "ALERT player_fallback: Bob" in out and "ALERT feedback_error: Reviewing the log failed" in out
    assert out.count("ALERT player_error: Bob") == 3  # then only logged
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    result = records[-1]
    assert result["kind"] == "result" and result["errors"]["feedback_error"] == 1
    assert result["errors"]["player_error"] == sum(r["kind"] == "player_error" for r in records) > 3
    report = path.with_name(path.stem + "_feedback.md").read_text(encoding="utf-8")
    assert "## Errors (things to fix)" in report and "content_filter via Azure" in report


def test_a_failed_request_falls_back_instead_of_stopping_the_game(tmp_path):
    import urllib.error
    from tests.conftest import ScriptedClient

    class DownClient(ScriptedClient):
        def chat(self, model, messages, **kw):
            raise urllib.error.URLError("connection reset")
    game, players = make_game(tmp_path, ["Vanilla Villager", "Grunt"], DownClient())  # type: ignore[arg-type]
    out = players.ask(game.player("Alice"), "Vote.", {"type": "object", "properties": {}, "required": []},
                      {"fallback": True})
    assert out == {"fallback": True}
    assert game.log.error_counts == {"player_error": 2, "player_fallback": 1}
    assert "couldn't be used" in game.history_for("Alice") and "couldn't be used" not in game.history_for("Bob")


def test_errors_show_in_the_html_and_text_views(tmp_path):
    from log_viewer import render_html
    game, _ = make_game(tmp_path, ["Vanilla Villager", "Grunt"])
    game.log.error("player_error", "Alice (haiku-5.5), attempt 1: empty answer (blocked)", player="Alice")
    game.log.error("crash", "the game stopped: boom", traceback="Traceback ...")
    game.log.close()
    page = render_html(game.log.path).read_text(encoding="utf-8")
    assert "2 errors: 1 player_error, 1 crash" in page and "href='#error-1'" in page and "id='error-1'" in page
    assert "Traceback ..." in page
    text = game.log.path.with_suffix(".txt").read_text(encoding="utf-8")
    assert "[ERROR crash] the game stopped: boom" in text


def test_unreviewed_errors_are_listed_until_acknowledged(tmp_path, monkeypatch, capsys):
    import os
    import sys
    import alerts
    log = tmp_path / "game_20261009_000000_1.jsonl"
    rec = [{"t": 0, "kind": "setup"}, {"t": 1, "kind": "player_error", "alert": True, "error": "Bob broke"},
           {"t": 2, "kind": "result", "errors": {"player_error": 1}}]
    log.write_text("\n".join(json.dumps(r) for r in rec) + "\n", encoding="utf-8")
    killed = tmp_path / "game_20261009_000000_2.jsonl"  # no result, untouched for hours: killed
    killed.write_text(json.dumps({"t": 0, "kind": "setup"}) + "\n", encoding="utf-8")
    os.utime(killed, (0, 0))
    running = tmp_path / "game_20261009_000000_3.jsonl"  # no result, but still being written
    running.write_text(json.dumps({"t": 0, "kind": "setup"}) + "\n", encoding="utf-8")
    clean = tmp_path / "game_20261009_000000_4.jsonl"
    clean.write_text(json.dumps({"t": 0, "kind": "result"}) + "\n", encoding="utf-8")

    games = alerts.unreviewed(tmp_path)
    assert [g["game"] for g in games] == [log.stem, killed.stem]
    assert "1 player_error" in alerts.describe(games) and "probably killed" in alerts.describe(games)
    assert "Unreviewed errors in 2 games" in (alerts.pending_line(tmp_path) or "")
    monkeypatch.setattr(sys, "argv", ["alerts.py", "--hook", "--logs", str(tmp_path)])
    alerts.main()
    assert "tell Kevin" in capsys.readouterr().out

    alerts.ack(tmp_path, ["all"])
    assert alerts.unreviewed(tmp_path) == [] and alerts.pending_line(tmp_path) is None
    alerts.main()
    assert capsys.readouterr().out == ""  # the hook stays quiet once everything is reviewed
    with log.open("a", encoding="utf-8") as f:  # a new error in a reviewed game brings it back
        f.write(json.dumps({"t": 3, "kind": "crash", "alert": True, "error": "boom"}) + "\n")
    assert [g["game"] for g in alerts.unreviewed(tmp_path)] == [log.stem]


def test_an_answer_that_breaks_its_schema_is_an_error_and_still_costs(tmp_path):
    import dataclasses
    from llm import schema_errors
    from players import VOTE_SCHEMA
    from tests.conftest import ScriptedClient
    assert schema_errors({"vote": "yes"}, VOTE_SCHEMA) == ["answer.vote should be boolean, not \"yes\""]
    assert schema_errors({"to": "Zed"}, {"anyOf": [{"type": "string", "enum": ["Bob"]}, {"type": "null"}]})

    class OffSchema(ScriptedClient):  # a provider that ignores strict structured output
        def chat(self, model, messages, **kw):
            reply = super().chat(model, messages, **kw)
            return dataclasses.replace(reply, content=json.dumps({"vote": "Zed"}), cost=0.01)
    game, players = make_game(tmp_path, ["Vanilla Villager", "Grunt"], OffSchema())  # type: ignore[arg-type]
    assert players.ask(game.player("Alice"), "Vote.", VOTE_SCHEMA, {"vote": False}) == {"vote": False}
    game.log.close()
    from gamelog import usage_by_caller
    [alice, _] = usage_by_caller(game.log.path, [{"name": "Alice", "model": "m"}, {"name": "Bob", "model": "m"}])
    assert alice["calls"] == alice["failed_calls"] == 2 and alice["cost"] == 0.02 and alice["fallbacks"] == 1


def test_an_answer_with_no_cost_is_an_error(tmp_path):
    client = OpenRouterClient("test-key")
    errors: list[str] = []
    client.on_error = lambda kind, summary, **data: errors.append(kind)
    client._post = lambda body: {"choices": [{"message": {"content": "{}"}}], "usage": {}}  # type: ignore[method-assign]
    client.chat(Model.GPT_6_LUNA, [])
    assert errors == ["api_error"]


def test_prompts_cache_what_repeats_and_other_models_get_plain_text(tmp_path, monkeypatch):
    client = OpenRouterClient("test-key")
    bodies: list[dict] = []
    monkeypatch.setattr(client, "_post", lambda body: bodies.append(body) or REFUSAL)
    game, players = make_game(tmp_path, ["Vanilla Villager", "Grunt"], client)  # type: ignore[arg-type]
    game.emit("Day 1 chat.")
    game.phase = "night"
    game.emit("Night 1 news.")
    schema = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    players.ask(game.player("Alice"), "Act.", schema, {})
    system, user = bodies[0]["messages"]
    cached = [b["text"] for b in system["content"] if "cache_control" in b]
    # The rules alone (shared with every call), then the general instructions, then Alice's own part,
    # which ends with what she saw in earlier phases; the current phase is in the uncached user message.
    assert len(cached) == 3 and cached[0] == "(rules)" and "Day 1 chat." in cached[2]
    assert "Night 1 news." in user["content"] and "Day 1 chat." not in user["content"]
    assert "cache_control" not in bodies[0]

    game.player("Alice").model = Model.GPT_6_LUNA  # other makers cache on their own and get plain strings
    players.ask(game.player("Alice"), "Act.", schema, {})
    assert isinstance(bodies[-1]["messages"][0]["content"], str)
    assert bodies[-1]["messages"][0]["content"] == text_of(system["content"])


def test_each_model_has_its_own_default_effort(monkeypatch):
    client = OpenRouterClient("test-key")
    bodies: list[dict] = []
    monkeypatch.setattr(client, "_post", lambda body: bodies.append(body) or REFUSAL)
    client.chat(Model.SONNET_5_5, [])
    client.chat(Model.QWEN_3_8_MAX, [])  # high runs past the token cap
    client.chat(Model.QWEN_3_8_MAX, [], effort="low")  # a spec's own effort wins
    assert [b["reasoning"]["effort"] for b in bodies] == ["high", "medium", "low"]
    assert resolve_effort(ModelSpec(Model.QWEN_3_8_MAX), None).effort == "medium"
    assert resolve_effort(ModelSpec(Model.QWEN_3_8_MAX), "xhigh").effort == "xhigh"  # --effort
    assert resolve_effort(ModelSpec(Model.OPUS_5_5, "low"), "xhigh").effort == "low"


def test_gemini_gets_nullable_enums_in_the_form_it_accepts(monkeypatch):
    client = OpenRouterClient("test-key")
    bodies: list[dict] = []
    monkeypatch.setattr(client, "_post", lambda body: bodies.append(body) or REFUSAL)
    schema = {"type": "object", "properties": {"role": {"anyOf": [{"type": "string", "enum": ["Medic", "Seer"]},
                                                                 {"type": "null"}]}},
              "required": ["role"], "additionalProperties": False}
    client.chat(Model.GEMINI_3_8_FLASH, [], schema=schema)
    client.chat(Model.HAIKU_5_5, [], schema=schema)  # Claude rejects the flat form
    sent = [b["response_format"]["json_schema"]["schema"]["properties"]["role"] for b in bodies]
    assert sent == [{"type": ["string", "null"], "enum": ["Medic", "Seer", None]}, schema["properties"]["role"]]


def test_a_byok_call_costs_the_provider_bill_plus_openrouters_fee():
    assert byok_cost({"cost": 0.001, "is_byok": True, "cost_details": {"upstream_inference_cost": 0.02}}) == 0.021
    assert byok_cost({"cost": 0.02, "is_byok": False, "cost_details": {"upstream_inference_cost": 0.02}}) == 0.02
    assert byok_cost({"is_byok": False}) is None
