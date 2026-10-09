"""Tips from past games: building a tips file from logs, and showing it to the chosen players."""

import json
import random

import pytest

import mafia
import tips
from tests.conftest import TOWN4_GRUNT, ScriptedClient
from llm import LLMReply, Model, ModelSpec
from players import player_messages

TIPS = """# Notes for whoever edits this
Never shown to players.

## Everyone
- Count the votes.

## Village
- Trust Sheriff results.

## Yakuza
- Claim Medic.

## Grunt
- Vote with the crowd.

## Odd heading
- Shown to everyone.
"""


def test_players_see_every_section_but_not_the_preamble():
    view = tips.player_view(TIPS)
    assert all(t in view for t in ["Count the votes", "Trust Sheriff", "Claim Medic", "Vote with the crowd"])
    assert "Never shown" not in view and view.startswith("## Everyone")


def test_tips_go_into_the_system_prompt_of_players_who_have_them(game_factory):
    game, players = game_factory(TOWN4_GRUNT)
    game.player("Alice").tips = TIPS
    alice = player_messages(game, game.player("Alice"), "(rules)", "task")[0]["content"]
    bob = player_messages(game, game.player("Bob"), "(rules)", "task")[0]["content"]
    assert "Tips from past games" in alice and "Trust Sheriff" in alice and "Claim Medic" in alice
    assert "Tips from past games" not in bob


def test_choosing_who_gets_tips():
    names, models = ["Alice", "Bob", "Carol", "Dave", "Erin"], ["opus-5.5", "haiku-5.5"] * 2 + ["opus-5.5"]
    assert tips.choose_players(names, models, "all", random.Random(0)) == names
    half = tips.choose_players(names, models, "half", random.Random(0))
    assert len(half) == 2 and half == tips.choose_players(names, models, "half", random.Random(0))
    assert tips.choose_players(names, models, "Bob,opus-5.5", random.Random(0)) == ["Alice", "Bob", "Carol", "Erin"]
    with pytest.raises(ValueError, match="Zed"):
        tips.choose_players(names, models, "Zed", random.Random(0))


def test_choosing_each_players_tips_file(tmp_path):
    names, models = ["Alice", "Bob", "Carol", "Dave"], ["opus-5.5", "haiku-5.5", "opus-5.5", "haiku-5.5"]
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    spec = tips.parse_player_tips(f"Carol=none, haiku-5.5={b},Bob={a}")
    assert spec == [("Carol", None), ("haiku-5.5", b), ("Bob", a)]
    # --tips a.md for everyone, then the Haiku players get b.md, except Bob (named) keeps a.md; Carol gets none.
    assert tips.assign_tips(names, models, a, "all", spec, random.Random(0)) == {"Alice": a, "Bob": a, "Dave": b}
    assert tips.assign_tips(names, models, None, "all", [("Dave", a)], random.Random(0)) == {"Dave": a}
    with pytest.raises(ValueError, match="Zed"):
        tips.assign_tips(names, models, None, "all", [("Zed", a)], random.Random(0))
    with pytest.raises(ValueError, match="WHO=FILE"):
        tips.parse_player_tips("Alice")


def test_a_game_logs_who_had_tips_and_how_they_went(tmp_path, monkeypatch):
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    tips_file = tmp_path / "tips.md"
    tips_file.write_text(TIPS, encoding="utf-8")
    feedback = [{"tip": "Count the votes.", "verdict": "helped", "why": "Caught a Grunt."}]

    def decide(name, task, schema):
        return {"tips_feedback": feedback} if "tips_feedback" in schema["properties"] else None
    other = tmp_path / "other.md"
    other.write_text("## Everyone\n- Older advice.\n", encoding="utf-8")
    client = ScriptedClient(decide)
    path = mafia.play_game(client, [Model.HAIKU_5_5, Model.GPT_6_LUNA], Model.HAIKU_5_5, TOWN4_GRUNT, seed=1,
                           tips=tips_file, tips_for="gpt-6-luna", player_tips=[("Alice", other)], lessons=True)
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    record = next(r for r in records if r["kind"] == "tips")
    result = next(r for r in records if r["kind"] == "result")
    luna = sorted(p["name"] for p in result["players"] if p["model"] == Model.GPT_6_LUNA.value)
    assert "Alice" not in luna
    had = sorted(["Alice", *luna])
    assert sorted(record["players"]) == had and sorted(p["name"] for p in result["players"] if p["tips"]) == had
    assert record["files"] == {"Alice": str(other), **{n: str(tips_file) for n in luna}}
    assert record["texts"] == {str(tips_file): TIPS, str(other): other.read_text(encoding="utf-8")}
    html = path.with_suffix(".html").read_text(encoding="utf-8")
    assert html.count("Tips for <") == len(had) and "Older advice" in html and "Claim Medic" in html
    # Only players with tips (and the moderator's review) are asked how the tips went.
    lessons = {r["who"]: r for r in records if r["kind"] == "lessons"}
    assert all(lessons[n].get("tips_feedback") == (feedback if n in had else None) for n in lessons)
    assert next(r for r in records if r["kind"] == "strategy_review")["tips_feedback"] == feedback
    assert "Caught a Grunt" in path.with_name(path.stem + "_feedback.md").read_text(encoding="utf-8")


class DistillClient:
    """Answers the distill call with fixed sections and remembers the prompt."""

    def __init__(self):
        self.total_cost: dict[str, float] = {}
        self.prompt = ""

    def chat(self, model, messages, *, tools=None, schema=None, schema_name="response", effort=None):
        self.prompt = messages[-1]["content"]
        content = json.dumps({"sections": [
            {"heading": "Medic", "tips": [{"tip": "Protect a claimed Sheriff.", "games": 2}]},
            {"heading": "Everyone", "tips": [{"tip": "Count the votes.", "games": 1}, {"tip": " ", "games": 1}]},
            {"heading": "Yakuza", "tips": []}]})
        return LLMReply(content, None, [], {"role": "assistant", "content": content}, model.value, 0.0, {})


def test_building_a_tips_file_from_game_logs(tmp_path):
    log = tmp_path / "game_20261009_000000_1.jsonl"
    records = [
        {"kind": "setup", "settings": {"mock": False}},
        *[{"kind": "player_fallback", "player": "Ivan"}] * 3,
        {"kind": "lessons", "who": "Alice", "role": "Medic", "model": "anthropic/claude-haiku-5.5",
         "lessons": [{"topic": "night actions", "applies_to": "Medic", "tip": "Guard the Sheriff."}]},
        {"kind": "strategy_review", "model": "anthropic/claude-opus-5.5", "summary": "The Village won on day 3.", "lessons": [
            {"topic": "deduction", "applies_to": "everyone", "tip": "Track votes.", "evidence": "Day 2 vote."}]},
        {"kind": "result", "winners": ["Alice"], "winning_faction": "Village", "end_reason": "win", "days": 3,
         "roles": {"Alice": "Medic", "Ivan": "Grunt"},
         "models": {"Alice": "anthropic/claude-haiku-5.5", "Ivan": "anthropic/claude-opus-5.5"}, "errors": {"player_fallback": 3}},
    ]
    log.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    (tmp_path / "game_20261009_000001_2.jsonl").write_text(json.dumps({"kind": "setup"}) + "\n", encoding="utf-8")
    client = DistillClient()
    out = tips.build(sorted(tmp_path.glob("game_*.jsonl")), tmp_path / "tips.md", client,
                     ModelSpec(Model.OPUS_5_5), max_words=500)
    assert "Guard the Sheriff" in client.prompt and "Track votes" in client.prompt and "Day 2 vote" in client.prompt
    assert "Distrust lessons from Ivan" in client.prompt and "[Alice, Medic, won" in client.prompt
    # Average player strength (2 + 5) / 2 = 3.5: Haiku's lesson weighs 0.4 * 0.7, the Opus moderator's 1.0 * 0.7.
    assert "average player strength 3.5/5" in client.prompt
    assert "claude-haiku-5.5, weight 0.28]" in client.prompt and "[moderator, weight 0.7]" in client.prompt
    text = out.read_text(encoding="utf-8")
    assert "1 new games, 1 in all" in text  # the game without lessons is skipped
    assert text.index("## Everyone") < text.index("## Medic") and "## Yakuza" not in text
    assert "- Protect a claimed Sheriff. (seen in 2 games)" in text
    assert tips.player_view(text).startswith("## Everyone\n- Count the votes.")

    # Run again after another game: the file is revised with only the new game, and the old one is kept.
    newer = tmp_path / "game_20261010_000000_3.jsonl"
    newer.write_text("\n".join(json.dumps(r) for r in [
        {"kind": "tips", "players": ["Alice"]},
        {"kind": "lessons", "who": "Alice", "role": "Medic", "model": "anthropic/claude-haiku-5.5", "lessons": [],
         "tips_feedback": [{"tip": "Count the votes.", "verdict": "hurt", "why": "Yakuza voted in a block."}]},
    ]) + "\n", encoding="utf-8")
    tips.build(sorted(tmp_path.glob("game_*.jsonl")), out, client, ModelSpec(Model.OPUS_5_5), max_words=500)
    assert "Revise it" in client.prompt and "## Medic\n- Protect a claimed Sheriff. (seen in 2 games)" in client.prompt
    assert "Guard the Sheriff" not in client.prompt  # the first game is already in the sheet
    assert 'FEEDBACK ON THE TIPS SHEET, hurt: "Count the votes." because Yakuza voted' in client.prompt
    assert "given a tips sheet from earlier games: Alice" in client.prompt
    assert "Games: game_20261009_000000_1, game_20261010_000000_3." in out.read_text(encoding="utf-8")
    assert [p.read_text(encoding="utf-8") for p in (tmp_path / "history").iterdir()] == [text]
    with pytest.raises(SystemExit, match="already has all 2 games"):
        tips.build(sorted(tmp_path.glob("game_*.jsonl")), out, client, ModelSpec(Model.OPUS_5_5), max_words=500)


def test_every_model_has_a_strength():
    assert set(tips.STRENGTH) == set(Model)
