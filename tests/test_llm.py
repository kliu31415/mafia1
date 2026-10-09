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
