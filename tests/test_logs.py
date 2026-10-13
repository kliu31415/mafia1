"""Game logs: the records analysis relies on."""

import json

import mafia
from llm import Model
from tests.conftest import ScriptedClient, votes


def test_logs_describe_the_game_and_its_votes(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    client = ScriptedClient(votes(guilty_for={"Bob"}, nominate={"Alice": "Bob"}))
    roles = ["Vanilla Villager", "Vanilla Villager", "Vanilla Villager", "Grunt", "Grunt"]
    path = mafia.play_game(client, mafia.GameConfig([Model.HAIKU_5_5], Model.HAIKU_5_5, roles, seed=1))
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    setup = records[0]
    assert setup["kind"] == "setup" and len(setup["rules_sha256"]) == 16
    assert setup["settings"]["roles"] == roles and "git_commit" in setup
    votes_ = [r for r in records if r["kind"] == "vote"]
    assert {v["stage"] for v in votes_} == {"nomination", "trial"}
    assert all(set(v["votes"]) <= {p["name"] for p in setup["players"]} for v in votes_)
    assert setup["game_id"] == path.stem
    result = records[-1]
    assert result["kind"] == "result" and result["end_reason"] in ("win", "stall", "day_limit", "no_faction_left")
    by_name = {p["name"]: p for p in result["players"]}
    assert set(by_name) == {p["name"] for p in setup["players"]}
    assert all(p["won"] == (p["name"] in result["winners"]) for p in by_name.values())
    assert all((p["death"] is None) == (p["alive"] or p["left"]) for p in by_name.values())


def test_player_calls_log_the_notepad_before_and_after(game_factory):
    import json
    from log_viewer import render_html
    writes = iter(["first note", None])
    game, players = game_factory(["Vanilla Villager", "Grunt"],
                                 ScriptedClient(lambda name, task, schema: {"notepad": next(writes)}))
    alice = game.players[0]
    for _ in range(2):
        players.ask(alice, "Say something.", {"type": "object", "properties": {}, "required": []}, {}, step="day_turn")
    game.log.close()
    calls = [json.loads(line) for line in game.log.path.read_text(encoding="utf-8").splitlines()]
    calls = [r for r in calls if r["kind"] == "player_call"]
    assert [(r["notepad_before"], r["notepad_after"]) for r in calls] == [("", "first note"),
                                                                         ("first note", "first note")]
    assert alice.notepad == "first note"
    page = render_html(game.log.path).read_text(encoding="utf-8")
    assert "Notepad before" in page and "(unchanged)" in page


def test_result_breaks_cost_down_by_player(tmp_path, monkeypatch):
    import dataclasses
    import json
    from log_viewer import render_html

    class PricedClient(ScriptedClient):
        def chat(self, model, messages, **kw):
            usage = {"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.01,
                     "prompt_tokens_details": {"cached_tokens": 40},
                     "completion_tokens_details": {"reasoning_tokens": 5}}
            return dataclasses.replace(super().chat(model, messages, **kw), cost=0.01, usage=usage)

    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    client = PricedClient(votes(guilty_for={"Bob"}, nominate={"Alice": "Bob"}))
    roles = ["Vanilla Villager", "Vanilla Villager", "Vanilla Villager", "Grunt", "Grunt"]
    path = mafia.play_game(client, mafia.GameConfig([Model.HAIKU_5_5], Model.SONNET_5_5, roles, seed=1))
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    usage = {u["who"]: u for u in records[-1]["usage"]}
    for p in records[0]["players"]:
        calls = sum(r["kind"] == "player_call" and r["player"] == p["name"] for r in records)
        assert usage[p["name"]]["calls"] == calls > 0 and usage[p["name"]]["models"] == [p["model"]]
        assert usage[p["name"]]["prompt_tokens"] == 100 * calls and usage[p["name"]]["cached_tokens"] == 40 * calls
    assert usage["Moderator"]["models"] == [Model.SONNET_5_5.value] and usage["Moderator"]["calls"] > 0
    assert round(sum(u["cost"] for u in usage.values()), 6) == round(sum(r.get("cost", 0) for r in records[:-1]), 6)
    page = render_html(path).read_text(encoding="utf-8")
    assert "Cost by player" in page and "Reasoning tokens" in page


def test_every_role_has_an_icon_in_the_html_log(game_factory):
    from log_viewer import ICONS, icon_slug, render_html
    from roles import ROLES
    assert all(icon_slug(role) != "generic" for role in ROLES), "draw an icon in roles/icons/ for each new role"
    assert icon_slug("Some Removed Role") == "generic" and (ICONS / "generic.svg").exists()
    assert all(info.summary for info in ROLES.values()), \
        "give each new role a one-line summary for the icon's hover text"
    game, _ = game_factory(["Medic", "Grunt"], ScriptedClient())
    game.log.close()
    page = render_html(game.log.path).read_text(encoding="utf-8")
    assert "class='n Village ic i-medic' title='Medic (Village): Night: protect" in page
    assert ".i-medic { --icon:url(" in page


def test_role_summaries_match_the_rules():
    """A role's rules paragraph changed since its summary was checked: update the summary if needed, then record it."""
    from role_summaries import stale_roles
    stale = stale_roles()
    assert not stale, (f"rules_1.txt changed for {', '.join(stale)}: check their `summary` in roles/__init__.py, then "
                       f"run: uv run role_summaries.py " + " ".join(f'"{r}"' for r in stale))


def test_every_call_record_says_what_step_it_was_and_how_long_it_took(tmp_path, monkeypatch):
    import json
    from llm import MockClient
    from players import STEPS
    from roles import DEFAULT_SETUP
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    path = mafia.play_game(MockClient(2),
        mafia.GameConfig([Model.HAIKU_5_5], Model.HAIKU_5_5, DEFAULT_SETUP, seed=2, debrief=True,
                         lessons=True))
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    calls = [r for r in records if r["kind"] == "player_call"]
    assert all(r["step"] in STEPS and r["day"] >= 1 and r["phase"] in ("day", "night") and r["latency_s"] >= 0
               for r in calls)
    steps = {r["step"] for r in calls}
    assert {"will", "day_turn", "night_action", "debrief", "lessons"} <= steps
    assert all("round" in r for r in calls if r["step"] in ("day_turn", "yakuza_chat"))
    assert all("latency_s" in r and "day" in r for r in records if r["kind"] == "moderator_call")


def test_logs_never_hold_secrets_or_email(tmp_path, monkeypatch):
    """Logs get shared: an API key (by its env var or its shape), an email address or the home folder's path
    never reaches the JSONL, .txt or .html, even when an error message or a model's answer contains one."""
    import log_viewer
    import records
    from gamelog import GameLog
    from pathlib import Path
    key = "sk-or-v1-" + "0123456789abcdef" * 4
    monkeypatch.setenv("SOME_SERVICE_TOKEN", "tok_abcdefghijklmnopqrstuvwxyz")
    source = Path.home() / "mafia1" / "llm.py"  # conftest's fake_home; with this system's slashes, and forward ones
    records.secret_values.cache_clear()
    try:
        path = tmp_path / "game.jsonl"
        log = GameLog(path)
        log.write("setup", players=[])
        log.error("api_retry", f"HTTP 401 for Bearer {key}: tok_abcdefghijklmnopqrstuvwxyz",
                  traceback=f'File "{source}", line 1, from {source.as_posix()}')
        log.write("chat", who="Alice", text="My owner is someone@example.com, ask them", cat="chat")
        log.close()
        old = tmp_path / "old.jsonl"  # a log written before redaction renders clean too
        old.write_text(json.dumps({"t": 0, "kind": "api_retry", "alert": True, "error": key}) + "\n")
        texts = [p.read_text(encoding="utf-8") for p in (path, path.with_suffix(".txt"), path.with_suffix(".html"),
                                                         log_viewer.render_html(old))]
    finally:
        records.secret_values.cache_clear()
    for text in texts:
        assert key not in text and "tok_abc" not in text and "someone@" not in text and "someuser" not in text
    assert "[redacted secret]" in texts[0] and "[redacted email]" in texts[0] and "from ~/mafia1/llm.py" in texts[0]
