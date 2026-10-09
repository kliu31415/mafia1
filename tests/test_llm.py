"""The OpenRouter client, with the network call replaced."""

import json

from llm import Model, OpenRouterClient
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

    client.chat(Model.GPT_6_LUNA, [], schema=None)
    assert "provider" not in bodies[-1]  # other providers' models are routed by OpenRouter as usual
