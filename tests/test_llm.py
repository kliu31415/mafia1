"""The OpenRouter client, with the network call replaced."""

import json

from llm import PROVIDERS, Model, OpenRouterClient
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
