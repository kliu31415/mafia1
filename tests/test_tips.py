"""Tips from past games: building a tips file from logs, and showing it to the chosen players."""

import json
import random

import pytest

import mafia
import tips
from tests.conftest import TOWN4_GRUNT, ScriptedClient
from llm import LLMReply, Model, ModelSpec, text_of
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
    alice = text_of(player_messages(game, game.player("Alice"), "(rules)", "task")[0]["content"])
    bob = text_of(player_messages(game, game.player("Bob"), "(rules)", "task")[0]["content"])
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
    path = mafia.play_game(client,
        mafia.GameConfig([Model.HAIKU_5_5, Model.GPT_6_LUNA], Model.HAIKU_5_5, TOWN4_GRUNT, seed=1,
                         tips=tips_file, tips_for="gpt-6-luna", player_tips=[("Alice", other)], lessons=True))
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


class TipsClient:
    """Answers notebook updates with queued ops and the sheet call with fixed sections, and keeps each prompt."""

    def __init__(self, ops: list[list[dict]]):
        self.total_cost: dict[str, float] = {}
        self.ops = ops
        self.prompts: list[tuple[str, str]] = []  # (schema name, user prompt)

    def chat(self, model, messages, *, tools=None, schema=None, schema_name="response", effort=None):
        self.prompts.append((schema_name, messages[-1]["content"]))
        if schema_name == "notebook_ops":
            content = json.dumps({"ops": self.ops.pop(0)})
        else:
            content = json.dumps({"sections": [
                {"heading": "Medic", "tips": [{"tip": "Protect a claimed Sheriff.", "games": 2}]},
                {"heading": "Everyone", "tips": [{"tip": "Count the votes.", "games": 1}, {"tip": " ", "games": 1}]},
                {"heading": "Yakuza", "tips": []}]})
        return LLMReply(content, None, [], {"role": "assistant", "content": content}, model.value, 0.0, {})


def op(kind, id="", tip="", audience="Everyone", weight=0.5, note=""):
    return {"op": kind, "id": id, "audience": audience, "tip": tip, "weight": weight, "note": note}


def test_the_notebook_and_sheet_are_built_from_game_logs(tmp_path):
    log = tmp_path / "game_20261009_000000_1.jsonl"
    records = [
        {"kind": "setup", "settings": {"mock": False}},
        *[{"kind": "player_fallback", "player": "Ivan"}] * 3,
        {"kind": "lessons", "who": "Alice", "role": "Medic", "model": "anthropic/claude-haiku-5.5",
         "lessons": [{"topic": "night actions", "applies_to": "Medic", "tip": "Guard the Sheriff."}]},
        {"kind": "strategy_review", "model": "anthropic/claude-opus-5.5", "summary": "The Village won on day 3.",
         "lessons": [{"topic": "deduction", "applies_to": "everyone", "tip": "Track votes.",
                      "evidence": "Day 2 vote."}]},
        {"kind": "result", "winners": ["Alice"], "winning_faction": "Village", "end_reason": "win", "days": 3,
         "roles": {"Alice": "Medic", "Ivan": "Grunt"},
         "models": {"Alice": "anthropic/claude-haiku-5.5", "Ivan": "anthropic/claude-opus-5.5"},
         "errors": {"player_fallback": 3}},
    ]
    log.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    (tmp_path / "game_20261009_000001_2.jsonl").write_text(json.dumps({"kind": "setup"}) + "\n", encoding="utf-8")
    client = TipsClient([[op("add", tip="Guard the Sheriff.", audience="Medic", weight=0.28, note="Alice"),
                          op("add", tip="Track votes.", weight=0.7, note="Day 2 vote"),
                          op("support", id="t99", weight=1.0)]])  # an unknown id is skipped
    out = tips.build(sorted(tmp_path.glob("game_*.jsonl")), tmp_path / "tips.md", client,
                     ModelSpec(Model.OPUS_5_5), max_words=500)
    (_, update), (_, sheet) = client.prompts
    assert "Guard the Sheriff" in update and "Track votes" in update and "Day 2 vote" in update
    assert "Distrust lessons from Ivan" in update and "[Alice, Medic, won" in update
    # Average player strength (2 + 5) / 2 = 3.5: Haiku's lesson weighs 0.4 * 0.7, the Opus moderator's 1.0 * 0.7.
    assert "average player strength 3.5/5" in update
    assert "claude-haiku-5.5, weight 0.28]" in update and "[moderator, weight 0.7]" in update
    assert "[t1] (Medic) Guard the Sheriff. | support: 1 games" in sheet and "[t2] (Everyone) Track votes." in sheet
    nb = json.loads(tips.notebook_path(out).read_text(encoding="utf-8"))
    assert nb["games"] == ["game_20261009_000000_1"] and len(nb["entries"]) == 2  # the game without lessons is skipped
    text = out.read_text(encoding="utf-8")
    assert "2 active entries" in text and "(1 games)" in text
    assert text.index("## Everyone") < text.index("## Medic") and "## Yakuza" not in text
    assert "- Protect a claimed Sheriff. (seen in 2 games)" in text
    assert tips.player_view(text).startswith("## Everyone\n- Count the votes.")
    assert "Guard the Sheriff" in tips.notebook_path(out).with_suffix(".md").read_text(encoding="utf-8")

    # After another game, only that game updates the notebook, and the old sheet and notebook are kept.
    newer = tmp_path / "game_20261010_000000_3.jsonl"
    newer.write_text("\n".join(json.dumps(r) for r in [
        {"kind": "tips", "players": ["Alice"]},
        {"kind": "lessons", "who": "Alice", "role": "Medic", "model": "anthropic/claude-haiku-5.5", "lessons": [],
         "tips_feedback": [{"tip": "Track votes.", "verdict": "hurt", "why": "Yakuza voted in a block."}]},
        {"kind": "result", "winners": [], "roles": {}, "models": {}},
    ]) + "\n", encoding="utf-8")
    client.ops = [[op("against", id="t2", weight=0.16, note="Yakuza voted in a block"),
                   op("edit", id="t1", tip="Guard a claimed Sheriff.", audience="Medic", note="sharper"),
                   op("support", id="t1", weight=0.3, note="again"), op("retire", id="t2", note="backfired")]]
    tips.build(sorted(tmp_path.glob("game_*.jsonl")), out, client, ModelSpec(Model.OPUS_5_5), max_words=500)
    (_, update), (_, sheet) = client.prompts[2:]
    assert "[t1] (Medic) Guard the Sheriff. | support: 1 games" in update  # the notebook so far
    assert 'FEEDBACK ON THE TIPS SHEET, hurt: "Track votes." because Yakuza voted' in update
    assert "given a tips sheet from earlier games: Alice" in update
    assert "Track votes" not in sheet and "[t1] (Medic) Guard a claimed Sheriff. | support: 2 games" in sheet
    nb = json.loads(tips.notebook_path(out).read_text(encoding="utf-8"))
    t1, t2 = nb["entries"]
    assert t1["history"][-1]["old"] == "Guard the Sheriff." and t2["status"] == "retired" and len(t2["against"]) == 1
    assert sorted(p.name.split("_2026")[0] for p in (tmp_path / "history").iterdir()) == ["tips"]
    with pytest.raises(tips.NoNewGames, match="already has all 2 games"):
        tips.build(sorted(tmp_path.glob("game_*.jsonl")), out, client, ModelSpec(Model.OPUS_5_5), max_words=500)


def test_older_logs_count_failed_last_attempts_as_fallbacks(tmp_path):
    log = tmp_path / "game_20261008_000000_1.jsonl"  # before player_fallback records existed
    records = [*[{"kind": "player_error", "player": "Ivan", "attempt": a} for a in (0, 1)] * 3,
               *[{"kind": "player_error", "player": "Bob", "attempt": a} for a in (0, 0, 1)],
               {"kind": "lessons", "who": "Bob", "role": "Grunt", "model": "x", "lessons": []},
               {"kind": "result", "winners": []}]
    log.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    g = tips.read_game(log)
    assert g is not None and g["unreliable"] == ["Ivan"]


def test_a_game_can_update_the_tips_when_it_ends(tmp_path, monkeypatch):
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    sheet = tmp_path / "tips" / "tips.md"
    mafia.play_game(ScriptedClient(),
        mafia.GameConfig([Model.HAIKU_5_5], Model.HAIKU_5_5, TOWN4_GRUNT, seed=1, lessons=True,
                         update_tips=sheet))
    nb = json.loads(tips.notebook_path(sheet).read_text(encoding="utf-8"))
    assert len(nb["games"]) == 1 and sheet.exists()


def test_strength_comes_from_the_model_registry():
    assert tips.strength(Model.OPUS_5_5.value) == 5 and tips.strength("someone/dropped-model") == tips.DEFAULT_STRENGTH


def test_parallel_builds_of_one_sheet_take_turns(tmp_path, monkeypatch):
    import threading
    import time
    sheet, order = tmp_path / "tips.md", []

    def slow_build(name):
        with tips.locked(sheet):
            order.append(f"{name} start")
            time.sleep(0.2)
            order.append(f"{name} end")
    threads = [threading.Thread(target=slow_build, args=(n,)) for n in "ab"]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert [o.split()[1] for o in order] == ["start", "end", "start", "end"]
    assert not sheet.with_name("tips.md.lock").exists()
    # A lock left by a process that died is taken over.
    sheet.with_name("tips.md.lock").touch()
    monkeypatch.setattr(tips, "LOCK_STALE_S", -1)
    with tips.locked(sheet):
        pass


def test_a_revision_rewords_and_retires_entries_without_counting_a_game(tmp_path):
    out = tmp_path / "tips.md"
    nb = tips.new_notebook()
    tips.apply_ops(nb, [op("add", tip="Read the flipped role.", weight=0.5, note="g1"),
                        op("add", tip="Guard the Sheriff.", audience="Medic", weight=0.5, note="g1")], "g1")
    tips.notebook_path(out).write_text(json.dumps(nb), encoding="utf-8")
    out.write_text("# old sheet\n", encoding="utf-8")
    client = TipsClient([[op("retire", id="t1", note="flips are hidden"), op("support", id="t2", weight=1.0),
                          op("add", tip="Hunt Neutral killers.", note="revision: asked for")]])
    tips.revise(out, client, ModelSpec(Model.OPUS_5_5), max_words=500, note="Add a tip on hunting Neutral killers.")
    (_, revision), (_, sheet) = client.prompts
    assert "no new game is attached" in revision and "Add a tip on hunting Neutral killers." in revision
    assert "flipped role" not in sheet and "Hunt Neutral killers." in sheet
    nb = json.loads(tips.notebook_path(out).read_text(encoding="utf-8"))
    t1, t2, t3 = nb["entries"]
    assert nb["games"] == ["g1"] and t1["status"] == "retired" and t1["history"][-1]["game"].startswith("revision ")
    assert len(t2["support"]) == 1 and t3.get("pinned") and not t2.get("pinned")  # a revision adds no evidence
    assert [p.read_text(encoding="utf-8") for p in (tmp_path / "history").iterdir()] == ["# old sheet\n"]


def test_pinned_entries_are_marked_for_the_sheet(tmp_path):
    out = tmp_path / "tips.md"
    nb = tips.new_notebook()
    tips.apply_ops(nb, [op("add", tip="Spend tokens while alive.", weight=0.0, note="revision")], "g1")
    tips.notebook_path(out).write_text(json.dumps(nb), encoding="utf-8")
    client = TipsClient([])
    tips.pin(out, client, ModelSpec(Model.OPUS_5_5), max_words=500, ids=["t1"])
    (_, sheet), = client.prompts
    assert "[t1] (Everyone) Spend tokens while alive. | PINNED" in sheet and "Every PINNED entry goes on" in sheet
    tips.pin(out, client, ModelSpec(Model.OPUS_5_5), max_words=500, ids=["t1"], unpin=True)
    assert "PINNED:" not in client.prompts[-1][1]
    with pytest.raises(SystemExit, match="t9"):
        tips.pin(out, client, ModelSpec(Model.OPUS_5_5), max_words=500, ids=["t9"])


def test_a_tips_answer_cut_off_at_the_output_cap_is_asked_again_one_effort_lower():
    class CutOnce:
        def __init__(self):
            self.efforts: list = []
            self.alerts: list = []
            self.on_error = lambda kind, error, **data: self.alerts.append((kind, data))

        def chat(self, model, messages, *, schema=None, schema_name="", effort=None, tools=None):
            self.efforts.append(effort)
            cut = len(self.efforts) == 1
            return LLMReply(content=None if cut else '{"ops": []}', reasoning=None, tool_calls=[], message={},
                            model=model.value, cost=0.5, usage={}, finish_reason="length" if cut else None)
    client = CutOnce()
    spec = ModelSpec(Model.OPUS_5_5, "high")
    reply = tips.ask(client, spec, [], tips.OPS_SCHEMA, "notebook_ops")  # type: ignore[arg-type]
    assert client.efforts == ["high", "medium"] and reply.content == '{"ops": []}' and reply.cost == 1.0
    assert client.alerts == [("effort_fallback", {"from_effort": "high", "to_effort": "medium"})]
