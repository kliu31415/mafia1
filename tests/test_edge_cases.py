"""Unhandled errors and edge cases found by code sweeps: each test is one that used to crash, go
unnoticed, or give a wrong result."""

import dataclasses
import http.client
import io
import json
import os
import sys

import pytest

import mafia
import moderator as moderator_module
from llm import LLMReply, MockClient, Model, OpenRouterClient, lower_effort
from moderator import Moderator
from players import NOTEPAD_WORDS, truncate_words, word_count
from roles import DEFAULT_SETUP, Status
from tests.conftest import TOWN4_GRUNT, VILLAGE5, ScriptedClient, make_game

ROLES5 = ["Vanilla Villager", "Vanilla Villager", "Vanilla Villager", "Grunt", "Grunt"]


def records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# --- LLM requests and answers --------------------------------------------------------------------

class FakeResponse:
    def __init__(self, body: bytes, fail: Exception | None = None):
        self.body, self.fail, self.sent = body, fail, False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size: int = -1):
        if self.fail:
            raise self.fail
        body, self.sent = (b"" if self.sent else self.body), True
        return body


def test_dropped_connections_and_provider_errors_in_an_answer_are_retried(monkeypatch):
    ok = json.dumps({"choices": [{"message": {"content": "{}"}}], "usage": {"cost": 0.01}}).encode()
    answers = iter([FakeResponse(b"", http.client.RemoteDisconnected("closed")),  # dropped while reading
                    FakeResponse(b"<html>Bad gateway</html>"),  # not JSON
                    FakeResponse(json.dumps({"error": {"code": 502, "message": "provider died"}}).encode()),
                    FakeResponse(ok)])
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: next(answers))
    monkeypatch.setattr("time.sleep", lambda s: None)
    client = OpenRouterClient("key")
    seen: list[str] = []
    client.on_error = lambda kind, summary, **data: seen.append(kind)
    assert client.chat(Model.GPT_6_LUNA, []).content == "{}"
    assert seen == ["api_retry"] * 3

    client.retries = 0  # out of retries: a clear error, not a bare JSON or connection error
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: FakeResponse(b"not json"))
    with pytest.raises(RuntimeError, match="failed after 1 attempts"):
        client.chat(Model.GPT_6_LUNA, [])


def test_a_call_past_its_deadline_is_retried_once_then_fails(monkeypatch):
    class KeptAlive(FakeResponse):  # whitespace forever, as a stuck provider behind a keep-alive could send
        def read(self, size: int = -1):
            return b" "
    calls: list[float] = []

    def urlopen(req, timeout):
        calls.append(timeout)
        return KeptAlive(b"")
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr("time.sleep", lambda s: None)
    client = OpenRouterClient("key", timeout=0.01)
    seen: list[str] = []
    client.on_error = lambda kind, summary, **data: seen.append(kind)
    with pytest.raises(RuntimeError, match="timed out"):
        client.chat(Model.GPT_6_LUNA, [])
    assert len(calls) == 2 and seen == ["api_retry"]


def test_a_lone_surrogate_in_a_models_text_is_replaced(game_factory):
    def decide(name, task, schema):
        if name == "Alice" and "public_message" in schema["properties"]:
            return {"public_message": "Hello \ud83d"}
        return None
    game, players = game_factory(TOWN4_GRUNT, ScriptedClient(decide))
    from day import chat_turn
    game.player("Alice").speaking_budget = 3.0
    chat_turn(game, players, game.player("Alice"), rnd=1, can_nominate=False)
    game.log.close()
    assert "Hello �" in game.log.path.with_suffix(".txt").read_text(encoding="utf-8")


def test_words_count_in_scripts_without_spaces_and_in_very_long_words():
    assert word_count("Vote Bob today") == 3
    assert word_count("我们应该投票给鲍勃") == 9  # one word per character
    assert word_count("x" * 100_000) == 5000  # can't dodge the caps by leaving out spaces
    assert truncate_words("我们应该投票给鲍勃", 4) == "我们应该 [truncated]"
    assert word_count(truncate_words("x" * 100_000, NOTEPAD_WORDS).removesuffix(" [truncated]")) == NOTEPAD_WORDS


def test_an_empty_notepad_keeps_the_notepad_and_a_retry_says_what_was_wrong(game_factory):
    answers = iter([{"notepad": "plan"}, {"notepad": ""}])
    game, players = game_factory(TOWN4_GRUNT, ScriptedClient(lambda name, task, schema: next(answers, None)))
    schema = {"type": "object", "properties": {}, "required": []}
    for _ in range(2):
        players.ask(game.player("Alice"), "Note something.", schema, {}, step="day_turn")
    assert game.player("Alice").notepad == "plan"

    class OnceBroken(ScriptedClient):
        def __init__(self):
            super().__init__()
            self.calls: list[list[dict]] = []

        def chat(self, model, messages, **kw):
            self.calls.append(messages)
            reply = super().chat(model, messages, **kw)
            return dataclasses.replace(reply, content='{"vote": "yes"}') if len(self.calls) == 1 else reply
    client = OnceBroken()
    game, players = game_factory(TOWN4_GRUNT, client)
    from players import VOTE_SCHEMA
    players.ask(game.player("Alice"), "Vote.", VOTE_SCHEMA, {"vote": False}, step="trial_vote")
    assert "couldn't be used" in client.calls[1][-1]["content"] and "answer.vote" in client.calls[1][-1]["content"]


def test_an_answer_cut_off_at_max_tokens_is_retried_at_lower_effort(game_factory):
    class CutOffOnce(ScriptedClient):
        def chat(self, model, messages, **kw):
            reply = super().chat(model, messages, **kw)
            if len(self.efforts) == 1:  # Haiku reasoned past the 16k cap (game_20261010_003734_551955)
                return dataclasses.replace(reply, content=None, finish_reason="length")
            return reply
    client = CutOffOnce()
    game, players = game_factory(TOWN4_GRUNT, client)
    alice = game.player("Alice")
    alice.effort = "high"
    from players import VOTE_SCHEMA
    players.ask(alice, "Vote.", VOTE_SCHEMA, {"vote": False}, step="trial_vote")
    assert client.efforts == [("Alice", "high"), ("Alice", "medium")]
    call = [r for r in records(game.log.path) if r["kind"] == "player_call"][-1]
    assert call["effort"] == "medium"
    assert lower_effort("low") == "low" and lower_effort("max") == "xhigh"


def test_a_night_check_answer_that_breaks_its_schema_is_one_failed_check(tmp_path):
    from night_check import NightChecker

    class BadJudge(ScriptedClient):
        def chat(self, model, messages, **kw):
            content = json.dumps({"verdict": "errors", "issues": [{"rule": "R9", "kind": "other", "description": "x"}]})
            return LLMReply(content, None, [], {}, model.value, 0.0, {})
    game, _ = make_game(tmp_path, TOWN4_GRUNT)
    checker = NightChecker(BadJudge(), Model.OPUS_5_5, Model.OPUS_5_5, "(rules)", game.log)
    state = game.full_state()
    checker.submit(1, "Resolve.", state, [], state)
    checker.finish()
    game.log.close()
    checks = [r for r in records(game.log.path) if r["kind"] == "night_check"]
    assert len(checks) == 1 and checks[0]["verdict"] == "failed" and "severity" in checks[0]["error"]


def test_printing_an_alert_never_fails(monkeypatch, capsys):
    from records import safe_print
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stream)
    safe_print("ALERT x: Bob → Carol \ud83d")
    stream.flush()
    assert b"Bob \\u2192 Carol" in stream.buffer.getvalue()


# --- The moderator -----------------------------------------------------------------------------------

def test_a_failed_moderator_call_is_retried(game_factory, monkeypatch):
    monkeypatch.setattr(moderator_module, "MODERATOR_RETRY_WAIT_S", 0)

    class Flaky(ScriptedClient):
        failures = 1

        def chat(self, model, messages, *, tools=None, **kw):
            if tools and self.failures:
                self.failures -= 1
                raise RuntimeError("OpenRouter HTTP 400: bad")
            return super().chat(model, messages, tools=tools, **kw)
    client = Flaky()
    game, players = game_factory(TOWN4_GRUNT, client)
    Moderator(game, client, players, Model.HAIKU_5_5, "(rules)").run_phase("Resolve.")
    assert game.log.error_counts == {"moderator_error": 1}


def test_tool_calls_after_end_phase_in_the_same_reply_are_carried_out(game_factory):
    class EndsFirst(ScriptedClient):
        def chat(self, model, messages, *, tools=None, **kw):
            calls = [{"id": f"c{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
                     for i, (n, a) in enumerate([("end_phase", {"summary": ""}),
                                                 ("apply_changes", {"changes": [{"op": "kill", "player": "Bob"}]})])]
            return LLMReply(None, None, calls, {"role": "assistant", "tool_calls": calls}, model.value, 0.0, {})
    client = EndsFirst()
    game, players = game_factory(TOWN4_GRUNT, client)
    Moderator(game, client, players, Model.HAIKU_5_5, "(rules)").run_phase("Resolve.")
    assert not game.player("Bob").alive


@pytest.mark.parametrize("change, why", [
    ({"op": "set_tokens", "player": "Bob", "token": "bullets", "value": "--2"}, "integer"),
    ({"op": "kill", "player": "Bob", "katana": "false"}, "true or false"),
    ({"op": "set_status", "player": "Bob", "key": "cleaned", "value": "false"}, "JSON true/false"),
    ({"op": "set_katana", "player": "Alice"}, "not a living Yakuza"),
    ({"op": "set_last_will", "player": "Bob", "text": None}, "must be text"),
])
def test_bad_ops_refuse_the_whole_batch(game_factory, change, why):
    game, players = game_factory(TOWN4_GRUNT)
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    with pytest.raises(ValueError, match=why):
        mod.dispatch("apply_changes", {"changes": [{"op": "kill", "player": "Carol"}, change]})
    assert game.player("Carol").alive  # nothing was applied


def test_set_katana_is_refused_at_night(game_factory):
    """Rules R8: a holder who dies at night passes the Katana on after the night's results, by code, so a
    teammate dying to that night's Jester revenge can't receive it (game_20261010_013419_977337)."""
    game, players = game_factory(TOWN4_GRUNT)
    game.phase = "night"
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    with pytest.raises(ValueError, match="don't set it at night"):
        mod.dispatch("apply_changes", {"changes": [{"op": "set_katana", "player": "Erin"}]})


def test_null_optional_fields_mean_not_given_and_an_unknown_token_is_a_warning(game_factory):
    game, players = game_factory(TOWN4_GRUNT)
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    mod.dispatch("apply_changes", {"changes": [{"op": "kill", "player": "Bob", "by": None, "cause": None}]})
    assert "Bob died (killed)" in game.events[-1].text
    out = mod.dispatch("apply_changes", {"changes": [{"op": "set_tokens", "player": "Carol", "token": "bulets",
                                                      "value": 1}]})
    assert "no 'bulets' tokens" in out["notes"][0] and game.log.error_counts == {"moderator_warning": 1}


@pytest.mark.parametrize("name, args", [
    ("tell", {"to": [], "text": "You were role-blocked."}),
    ("tell", {"to": "all", "text": "Hi"}),
    ("random_choice", {"options": "Alice, Bob", "k": 1}),
    ("random_choice", {"options": ["Alice"], "k": 2}),
])
def test_malformed_tool_arguments_are_errors(game_factory, name, args):
    game, players = game_factory(TOWN4_GRUNT)
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    with pytest.raises(ValueError):
        mod.dispatch(name, args)


def test_a_puppet_op_needs_a_living_puppeteer_and_a_non_yakuza_puppet(game_factory):
    game, players = game_factory(["Puppeteer", "Vanilla Villager", "Vanilla Villager", "Vanilla Villager", "Wiretap"])
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    with pytest.raises(ValueError, match="not a Puppeteer"):
        mod.dispatch("apply_changes", {"changes": [{"op": "puppet", "player": "Carol", "by": "Bob"}]})
    with pytest.raises(ValueError, match="themselves"):
        mod.dispatch("apply_changes", {"changes": [{"op": "puppet", "player": "Alice", "by": "Alice"}]})
    with pytest.raises(ValueError, match="another Yakuza"):
        mod.dispatch("apply_changes", {"changes": [{"op": "puppet", "player": "Erin", "by": "Alice"}]})
    mod.dispatch("apply_changes", {"changes": [{"op": "puppet", "player": "Bob", "by": "Alice"}]})
    assert game.puppets_next == {"Bob": "Alice"}


# --- Game rules ------------------------------------------------------------------------------------

def test_two_prosecutions_of_one_player_are_one_trial(game_factory):
    from day import run_day
    game, players = game_factory(VILLAGE5 + ["Grunt"], ScriptedClient())
    game.prosecutions += ["Bob", "Bob"]
    run_day(game, players)
    assert sum("Bob was prosecuted" in v for v in game.vote_record) == 1


def test_a_survivors_forged_will_and_clean_are_undone(game_factory):
    from night import run_night
    game, players = game_factory(TOWN4_GRUNT, ScriptedClient(moderator_calls=[
        ("apply_changes", {"changes": [{"op": "set_last_will", "player": "Bob", "text": "I am the Grunt."},
                                       {"op": "set_status", "player": "Bob", "key": "cleaned", "value": True}]})]))
    game.player("Bob").last_will = "Sheriff: Erin is Evil."
    mod = Moderator(game, players.client, players, Model.HAIKU_5_5, "(rules)")
    run_night(game, players, mod)
    bob = game.player("Bob")
    assert bob.alive and bob.last_will == "Sheriff: Erin is Evil." and Status.CLEANED not in bob.status


def test_blank_messages_arent_messages_and_a_failed_revision_keeps_the_first_answer(game_factory):
    from day import chat_turn
    turns = iter([{"public_message": "   ", "private_messages": [{"to": "Carol", "text": "word " * 50}]}])

    class RevisionFails(ScriptedClient):
        def chat(self, model, messages, **kw):
            reply = super().chat(model, messages, **kw)
            return dataclasses.replace(reply, content=None) if "WARNING" in messages[-1]["content"] else reply
    game, players = game_factory(VILLAGE5, RevisionFails(lambda n, t, s: next(turns, None) if n == "Alice" else None))
    game.player("Alice").speaking_budget = 0.3
    chat_turn(game, players, game.player("Alice"), rnd=1, can_nominate=False)
    told = [e.text for e in game.events if e.visible_to == {"Alice"}]
    assert not any("public message" in t for t in told)  # the blank one was never planned
    assert any(e.fields.get("to") == "Carol" for e in game.events if e.cat == "pm")  # cut to fit, still sent


# --- Running games: crashes, resumes and logs ----------------------------------------------------------

def test_a_crash_while_setting_up_is_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    monkeypatch.setattr(mafia, "Players", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bad prompt")))
    with pytest.raises(RuntimeError):
        mafia.play_game(MockClient(1), mafia.GameConfig([Model.HAIKU_5_5], Model.HAIKU_5_5, ROLES5, 1))
    [log] = tmp_path.glob("*.jsonl")
    assert "while setting it up: RuntimeError: bad prompt" in records(log)[-1]["error"]


def test_ctrl_c_after_the_game_is_logged_and_doesnt_leave_a_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    monkeypatch.setattr(mafia, "run_lessons", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        mafia.play_game(MockClient(1), mafia.GameConfig([Model.HAIKU_5_5], Model.HAIKU_5_5, ROLES5, 1, lessons=True))
    [log] = tmp_path.glob("*.jsonl")
    assert "after the game" in records(log)[-1]["error"] and not log.with_suffix(".ckpt").exists()
    assert log.with_suffix(".html").exists()


def test_games_started_together_with_one_seed_get_their_own_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    first, second = mafia.new_log("game", 7), mafia.new_log("game", 7)
    assert first.path != second.path
    first.close()
    second.close()


def test_resuming_keeps_the_crash_night_check_errors_and_costs_and_survives_a_torn_line(tmp_path, monkeypatch):
    from checkpoint import load
    seed = 7
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    real_run_night = mafia.run_night

    def crash_on_night_2(game, *args):
        if game.day == 2:
            game.log.write("player_call", player="Alice", model=Model.HAIKU_5_5.value, task="x", output={},
                           cost=0.5)  # paid for, then cut by the resume
            game.log.error("night_check_issue", "night 1: wrong death", night=1)
            raise RuntimeError("laptop went to sleep")
        real_run_night(game, *args)
    monkeypatch.setattr(mafia, "run_night", crash_on_night_2)
    with pytest.raises(RuntimeError):
        mafia.play_game(MockClient(seed), mafia.GameConfig([Model.HAIKU_5_5], Model.HAIKU_5_5, DEFAULT_SETUP, seed))
    [ckpt_path] = tmp_path.glob("*.ckpt")
    log = ckpt_path.with_suffix(".jsonl")
    with log.open("a", encoding="utf-8") as f:
        f.write('{"t": 1, "kind": "player_ca')  # the process died mid-write
    monkeypatch.setattr(mafia, "run_night", real_run_night)
    ckpt = load(ckpt_path)
    mafia.play_game(MockClient(seed), mafia.GameConfig.from_checkpoint(ckpt), resume=ckpt)
    out = records(log)
    result = out[-1]
    assert result["errors"]["crash"] == 1 and result["errors"]["night_check_issue"] == 1
    assert result["errors"]["log_error"] == 1  # the torn line
    resume = next(r for r in out if r["kind"] == "resume")
    assert resume["cut_cost"] == 0.5 and result["cost"][Model.HAIKU_5_5.value] == pytest.approx(0.5)


def test_cli_rejects_settings_that_cant_work(monkeypatch, capsys):
    for argv, why in [(["--max-days", "0"], "at least 1"), (["--tips-for", "half"], "needs --tips"),
                      (["--roles", "random:20"], "1 to 16 players"), (["--resume", "nope.ckpt"], "can't resume")]:
        monkeypatch.setattr(sys, "argv", ["mafia.py", "--mock", *argv])
        with pytest.raises(SystemExit):
            mafia.main()
        assert why in capsys.readouterr().err


# --- Reading logs: viewer, alerts, tips, stats --------------------------------------------------------

def test_the_viewer_shows_unparsable_tool_arguments_and_old_tips_and_skips_torn_lines(tmp_path):
    from log_viewer import render_html
    path = tmp_path / "game_1.jsonl"
    lines = [json.dumps(r) for r in [
        {"kind": "setup", "players": [{"name": "Bob", "seat": 0, "role": "Grunt", "model": "m"}], "katana": "Bob"},
        {"kind": "tips", "players": ["Bob"], "file": "tips.md", "text": "## Everyone\n- Claim early."},  # version 11
        {"kind": "moderator_call", "model": "m", "tool_calls": [
            {"function": {"name": "end_phase", "arguments": '{"summary": "Night 1 resol'}}]},
        {"kind": "moderator_tool", "name": "end_phase", "args": '{"summary": "Night 1 resol', "result": {}},
    ]] + ['{"kind": "even']
    path.write_text("\n".join(lines), encoding="utf-8")
    page = render_html(path).read_text(encoding="utf-8")
    assert "unparsable arguments" in page and "Claim early." in page and "1 unreadable log line" in page


def test_alerts_handle_torn_lines_running_games_and_new_errors_after_a_resume(tmp_path):
    import alerts
    log = tmp_path / "game_20261009_000000_1.jsonl"
    err = lambda t, kind="player_error": json.dumps({"t": t, "kind": kind, "alert": True, "error": "x"})  # noqa: E731
    log.write_text("\n".join([err(1), err(2), err(3, "crash"), '{"t": 4, "kind": "player_ca']), encoding="utf-8")
    [g] = alerts.unreviewed(tmp_path)  # running: the half-written last line isn't counted
    assert g["kinds"] == {"player_error": 2, "crash": 1}
    alerts.ack(tmp_path, ["all"])
    assert alerts.unreviewed(tmp_path) == []
    # Resumed: the cut errors go, the crash stays, and one new error comes; fewer in total, but it's new.
    log.write_text("\n".join([err(3, "crash"), err(9, "api_retry"), json.dumps({"t": 10, "kind": "result"})]) + "\n",
                   encoding="utf-8")
    [g] = alerts.unreviewed(tmp_path)
    assert g["kinds"] == {"crash": 1, "api_retry": 1}
    (tmp_path / "game_20261009_000000_2.jsonl").write_text('{"t": 1, "kind": "setup"}\n{"t": 2\n', encoding="utf-8")
    os.utime(tmp_path / "game_20261009_000000_2.jsonl", (0, 0))
    assert "probably killed" in alerts.describe(alerts.unreviewed(tmp_path))
    (tmp_path / "mock_lessons.jsonl").write_text("{}\n", encoding="utf-8")
    assert not any(g["game"] == "mock_lessons" for g in alerts.unreviewed(tmp_path, "mock"))


def test_alerts_in_progress_stay_listed_apart_until_acked_and_new_errors_reopen_them(tmp_path):
    import alerts
    err = lambda t: json.dumps({"t": t, "kind": "player_error", "alert": True, "error": "x"})  # noqa: E731
    a, b = tmp_path / "game_20261009_000000_1.jsonl", tmp_path / "game_20261009_000000_2.jsonl"
    for log in (a, b):
        log.write_text(err(1) + "\n" + json.dumps({"t": 2, "kind": "result"}) + "\n", encoding="utf-8")
    alerts.mark_in_progress(tmp_path, [a.stem], "waiting on Kevin")
    new, wip = alerts.split_in_progress(tmp_path, alerts.unreviewed(tmp_path))
    assert [g["game"] for g in new] == [b.stem]
    assert [(g["game"], g["note"]) for g in wip] == [(a.stem, "waiting on Kevin")]
    assert "waiting on Kevin" in alerts.describe(new, wip)
    assert alerts.ack(tmp_path, ["all"]) == [b.stem]  # "all" leaves in-progress games alone
    assert alerts.pending_line(tmp_path) is None  # only an in-progress game is left
    a.write_text(err(1) + "\n" + err(5) + "\n", encoding="utf-8")  # a new error makes it new again
    assert [g["game"] for g in alerts.split_in_progress(tmp_path, alerts.unreviewed(tmp_path))[0]] == [a.stem]
    alerts.ack(tmp_path, [a.stem])
    assert alerts.unreviewed(tmp_path) == [] and alerts.load_json(tmp_path / alerts.IN_PROGRESS_FILE) == {}


def test_tips_skip_unfinished_games_and_repeated_ops_and_keep_the_sheet_when_the_new_one_is_empty(tmp_path):
    import tips
    from llm import ModelSpec
    from tests.test_tips import TipsClient, op
    game = lambda n, result=True: [  # noqa: E731
        {"kind": "setup", "settings": {"mock": False}},
        {"kind": "lessons", "who": "Alice", "role": "Medic", "model": "anthropic/claude-haiku-5.5",
         "lessons": [{"topic": "deduction", "applies_to": "everyone", "tip": f"Tip {n}."}]},
    ] + ([{"kind": "result", "winners": [], "roles": {}, "models": {}}] if result else [])
    for n, finished in [(1, True), (2, False)]:
        (tmp_path / f"game_2026100{n}_000000_1.jsonl").write_text(
            "\n".join(json.dumps(r) for r in game(n, finished)) + "\n", encoding="utf-8")
    client = TipsClient([[op("add", tip="Count votes.", weight=0.5), op("add", tip="Count votes.")]])
    out = tips.build(sorted(tmp_path.glob("game_*.jsonl")), tmp_path / "tips.md", client,
                     ModelSpec(Model.OPUS_5_5), 500)
    nb = json.loads(tips.notebook_path(out).read_text(encoding="utf-8"))
    assert nb["games"] == ["game_20261001_000000_1"] and len(nb["entries"]) == 1  # unfinished: not yet
    entry = nb["entries"][0]
    assert entry["support"][0]["weight"] == 0.5  # the repeated add merged into the first
    supports = [op("support", id=entry["id"], weight=0.3, note="Alice saw it."),
                op("support", id=entry["id"], weight=1.0, note="Bob too."),
                op("support", id=entry["id"], weight=1.0, note="Bob too."),
                op("support", weight=float("nan"), id=entry["id"])]
    assert tips.apply_ops(nb, supports + [op("restore", id=entry["id"])], "g2") == 1  # only the restore
    assert len(entry["support"]) == 2  # g1's add, then one from g2 with the higher weight and both notes
    assert entry["support"][1] == {"game": "g2", "weight": 1.0, "note": "Alice saw it.; Bob too."}

    class EmptySheet(TipsClient):
        def chat(self, model, messages, *, schema_name="response", **kw):
            if schema_name == "notebook_ops":
                return super().chat(model, messages, schema_name=schema_name, **kw)
            return LLMReply('{"sections": []}', None, [], {}, model.value, 0.0, {})
    before = out.read_text(encoding="utf-8")
    (tmp_path / "game_20261002_000000_1.jsonl").write_text(
        "\n".join(json.dumps(r) for r in game(2)) + "\n", encoding="utf-8")
    errors: list[str] = []
    tips.build(sorted(tmp_path.glob("game_*.jsonl")), out, EmptySheet([[]]), ModelSpec(Model.OPUS_5_5), 500,
               on_error=lambda kind, summary, **d: errors.append(summary))
    assert out.read_text(encoding="utf-8") == before and "empty sheet" in errors[0]


def test_a_tips_build_flags_a_lock_another_build_took_over(tmp_path, monkeypatch):
    import tips
    monkeypatch.setattr(tips, "LOCK_STALE_S", -1)  # every lock looks stale
    errors: list[str] = []
    with tips.locked(tmp_path / "tips.md", lambda kind, summary, **d: errors.append(summary)) as touch:
        with tips.locked(tmp_path / "tips.md", lambda kind, summary, **d: errors.append(summary)):
            pass
        touch()  # the first build notices it lost the lock
    assert any("took over" in e for e in errors) and any("taken over by another build" in e for e in errors)


def test_tips_cli_mock_builds_dont_touch_the_real_sheet(tmp_path, monkeypatch):
    import tips
    calls = []
    monkeypatch.setattr(tips, "build", lambda paths, out, *a, **k: calls.append(out))
    (tmp_path / "mock_20261009_000000_1.jsonl").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["tips.py", "build", "--mock", str(tmp_path)])
    tips.main()
    assert calls == [tips.ROOT / "logs" / "mock_tips" / "tips.md"]
    monkeypatch.setattr(sys, "argv", ["tips.py", "build", str(tmp_path / "game_2099*.jsonl")])
    with pytest.raises(SystemExit, match="No game logs match"):
        tips.main()


def test_stats_says_what_it_skipped_when_no_games_are_left(tmp_path):
    import stats
    from tests.test_stats import game_records, write_log
    write_log(tmp_path / "game_a.jsonl", game_records()[:-1])
    games, skipped = stats.load_games(stats.log_files([tmp_path]))
    assert stats.report(games, skipped) == "No finished games found. Skipped: 1 unfinished."


# --- Sweep 2 -----------------------------------------------------------------------------------------

def test_the_moderator_cant_remove_a_status_key_role_code_reads(game_factory):
    game, players = game_factory(["Executioner", "Vanilla Villager", "Vanilla Villager", "Grunt"])
    game.player("Alice").status[Status.TARGET] = "Bob"
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    with pytest.raises(ValueError, match="set by code"):
        mod.dispatch("apply_changes", {"changes": [{"op": "set_status", "player": "Alice", "key": "target",
                                                    "value": None}]})
    assert Status.TARGET in game.player("Alice").status


def test_a_checkpoint_resumes_from_the_log_next_to_it(tmp_path, monkeypatch):
    """A checkpoint copied from another machine (sync_logs) names a log path that doesn't exist here."""
    import shutil

    from checkpoint import load
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path / "cloud")
    real_run_night = mafia.run_night

    def crash_on_night_2(game, *args):
        if game.day == 2:
            raise RuntimeError("stopped")
        real_run_night(game, *args)
    monkeypatch.setattr(mafia, "run_night", crash_on_night_2)
    with pytest.raises(RuntimeError):
        mafia.play_game(MockClient(3), mafia.GameConfig([Model.HAIKU_5_5], Model.HAIKU_5_5, DEFAULT_SETUP, 3))
    monkeypatch.setattr(mafia, "run_night", real_run_night)
    pc = tmp_path / "pc"
    shutil.copytree(tmp_path / "cloud", pc)
    shutil.rmtree(tmp_path / "cloud")
    [ckpt_path] = pc.glob("*.ckpt")
    ckpt = load(ckpt_path)
    resumed = mafia.play_game(MockClient(3), mafia.GameConfig.from_checkpoint(ckpt), resume=ckpt)
    assert resumed == ckpt_path.with_suffix(".jsonl")


def test_katana_decisions_are_scored_from_the_revote(tmp_path):
    import stats
    from tests.test_stats import game_records, write_log
    recs = game_records()
    next(r for r in recs if r["kind"] == "katana")["revote_targets"] = {"Erin": "Bob"}  # first voted Alice
    g = stats.load_game(write_log(tmp_path / "game_a.jsonl", recs))
    assert g is not None
    assert not any(d["kind"] == "katana_target" for d in g["decisions"])  # the attack on Alice wasn't Erin's vote


def test_a_roleplayer_looks_exactly_like_their_fake_role(game_factory):
    from players import role_briefing
    from roles import ROLES, logic
    game, players = game_factory(["Roleplayer", "Seer", "Vanilla Villager", "Grunt"])
    rp, seer = game.player("Alice"), game.player("Bob")
    logic("Roleplayer").setup(game, rp)
    assert rp.tokens == ROLES[rp.status[Status.FAKE_ROLE]].tokens
    rp.status[Status.FAKE_ROLE], rp.tokens = "Seer", dict(seer.tokens)  # setup picks at random; pin it
    assert role_briefing(game, rp).replace("Alice (seat 1 of", "Bob (seat 2 of") == role_briefing(game, seer)
    rp.status[Status.FAKE_ROLE] = "Fortune Teller"  # gets results at dawn; never asked for a night action
    assert not logic("Roleplayer").acts_at_night(rp)


def test_a_blank_start_of_day_will_keeps_the_will(game_factory):
    from day import run_day
    game, players = game_factory(VILLAGE5 + ["Grunt"], ScriptedClient(
        lambda name, task, schema: {"last_will": ""} if "last_will" in schema["properties"] and
        task.startswith("Write") else None))
    game.player("Alice").last_will = "I am the Sheriff."
    run_day(game, players)
    assert game.player("Alice").last_will == "I am the Sheriff."


def test_yakuza_who_agree_not_to_attack_get_no_revote(game_factory):
    def decide(name, task, schema):
        if "katana_vote_target" in schema["properties"]:
            return {"katana_vote_holder": "Dave", "katana_vote_target": None, "act": False}  # holder was Carol
        return {"message": "   "} if "message" in schema["properties"] else None
    game, players = game_factory(["Vanilla Villager", "Vanilla Villager", "Grunt", "Grunt"], ScriptedClient(decide))
    game.katana_holder = "Carol"
    from night import run_night
    run_night(game, players, Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)"))
    assert not any("no majority" in e.text for e in game.events)
    assert not any(t.startswith("Revote") for _, t in players.client.asked)
    assert game.katana_holder == "Dave"  # they agreed to move it without attacking (rules R8)
    katana = [json.loads(line) for line in game.log.path.read_text(encoding="utf-8").splitlines()
              if '"kind": "katana"' in line][-1]
    assert katana["result"]["moved_from"] == "Carol"  # so the moderator doesn't say Dave "kept" it
    assert not any("(Yakuza chat):" in e.text for e in game.events)  # a blank message isn't posted


# --- Sweep 3 -----------------------------------------------------------------------------------------

def test_a_finished_game_cant_be_resumed_from_a_stale_checkpoint(tmp_path, monkeypatch, capsys):
    import pickle

    from checkpoint import CHECKPOINT_VERSION
    log = tmp_path / "game_1.jsonl"
    log.write_text('{"kind": "setup"}\n{"kind": "result"}\n', encoding="utf-8")
    log.with_suffix(".ckpt").write_bytes(pickle.dumps({"version": CHECKPOINT_VERSION, "log_path": str(log)}))
    monkeypatch.setattr(sys, "argv", ["mafia.py", "--resume", str(log.with_suffix(".ckpt"))])
    with pytest.raises(SystemExit):
        mafia.main()
    assert "already finished" in capsys.readouterr().err


def test_a_mistyped_tips_name_is_a_cli_error_not_a_crashed_game(tmp_path, monkeypatch, capsys):
    tips = tmp_path / "tips.md"
    tips.write_text("## Everyone\n- Count votes.\n", encoding="utf-8")
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path / "logs")
    for extra in (["--tips", str(tips), "--tips-for", "Zed"], ["--player-tips", f"Zed={tips}"]):
        monkeypatch.setattr(sys, "argv", ["mafia.py", "--mock", *extra])
        with pytest.raises(SystemExit):
            mafia.main()
        assert "Zed" in capsys.readouterr().err
    assert not (tmp_path / "logs").exists()


def test_a_hanging_is_announced_before_the_executioner_s_win(game_factory):
    game, _ = game_factory(["Executioner", "Vanilla Villager", "Vanilla Villager", "Grunt"])
    game.player("Alice").status[Status.TARGET] = "Bob"
    game.kill("Bob", "executed by hanging", guilty_voters=["Carol"])
    texts = [e.text for e in game.events]
    death = next(i for i, t in enumerate(texts) if t.startswith("Bob died"))
    assert all(i > death for i, t in enumerate(texts) if "Alice" in t)


def test_the_puppeteer_never_sees_the_puppet_s_nomination(game_factory):
    from day import chat_turn

    def decide(name, task, schema):
        if name == "Bob" and "nominate" in schema["properties"]:
            return {"nominate": "Carol"}
        if name == "Erin" and "puppeting Bob" in task:
            return {"public_message": "word " * 300}  # over budget: the Puppeteer is asked to revise
        return None
    client = ScriptedClient(decide)
    game, players = game_factory(VILLAGE5[:4] + ["Puppeteer"], client)
    game.puppets = {"Bob": "Erin"}
    game.player("Bob").speaking_budget = 3.0
    chat_turn(game, players, game.player("Bob"), rnd=1, can_nominate=True)
    assert any(name == "Erin" and "WARNING" in task for name, task in client.asked)
    assert not any(name == "Erin" and "Carol" in task.split("WARNING")[-1] for name, task in client.asked)


def test_a_cleaned_death_still_shows_its_cause(game_factory):
    game, _ = game_factory(["Vanilla Villager", "Vigilante", "Vanilla Villager", "Mortician"])
    game.player("Alice").status[Status.CLEANED] = True
    game.kill("Alice", "Vigilante")
    reveal = next(e.text for e in game.events if e.text.startswith("Alice died"))
    assert "(killed by Vigilante)" in reveal and "Vanilla Villager" not in reveal  # rules R12


def test_problems_players_and_the_moderator_report_are_listed_for_review(tmp_path):
    import alerts
    log = tmp_path / "game_20261009_000000_1.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in [
        {"t": 1, "kind": "player_feedback", "player": "Erin", "feedback": "I can see Bob's nomination"},
        {"t": 2, "kind": "moderator_flag", "issue": "R8: can the Katana move without an attack?"},
        {"t": 3, "kind": "review", "issues": [{"kind": "harness bug", "severity": "high", "description": "leak"},
                                              {"kind": "other", "severity": "low", "description": "typo"}]},
        {"t": 4, "kind": "result"}]) + "\n", encoding="utf-8")
    [g] = alerts.unreviewed(tmp_path)
    assert g["kinds"] == {"player_feedback": 1, "moderator_flag": 1, "review_issue": 1}
    assert "Bob's nomination" in alerts.describe([g])
    alerts.ack(tmp_path, ["all"])
    assert alerts.unreviewed(tmp_path) == []


def test_death_reveal_says_who_or_what_killed():
    from state import death_cause
    assert death_cause("Katana") == "killed by Katana"
    assert death_cause("Jester's revenge") == "killed by Jester's revenge"
    assert death_cause("executed by hanging") == "executed by hanging"
    assert death_cause("killed by the Vigilante") == "killed by the Vigilante"
    assert death_cause(" ") == "killed"


def test_a_cut_notepad_tells_its_owner(game_factory):
    long = " ".join(["word"] * (NOTEPAD_WORDS + 5))
    game, players = game_factory(TOWN4_GRUNT, ScriptedClient(lambda name, task, schema: {"notepad": long}))
    players.ask(game.player("Alice"), "Note something.", {"type": "object", "properties": {}, "required": []}, {},
                step="day_turn")
    assert "notepad was over" in game.history_for("Alice") and "notepad was over" not in game.history_for("Bob")


def test_the_notepad_cap_grows_with_the_player_count(game_factory):
    from players import notepad_words
    game, _ = game_factory(TOWN4_GRUNT)
    assert notepad_words(game) == NOTEPAD_WORDS
    game, _ = game_factory(TOWN4_GRUNT + ["Vanilla Villager"] * 7)  # 12 players
    assert notepad_words(game) == 400


def test_feedback_prompts_show_dead_players_the_whole_game(game_factory):
    from feedback import POST_GAME_SCHEMA, post_game_context, run_debrief
    from llm import Model
    from moderator import Moderator
    from players import player_messages
    from tests.conftest import ScriptedClient
    game, players = game_factory(TOWN4_GRUNT)
    game.emit("Grunt (Yakuza chat): secret plan", ["Erin"])
    game.kill("Alice", "Katana")
    assert "secret plan" in post_game_context(game)
    # The reveal is a cached part of the system prompt, shared by the debrief and lessons questions.
    assert "secret plan" in str(player_messages(game, game.player("Alice"), "(rules)", "?",
                                                context=post_game_context(game))[0])
    sent: list[dict] = []

    def decide(name, task, schema):
        sent.append(schema)
    client = ScriptedClient(decide)
    game.log.path.parent.mkdir(exist_ok=True)
    players.client, players.shared = client, True
    run_debrief(game, players, Moderator(game, client, players, Model.HAIKU_5_5, "(rules)"))
    assert all(set(POST_GAME_SCHEMA["properties"]) <= set(s["properties"]) for s in sent[:5])


def test_a_written_out_null_is_no_feedback_and_keeps_the_notepad(game_factory):
    # Haiku wrote "null" as feedback 27 times in game_20261009_152339_529912 (text fields are plain strings).
    answers = iter([{"notepad": "plan"}, {"notepad": "null", "feedback": "null"}])
    game, players = game_factory(TOWN4_GRUNT, ScriptedClient(lambda name, task, schema: next(answers, None)))
    players.feedback_field = True
    schema = {"type": "object", "properties": {}, "required": []}
    for _ in range(2):
        players.ask(game.player("Alice"), "Note something.", schema, {}, step="day_turn")
    assert game.player("Alice").notepad == "plan"
    assert '"player_feedback"' not in game.log.path.read_text(encoding="utf-8")


def test_the_post_game_reveal_shows_each_private_message_once(game_factory):
    from feedback import full_log
    game, _ = game_factory(TOWN4_GRUNT)
    game.emit("Alice -> Bob (private): hi", ["Alice", "Bob"])
    game.emit("Alice sent Bob a private message.", ["Carol", "Dave", "Erin"], kind="notice")
    assert "hi" in full_log(game) and "sent Bob a private message" not in full_log(game)


def test_post_game_prompts_carry_the_history_once(game_factory):
    from feedback import post_game_context
    from players import player_messages
    game, _ = game_factory(TOWN4_GRUNT)
    game.emit("Alice (public): day one remark", cat="chat", speaker="Alice", message="day one remark")
    game.phase = "night"
    game.emit("night happened")
    text = str(player_messages(game, game.player("Alice"), "(rules)", "?", context=post_game_context(game)))
    assert text.count("day one remark") == 1


def test_a_bug_in_our_own_answer_handling_stops_the_game_instead_of_a_silent_fallback(tmp_path, monkeypatch):
    import players as players_module
    game, players = make_game(tmp_path, TOWN4_GRUNT)

    def broken(game):
        raise KeyError("bug")
    monkeypatch.setattr(players_module, "notepad_words", broken)  # reached only after a valid answer
    with pytest.raises(KeyError):
        players.ask(game.player("Alice"), "Vote.", players_module.VOTE_SCHEMA, {"vote": False}, step="trial_vote")
    game.log.close()
    assert not [r for r in records(game.log.path) if r["kind"] in ("player_error", "player_fallback")]
