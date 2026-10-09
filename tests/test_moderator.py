"""The moderator's tools and the night check."""

import pytest

import mafia
from llm import LLMReply, Model, ModelSpec
from moderator import Moderator
from tests.conftest import ScriptedClient


def test_malformed_moderator_ops_change_nothing(game_factory):
    game, players = game_factory(["Vanilla Villager", "Vanilla Villager", "Grunt"])
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    bad = [{"op": "kill", "player": "Bob"}, {"op": "set_tokens", "player": "Bob", "token": "x"}]
    with pytest.raises(ValueError, match="missing"):
        mod.dispatch("apply_changes", {"changes": bad})
    assert game.player("Bob").alive
    with pytest.raises(ValueError, match="no player"):
        mod.dispatch("apply_changes", {"changes": [{"op": "kill", "player": "Zed"}]})
    out = mod.dispatch("apply_changes", {"changes": [{"op": "kill", "player": "Bob", "who": "x"}]})
    assert "unknown fields" in out["notes"][0] and not game.player("Bob").alive


def test_status_key_typo_gets_a_hint(game_factory):
    game, players = game_factory(["Vanilla Villager", "Vanilla Villager", "Grunt"])
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    out = mod.dispatch("apply_changes", {"changes": [{"op": "set_status", "player": "Bob", "key": "clean",
                                                      "value": True}]})
    assert "cleaned" in out["notes"][0]


def test_night_check_logs_the_judges_verdict(tmp_path, monkeypatch):
    issue = {"rule": "R3", "severity": "high", "kind": "wrong death", "description": "defense ignored"}

    def decide(name, task, schema):
        return {"verdict": "errors", "issues": [issue]} if name is None and "verdict" in schema["properties"] else None
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    roles = ["Vanilla Villager", "Vanilla Villager", "Vanilla Villager", "Grunt", "Grunt"]
    path = mafia.play_game(ScriptedClient(decide), [Model.HAIKU_5_5], Model.HAIKU_5_5, roles, seed=1,
                           check_nights=True)
    import json
    checks = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
              if '"night_check"' in line]
    assert checks and all(c["verdict"] == "errors" and c["issues"] == [issue] for c in checks)
    assert sorted(c["night"] for c in checks) == list(range(1, len(checks) + 1))
    assert all(c["alive"] == len(c["roles_in_play"]) == 5 for c in checks)  # nobody dies in this game
    report = path.with_name(path.stem + "_feedback.md").read_text(encoding="utf-8")
    assert "Night checks" in report and "defense ignored" in report
    assert "Night check" in path.with_suffix(".html").read_text(encoding="utf-8")


def test_kills_record_the_killer_and_their_role(game_factory):
    game, players = game_factory(["Vigilante", "Vanilla Villager", "Grunt", "Jester"])
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    game.phase = "night"
    mod.dispatch("apply_changes", {"changes": [
        {"op": "kill", "player": "Bob", "cause": "Vigilante", "by": "Alice"},
        {"op": "kill", "player": "Dave", "cause": "Katana", "by": "Carol", "katana": True}]})
    assert game.player("Bob").death["killer_role"] == "Vigilante" and not game.player("Bob").death["katana"]
    assert game.player("Dave").death == {"day": 1, "phase": "night", "cause": "Katana", "killer": "Carol",
                                         "killer_role": "Grunt", "katana": True}
    with pytest.raises(ValueError, match="no player"):
        mod.dispatch("apply_changes", {"changes": [{"op": "kill", "player": "Alice", "by": "Zed"}]})


def test_lessons_include_the_moderators_strategy_review(tmp_path, monkeypatch):
    lesson = {"topic": "deception", "applies_to": "Yakuza", "tip": "don't PM your partner on Day 1",
              "evidence": "Alice's PMs to Heidi"}

    def decide(name, task, schema):
        return {"summary": "Village read the PMs.", "lessons": [lesson]} if "evidence" in str(schema) else None
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    roles = ["Vanilla Villager", "Vanilla Villager", "Vanilla Villager", "Grunt", "Grunt"]
    path = mafia.play_game(ScriptedClient(decide), [Model.HAIKU_5_5], Model.HAIKU_5_5, roles, seed=1,
                           lessons=True)
    import json
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [r["lessons"] for r in records if r["kind"] == "strategy_review"] == [[lesson]]
    shared = [json.loads(line) for line in (tmp_path / "lessons.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r for r in shared if r["source"] == "moderator"] == [
        {"game": path.stem, "source": "moderator", "player": None, "role": "Moderator",
         "model": Model.HAIKU_5_5.value, "won": None, **lesson}]
    report = path.with_name(path.stem + "_feedback.md").read_text(encoding="utf-8")
    assert "Moderator strategy review" in report and "don't PM your partner" in report


def test_an_empty_moderator_answer_is_an_error(game_factory):
    from llm import LLMReply

    class Refuses(ScriptedClient):
        def chat(self, model, messages, *, tools=None, **kw):
            if tools and not any(m.get("role") == "tool" for m in messages) and len(messages) < 4:
                return LLMReply(None, None, [], {"role": "assistant", "content": None}, model.value, 0.0, {},
                                stop_note="finish_reason content_filter via X: blocked")
            return super().chat(model, messages, tools=tools, **kw)
    client = Refuses()
    game, players = game_factory(["Vanilla Villager", "Vanilla Villager", "Grunt"], client)
    Moderator(game, client, players, Model.HAIKU_5_5, "(rules)").run_phase("Resolve.")
    assert game.log.error_counts == {"moderator_error": 1}


def test_killing_a_dead_player_is_a_warning(game_factory):
    game, players = game_factory(["Vanilla Villager", "Vanilla Villager", "Grunt"])
    game.kill("Bob", "Katana")
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    out = mod.dispatch("apply_changes", {"changes": [{"op": "kill", "player": "Bob"}]})
    assert "already dead" in out["notes"][0] and game.log.error_counts == {"moderator_warning": 1}


def test_a_moderator_the_filter_keeps_blocking_switches_to_its_fallback(game_factory):
    blocked = LLMReply(None, None, [], {"role": "assistant", "content": None}, "m", 0.0, {},
                       stop_note="finish_reason content_filter via Anthropic: blocked")

    class Filtered(ScriptedClient):
        def __init__(self, blocks: int):
            super().__init__()
            self.blocks, self.models = blocks, list[Model]()

        def chat(self, model, messages, *, tools=None, **kw):
            self.models.append(model)
            if tools and model is Model.OPUS_5_5 and self.blocks:
                self.blocks -= 1
                return blocked
            return super().chat(model, messages, tools=tools, **kw)

    for blocks, switched in [(2, False), (3, True)]:
        client = Filtered(blocks)
        game, players = game_factory(["Vanilla Villager", "Grunt"], client)
        mod = Moderator(game, client, players, Model.OPUS_5_5, "(rules)",
                        fallback=ModelSpec(Model.GPT_6_1_SOL, "high"))
        mod.run_phase("Resolve the night.")
        assert (mod.model is Model.GPT_6_1_SOL) is switched
        assert (client.models[-1] is Model.GPT_6_1_SOL) is switched  # the phase went on with the fallback
        assert ("moderator_switch" in game.log.error_counts) is switched
