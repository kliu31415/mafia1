"""The moderator's tools and the night check."""

import json

import pytest

import mafia
import moderator
from llm import LLMReply, Model, ModelSpec
from moderator import Moderator
from night import run_night
from players import VOTE_SCHEMA
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
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [r["lessons"] for r in records if r["kind"] == "strategy_review"] == [[lesson]]
    shared = [json.loads(line) for line in (tmp_path / "lessons.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r for r in shared if r["source"] == "moderator"] == [
        {"game": path.stem, "source": "moderator", "player": None, "role": "Moderator",
         "model": Model.HAIKU_5_5.value, "won": None, **lesson}]
    report = path.with_name(path.stem + "_feedback.md").read_text(encoding="utf-8")
    assert "Moderator strategy review" in report and "don't PM your partner" in report


def test_an_empty_moderator_answer_is_an_error(game_factory):
    class Empty(ScriptedClient):
        def chat(self, model, messages, *, tools=None, **kw):
            if tools and not any(m.get("role") == "tool" for m in messages) and len(messages) < 4:
                return LLMReply(None, None, [], {"role": "assistant", "content": None}, model.value, 0.0, {},
                                stop_note="finish_reason length via X: no refusal text")
            return super().chat(model, messages, tools=tools, **kw)
    client = Empty()
    game, players = game_factory(["Vanilla Villager", "Vanilla Villager", "Grunt"], client)
    Moderator(game, client, players, Model.HAIKU_5_5, "(rules)").run_phase("Resolve.")
    assert game.log.error_counts == {"moderator_error": 1}


def test_killing_a_dead_player_is_a_warning(game_factory):
    game, players = game_factory(["Vanilla Villager", "Vanilla Villager", "Grunt"])
    game.kill("Bob", "Katana")
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    out = mod.dispatch("apply_changes", {"changes": [{"op": "kill", "player": "Bob"}]})
    assert "already dead" in out["notes"][0] and game.log.error_counts == {"moderator_warning": 1}


def test_a_moderator_the_filter_keeps_blocking_switches_to_its_fallback(game_factory, monkeypatch):
    monkeypatch.setattr(moderator, "MODERATOR_RETRY_WAIT_S", 0)
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


class FilteringClient(ScriptedClient):
    """Its first `blocks` moderator calls come back blocked by a content filter; records moderator prompts."""

    def __init__(self, *args, blocks: int = 0, **kwargs):
        super().__init__(*args, **kwargs)
        self.blocks = blocks
        self.moderator_prompts: list[list[dict]] = []

    def chat(self, model, messages, *, tools=None, **kwargs):
        if tools:
            self.moderator_prompts.append([dict(m) for m in messages])
            if self.blocks:
                self.blocks -= 1
                msg = {"role": "assistant", "content": None}
                return LLMReply(None, None, [], msg, model.value, 0.0, {},
                                stop_note="finish_reason content_filter via Anthropic: blocked")
        return super().chat(model, messages, tools=tools, **kwargs)


def test_a_filtered_moderator_answer_is_retried_unchanged(game_factory, monkeypatch):
    monkeypatch.setattr(moderator, "MODERATOR_RETRY_WAIT_S", 0)
    game, players = game_factory(["Vanilla Villager", "Vanilla Villager", "Grunt"])
    client = FilteringClient(blocks=2)
    mod = Moderator(game, client, players, Model.HAIKU_5_5, "(rules)")
    mod.run_phase("Resolve the night.")
    assert len(client.moderator_prompts) == 3
    assert client.moderator_prompts[0] == client.moderator_prompts[2]  # no empty answer or nudge appended


def test_no_player_answer_has_a_thoughts_field(game_factory):
    """Written-out reasoning in an answer looks like distillation to Anthropic's filter (gamelog v23)."""
    schemas = []
    game, players = game_factory(["Vigilante", "Vanilla Villager", "Grunt", "Grunt"],
                                 ScriptedClient(lambda name, task, schema: schemas.append(schema)))
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    game.phase = "night"
    run_night(game, players, mod)
    for p in game.players:
        players.ask(p, "Vote.", VOTE_SCHEMA, {"vote": False})
    assert schemas and not any("thoughts" in json.dumps(s) for s in schemas)
    assert all("reason" in s["required"] for s in schemas)


def test_a_players_reason_is_logged_but_never_returned_to_the_game(game_factory):
    client = ScriptedClient(lambda name, task, schema: {"vote": True, "reason": "Erin's vote was odd."})
    game, players = game_factory(["Vanilla Villager", "Grunt"], client)
    assert players.ask(game.player("Alice"), "Vote.", VOTE_SCHEMA, {"vote": False}) == {"vote": True}
    assert "Erin's vote was odd." in game.log.path.read_text(encoding="utf-8")


def test_the_moderator_gets_a_readable_state_summary(game_factory):
    game, _ = game_factory(["Clerk", "Medic", "Vanilla Villager", "Grunt", "Prosecutor"])
    game.katana_holder = "Alice"
    game.kill("Bob", "Katana")
    game.rigged_day = game.day + 1
    game.prosecutions.append("Carol")
    summary = game.state_summary()
    assert "seat 1: Alice (Clerk, Yakuza)" in summary and "holds the Katana" in summary
    assert "Dead: Bob (Medic" in summary and "seat 2" not in summary
    assert f"Clerk's rig on day {game.day + 1}" in summary and "Carol is prosecuted next day" in summary
