"""The moderator's tools and the night check."""

import json

import pytest

import feedback
import mafia
import moderator
from llm import LLMReply, Model, ModelSpec
from moderator import Moderator
from night import run_night
from players import VOTE_SCHEMA
from tests.conftest import ScriptedClient, told


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


def test_an_op_that_fails_after_its_checks_says_which_earlier_ops_were_applied(game_factory, monkeypatch):
    from roles.prosecutor import Prosecutor
    game, players = game_factory(["Prosecutor", "Vanilla Villager", "Vanilla Villager", "Grunt"])
    game.phase = "night"
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")

    def broken(self, game, c):  # a bug in our own code, which the batch's checks can't catch
        raise KeyError("oops")
    monkeypatch.setattr(Prosecutor, "apply_op", broken)
    changes = [{"op": "kill", "player": "Bob"}, {"op": "prosecute", "by": "Alice", "player": "Dave"}]
    with pytest.raises(RuntimeError, match="change 1 \\(prosecute\\) failed: KeyError.*Changes 0-0 were applied"):
        mod.dispatch("apply_changes", {"changes": changes})
    assert not game.player("Bob").alive  # so the moderator mustn't send the kill again


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
    path = mafia.play_game(ScriptedClient(decide),
        mafia.GameConfig([Model.HAIKU_5_5], Model.HAIKU_5_5, roles, seed=1,
                         check_nights=True))
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
                                         "killer_role": "Grunt", "killers": ["Carol"], "killer_roles": ["Grunt"],
                                         "katana": True}
    with pytest.raises(ValueError, match="no player"):
        mod.dispatch("apply_changes", {"changes": [{"op": "kill", "player": "Alice", "by": "Zed"}]})
    # Several fatal attacks: every killer is recorded (R12 reveals every fatal cause).
    mod.dispatch("apply_changes", {"changes": [{"op": "kill", "player": "Alice", "cause": "Katana and Jester's revenge",
                                                "by": ["Carol", "Dave"], "katana": True}]})
    assert game.player("Alice").death["killers"] == ["Carol", "Dave"]
    assert game.player("Alice").death["killer_roles"] == ["Grunt", "Jester"]
    with pytest.raises(ValueError, match="no player"):
        mod.dispatch("apply_changes", {"changes": [{"op": "kill", "player": "Carol", "by": ["Dave", "Zed"]}]})


def test_lessons_include_the_moderators_strategy_review(tmp_path, monkeypatch):
    lesson = {"topic": "deception", "applies_to": "Yakuza", "tip": "don't PM your partner on Day 1",
              "evidence": "Alice's PMs to Heidi"}

    def decide(name, task, schema):
        return {"summary": "Village read the PMs.", "lessons": [lesson]} if "evidence" in str(schema) else None
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    roles = ["Vanilla Villager", "Vanilla Villager", "Vanilla Villager", "Grunt", "Grunt"]
    path = mafia.play_game(ScriptedClient(decide),
        mafia.GameConfig([Model.HAIKU_5_5], Model.HAIKU_5_5, roles, seed=1,
                         lessons=True))
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


def test_two_kills_of_one_player_in_a_batch_are_rejected(game_factory):
    # game_20261009_164356_960898: the second kill (the Katana's) was silently dropped with its katana flag.
    game, players = game_factory(["Vanilla Villager", "Vanilla Villager", "Grunt"])
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    with pytest.raises(ValueError, match="one kill"):
        mod.dispatch("apply_changes", {"changes": [{"op": "kill", "player": "Bob", "cause": "Serial Killer"},
                                                   {"op": "kill", "player": "Bob", "cause": "Katana", "katana": True}]})
    assert game.player("Bob").alive


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
        players.ask(p, "Vote.", VOTE_SCHEMA, {"vote": False}, step="trial_vote")
    assert schemas and not any("thoughts" in json.dumps(s) for s in schemas)
    assert all("reason" in s["required"] for s in schemas)


def test_a_players_reason_is_logged_but_never_returned_to_the_game(game_factory):
    client = ScriptedClient(lambda name, task, schema: {"vote": True, "reason": "Erin's vote was odd."})
    game, players = game_factory(["Vanilla Villager", "Grunt"], client)
    assert players.ask(game.player("Alice"), "Vote.", VOTE_SCHEMA, {"vote": False}, step="trial_vote") == {"vote": True}
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


def test_a_token_count_below_zero_is_reset_and_warned(game_factory):
    # game_20261009_232916_370745: set_tokens 0 plus a prosecute op that spent the token again.
    game, players = game_factory(["Prosecutor", "Vanilla Villager", "Grunt"])
    game.player("Alice").tokens["prosecutor"] = 1
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    out = mod.dispatch("apply_changes", {"changes": [
        {"op": "set_tokens", "player": "Alice", "token": "prosecutor", "value": 0},
        {"op": "prosecute", "player": "Carol", "by": "Alice"}]})
    assert game.player("Alice").tokens["prosecutor"] == 0 and any("below 0" in n for n in out["notes"])


def test_a_night_tell_to_a_player_whose_result_code_delivers_is_held_once(game_factory):
    game, players = game_factory(["Philanthropist", "Medic", "Vanilla Villager", "Grunt"])
    game.phase = "night"
    game.night_actions[game.day] = {"Alice": {"act": True, "target": "Bob"}, "Bob": {"act": True, "target": "Carol"}}
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    told = lambda name: [e.text for e in game.events if e.visible_to is not None and name in e.visible_to]  # noqa: E731
    out = mod.dispatch("tell", {"to": ["Alice"], "text": "You handed Bob a token."})
    assert out["ok"] is False and "Not sent to Alice: code already gives" in out["note"] and not told("Alice")
    mod.dispatch("tell", {"to": ["Alice"], "text": "You were attacked but survived."})  # resent: goes through
    assert told("Alice") == ["Moderator (private): You were attacked but survived."]
    assert mod.dispatch("tell", {"to": ["Bob"], "text": "Done."})["ok"]  # a Medic's result comes from the moderator
    assert game.log.error_counts == {}


def test_ending_the_night_with_a_held_tell_unsent_is_refused_once(game_factory):
    game, players = game_factory(["Philanthropist", "Vanilla Villager", "Grunt"])
    game.phase = "night"
    game.night_actions[game.day] = {"Alice": {"act": True, "target": "Bob"}}
    game.night_visits[game.day] = []
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    assert mod.dispatch("tell", {"to": ["Alice"], "text": "You handed Bob a token. You were attacked."})["ok"] is False
    out = mod.dispatch("end_phase", {"summary": ""})
    assert out["ok"] is False and "Alice" in out["note"]
    assert mod.dispatch("end_phase", {"summary": ""})["ok"]  # nothing else to send: the second end_phase goes through


def test_a_resent_held_tell_lets_the_night_end(game_factory):
    game, players = game_factory(["Philanthropist", "Vanilla Villager", "Grunt"])
    game.phase = "night"
    game.night_actions[game.day] = {"Alice": {"act": True, "target": "Bob"}}
    game.night_visits[game.day] = []
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    mod.dispatch("tell", {"to": ["Alice"], "text": "You handed Bob a token. You were attacked."})
    mod.dispatch("tell", {"to": ["Alice"], "text": "You were attacked but survived."})
    assert mod.dispatch("end_phase", {"summary": ""})["ok"]


def test_a_held_tell_still_reaches_the_other_recipients(game_factory):
    # Yakuza summaries to the whole team went nowhere when one teammate had a code-given result, then were split.
    game, players = game_factory(["Archivist", "Grunt", "Grunt", "Vanilla Villager", "Vanilla Villager"])
    game.phase = "night"
    game.night_actions[game.day] = {"Alice": {"act": True, "target": None}}
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    out = mod.dispatch("tell", {"to": ["Alice", "Bob", "Carol"], "text": "Yakuza actions tonight: ..."})
    assert out["ok"] is False and out["note"].startswith("Sent to Bob, Carol. Not sent to Alice")
    assert told(game, "Bob") == told(game, "Carol") == ["Moderator (private): Yakuza actions tonight: ..."]
    assert told(game, "Alice") == []


def test_tells_to_a_player_killed_tonight_or_whose_op_was_refused_go_through(game_factory):
    game, players = game_factory(["Archivist", "Profiler", "Grunt", "Vanilla Villager", "Vanilla Villager"])
    game.phase = "night"
    game.night_actions[game.day] = {"Alice": {"act": True, "target": None}, "Bob": {"act": True, "target": "Bob"}}
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    game.kill("Alice", "Katana")
    assert mod.dispatch("tell", {"to": ["Alice"], "text": "You were attacked and died."})["ok"]
    with pytest.raises(ValueError):  # game_20261010_053523_23052: then the result was made by hand
        mod.dispatch("apply_changes", {"changes": [{"op": "profile", "player": "Bob", "by": "Bob"}]})
    assert mod.dispatch("tell", {"to": ["Bob"], "text": "Your profile: ..."})["ok"]


def test_a_token_use_counted_by_both_set_tokens_and_the_op_is_noted(game_factory):
    game, players = game_factory(["Prosecutor", "Vanilla Villager", "Grunt"])
    game.player("Alice").tokens["prosecutor"] = 2
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    out = mod.dispatch("apply_changes", {"changes": [
        {"op": "set_tokens", "player": "Alice", "token": "prosecutor", "value": 1}]})
    assert "notes" not in out
    out = mod.dispatch("apply_changes", {"changes": [{"op": "prosecute", "player": "Carol", "by": "Alice"}]})
    assert game.player("Alice").tokens["prosecutor"] == 0
    assert "Check Alice's prosecutor tokens, now 0" in out["notes"][0]


def test_code_tells_the_yakuza_their_choices_and_night_victims_their_death(game_factory):
    # Moderator accuracy audit, Oct 11 2026: hand-written summaries and death notices were inconsistent.
    def decide(name, task, schema):
        if name in ("Alice", "Bob"):
            return {"act": name == "Bob", "target": "Dave" if name == "Bob" else None,
                    "katana_vote_holder": "Alice", "katana_vote_target": "Carol"}
    game, players = game_factory(["Grunt", "Pharmacist", "Vanilla Villager", "Vanilla Villager", "Medic"],
                                 ScriptedClient(decide, moderator_calls=[("apply_changes", {"changes": [
                                     {"op": "kill", "player": "Carol", "cause": "Katana", "by": "Alice",
                                      "katana": True}]})]))
    run_night(game, players, Moderator(game, players.client, players, Model.HAIKU_5_5, "(rules)"))
    assert told(game, "Carol")[-1] == "Moderator (private): You were attacked tonight (Katana) and died."
    assert told(game, "Alice")[-1] == ("Moderator (private): Yakuza night summary: Alice holds the Katana and chose to "
                                       "attack Carol. Bob (Pharmacist) chose to act on Dave.")
    assert told(game, "Bob")[-1] == ("Moderator (private): Yakuza night summary: Alice holds the Katana and chose to "
                                     "attack Carol. Alice (Grunt) chose no action.")
    assert not any("Yakuza night summary" in t for n in ("Carol", "Dave", "Erin") for t in told(game, n))


def test_everyone_can_update_their_will_with_the_night_action_and_it_stands_if_they_die(game_factory):
    # Kevin, Oct 12 2026 (rules R13): three players died with that night's target missing from their will.
    def decide(name, task, schema):
        if name == "Alice":
            return {"katana_vote_holder": "Alice", "katana_vote_target": "Carol"}
        if name in ("Carol", "Dave"):
            return {"last_will": f"{name}: no night action, Vanilla."}
        if name == "Erin":
            return {"act": True, "target": "Dave", "last_will": "Erin - Medic. N1: protecting Dave."}
    game, players = game_factory(["Grunt", "Pharmacist", "Vanilla Villager", "Vanilla Villager", "Medic"],
                                 ScriptedClient(decide, moderator_calls=[("apply_changes", {"changes": [
                                     {"op": "kill", "player": "Carol", "cause": "Katana", "by": "Alice",
                                      "katana": True}]})]))
    run_night(game, players, Moderator(game, players.client, players, Model.HAIKU_5_5, "(rules)"))
    assert {n for n, task in players.client.asked if "update your last will" in task} == {
        "Alice", "Bob", "Carol", "Dave", "Erin"}  # Vanilla Villagers too
    assert "Carol" not in game.night_actions[1] and "Dave" not in game.night_actions[1]  # no action to record
    assert all("last_will" not in a for a in game.night_actions[1].values())
    assert not game.player("Carol").alive and game.player("Carol").last_will == "Carol: no night action, Vanilla."
    assert game.player("Erin").last_will == "Erin - Medic. N1: protecting Dave."
    assert game.player("Bob").last_will == ""  # an empty answer keeps the old will


def test_the_moderator_models_post_game_calls_run_together_and_the_log_keeps_its_order(tmp_path, monkeypatch):
    """after_game starts the moderator's debrief, the strategy review and the log review in threads while the
    players' rounds run; each step still writes its records in order (the log views start a section per step)."""
    import threading
    from llm import MockClient

    met = threading.Barrier(3, timeout=20)  # passes only if all three calls are running at once
    threads: list[str] = []

    class Client(MockClient):
        def chat(self, model, messages, **kw):
            if threading.current_thread().name.startswith("post-game"):
                threads.append(kw["schema_name"])
                met.wait()
            return super().chat(model, messages, **kw)
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    roles = ["Vanilla Villager", "Vanilla Villager", "Vanilla Villager", "Grunt", "Grunt"]
    path = mafia.play_game(Client(1), mafia.GameConfig([Model.HAIKU_5_5], Model.HAIKU_5_5, roles, seed=1,
                                                       debrief=True, lessons=True, review=True))
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert sorted(threads) == ["debrief", "review", "strategy_review"]
    assert not [r for r in records if r.get("alert")]
    post = [r["kind"] if r["kind"] != "debrief" else f"debrief:{r['who'] == 'moderator'}" for r in records
            if r["kind"] in ("section", "debrief", "lessons", "strategy_review", "review")]
    n = len(roles)
    assert post == (["section", *["debrief:False"] * n, "debrief:True", "section", *["lessons"] * n,
                     "section", "strategy_review", "section", "review"])
    sections = [r["title"] for r in records if r["kind"] == "section"]
    assert sections == list(feedback.POST_GAME_SECTIONS.values())


def test_a_plan_limit_in_a_post_game_thread_stops_its_step_and_skips_the_later_ones(tmp_path, monkeypatch):
    from claude_code import PlanLimitError
    from llm import MockClient

    class Client(MockClient):
        def chat(self, model, messages, **kw):
            if kw.get("schema_name") == "strategy_review":
                raise PlanLimitError("games have a cap of 70% of the Claude subscription's 7-day window")
            return super().chat(model, messages, **kw)
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    roles = ["Vanilla Villager", "Vanilla Villager", "Vanilla Villager", "Grunt", "Grunt"]
    path = mafia.play_game(Client(1), mafia.GameConfig([Model.HAIKU_5_5], Model.HAIKU_5_5, roles, seed=1,
                                                       debrief=True, lessons=True, review=True))
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    [stop] = [r for r in records if r["kind"] == "plan_limit"]
    assert stop["step"] == "Collecting the moderator's strategy review"
    assert {"debrief", "lessons"} <= {r["kind"] for r in records}
    assert not [r for r in records if r["kind"] in ("strategy_review", "review", "crash")]
    assert records[-1]["kind"] == "result" and records[-1]["errors"] == {"plan_limit": 1}
