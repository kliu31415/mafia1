"""Scenario tests for the rules that code (not the LLM moderator) carries out."""

from collections.abc import Collection

import pytest

import mafia
from day import run_day, run_nomination, run_trial
from moderator import Moderator
from llm import Model
from roles import Status
from tests.conftest import ScriptedClient

VILLAGE5 = ["Vanilla Villager"] * 5
TOWN4_GRUNT = ["Vanilla Villager"] * 4 + ["Grunt"]  # run_day needs two factions alive, or the game is over


def votes(guilty_for: Collection[str] = (), nominate: dict[str, str] | None = None):
    """A decide() where everyone votes Yes/Guilty on the given nominees, and the given players
    nominate once each."""
    nominated = set()

    def decide(name, task, schema):
        if "vote" in schema["properties"]:
            return {"vote": any(f"nominated {n}." in task or f"{n} is on trial" in task for n in guilty_for)}
        if nominate and name in nominate and name not in nominated and "nominate" in schema["properties"]:
            nominated.add(name)
            return {"nominate": nominate[name]}
        return None
    return decide


# --- Jester and Executioner ---------------------------------------------------------------------

def test_hanged_jester_wins_and_takes_revenge_on_a_guilty_voter(game_factory):
    game, _ = game_factory(["Jester", "Vanilla Villager", "Vanilla Villager", "Vanilla Villager", "Grunt"])
    game.kill("Alice", "executed by hanging", guilty_voters=["Bob", "Carol"])
    assert game.personal_winners == ["Alice"]
    game.phase = "night"
    game.resolve_revenge()
    dead = {n for n, _ in game.pending_deaths}
    assert len(dead) == 1 and dead <= {"Bob", "Carol"}


def test_jester_killed_at_night_does_not_win(game_factory):
    game, _ = game_factory(["Jester", "Vanilla Villager", "Vanilla Villager", "Grunt"])
    game.phase = "night"
    game.kill("Alice", "Katana")
    assert game.personal_winners == [] and game.pending_revenge == []


def test_executioner_wins_and_leaves_when_target_is_hanged(game_factory):
    game, _ = game_factory(["Executioner", "Vanilla Villager", "Vanilla Villager", "Grunt"])
    game.player("Alice").status[Status.TARGET] = "Bob"
    game.kill("Bob", "executed by hanging", guilty_voters=["Carol"])
    alice = game.player("Alice")
    assert "Alice" in game.personal_winners and not alice.alive and alice.status[Status.LEFT]
    assert game.death_count() == 1  # leaving isn't a death


def test_executioner_becomes_jester_when_target_dies_otherwise(game_factory):
    game, _ = game_factory(["Executioner", "Vanilla Villager", "Vanilla Villager", "Grunt"])
    game.player("Alice").status[Status.TARGET] = "Bob"
    game.phase = "night"
    game.kill("Bob", "Katana")
    assert game.player("Alice").role == "Jester" and game.player("Alice").alive


# --- Nominations and trials ---------------------------------------------------------------------

def test_nomination_needs_a_strict_majority_of_living_players(game_factory):
    # Alice nominates Bob; only Carol also votes Yes: 2 of 4 is not more than half.
    def decide(name, task, schema):
        return {"vote": name == "Carol"} if "vote" in schema["properties"] else None
    game, players = game_factory(VILLAGE5[:4], ScriptedClient(decide))
    assert run_nomination(game, players, game.player("Alice"), "Bob", rnd=1) == "failed"
    assert game.player("Bob").alive


def test_guilty_majority_executes(game_factory):
    game, players = game_factory(VILLAGE5, ScriptedClient(votes(guilty_for={"Bob"})))
    assert run_trial(game, players, game.player("Alice"), "Bob", rnd=1) == "executed"
    assert not game.player("Bob").alive


def test_clerk_rig_executes_despite_innocent_verdict(game_factory):
    game, players = game_factory(VILLAGE5[:4] + ["Clerk"])
    assert run_trial(game, players, game.player("Alice"), "Bob", rnd=1) == "innocent"
    game.rigged_day = game.day
    assert run_trial(game, players, game.player("Alice"), "Carol", rnd=1) == "executed"
    assert not game.player("Carol").alive


def test_prosecuted_player_goes_straight_to_trial(game_factory):
    game, players = game_factory(TOWN4_GRUNT, ScriptedClient(votes(guilty_for={"Erin"})))
    game.prosecutions.append("Erin")
    run_day(game, players)
    assert not game.player("Erin").alive
    assert any("prosecuted" in v for v in game.vote_record)


def test_day_ends_after_an_execution(game_factory):
    client = ScriptedClient(votes(guilty_for={"Bob"}, nominate={"Alice": "Bob", "Carol": "Dave"}))
    game, players = game_factory(TOWN4_GRUNT, client)
    run_day(game, players)
    assert not game.player("Bob").alive and game.player("Dave").alive


# --- Puppeteer ----------------------------------------------------------------------------------

def test_puppeteer_writes_the_puppets_messages(game_factory):
    def decide(name, task, schema):
        if name == "Erin" and "You are puppeting Bob" in task:
            return {"public_message": "I am definitely Bob."}
        return None
    client = ScriptedClient(decide)
    game, players = game_factory(VILLAGE5[:4] + ["Puppeteer"], client)
    game.puppets_next = {"Bob": "Erin"}
    run_day(game, players)
    chat = {(e.fields["speaker"], e.fields["message"]) for e in game.events if e.cat == "chat"}
    assert chat == {("Bob", "I am definitely Bob.")}
    assert not any(name == "Bob" and "public_message" in task for name, task in client.asked)


# --- Katana, Cardinal, win checks -----------------------------------------------------------------

def test_katana_passes_when_its_holder_dies_by_day(game_factory):
    game, _ = game_factory(["Grunt", "Pharmacist", "Vanilla Villager", "Vanilla Villager"])
    assert game.katana_holder == "Alice"
    game.kill("Alice", "executed by hanging", guilty_voters=["Carol", "Dave"])
    assert game.katana_holder == "Bob"


def test_cardinal_curse_kills_a_good_player_next_dawn(game_factory):
    game, _ = game_factory(["Cardinal", "Vanilla Villager", "Vanilla Villager", "Grunt"])
    game.kill("Alice", "executed by hanging", guilty_voters=["Dave"])
    game.run_dawn_hooks()
    assert [p.name for p in game.alive()] in (["Bob", "Dave"], ["Carol", "Dave"])


@pytest.mark.parametrize("alive_roles, expected", [
    (["Vanilla Villager", "Vanilla Villager"], "Village"),
    (["Vanilla Villager", "Jester"], "Village"),  # Jesters don't block a win
    (["Grunt", "Grunt"], "Yakuza"),
    (["Vanilla Villager", "Grunt"], None),
    (["Vanilla Villager", "Serial Killer"], None),  # a Neutral killer does block
])
def test_win_check(game_factory, alive_roles, expected):
    game, _ = game_factory(alive_roles)
    winners = game.check_winner()
    if expected is None:
        assert winners is None
    else:
        assert winners and all(game.player(w).faction == expected for w in winners)


def test_nobody_wins_after_three_days_and_nights_without_deaths(tmp_path, monkeypatch):
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    roles = ["Vanilla Villager", "Vanilla Villager", "Vanilla Villager", "Grunt", "Grunt"]
    path = mafia.play_game(ScriptedClient(), [Model.HAIKU_5_5], Model.HAIKU_5_5, roles, seed=1)
    assert "Everyone loses" in path.with_suffix(".txt").read_text(encoding="utf-8")
    import json
    result = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    assert result["end_reason"] == "stall" and result["winning_faction"] is None


# --- Moderator ops ---------------------------------------------------------------------------

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


# --- Setup and briefings ----------------------------------------------------------------------

def test_setup_hooks_assign_executioner_target_and_roleplayer_fake_role(tmp_path):
    import random
    from gamelog import GameLog
    from players import role_briefing
    from roles import ROLES
    from state import setup_game
    game = setup_game(["Executioner", "Roleplayer", "Grunt", "Vanilla Villager"], [Model.HAIKU_5_5],
                      random.Random(3), GameLog(tmp_path / "t.jsonl"))
    exe = next(p for p in game.players if p.role == "Executioner")
    rp = next(p for p in game.players if p.role == "Roleplayer")
    assert exe.status[Status.TARGET] in {p.name for p in game.players} - {exe.name}
    assert ROLES[rp.status[Status.FAKE_ROLE]].category == "Investigative"
    assert f"Your target is {exe.status[Status.TARGET]}." in role_briefing(game, exe)
    briefing = role_briefing(game, rp)
    assert f"Your role is {rp.status[Status.FAKE_ROLE]}." in briefing and "Roleplayer" not in briefing


def test_moderator_night_notes_cover_roles_in_the_game(game_factory):
    from night import role_notes
    game, _ = game_factory(["Trapper", "Seer", "Vanilla Villager", "Grunt"])
    game.kill("Alice", "Katana")  # a dead Trapper's traps still work
    notes = role_notes(game)
    assert "Trapper" in notes and "Seer" in notes and "Arsonist" not in notes


def test_role_ops_are_offered_only_for_roles_in_the_game(game_factory):
    game, players = game_factory(["Clerk", "Vanilla Villager", "Vanilla Villager"])
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    mod.dispatch("apply_changes", {"changes": [{"op": "rig_vote"}]})
    assert game.rigged_day == game.day + 1
    with pytest.raises(ValueError, match="op must be one of"):
        mod.dispatch("apply_changes", {"changes": [{"op": "prosecute", "player": "Bob"}]})
    description = next(t for t in mod.tools if t["function"]["name"] == "apply_changes")["function"]["description"]
    assert "rig_vote" in description and "prosecute" not in description


def test_every_role_file_is_registered():
    """A roles/<role>.py that isn't imported in roles/__init__.py would silently do nothing."""
    from pathlib import Path
    import roles
    from roles.base import LOGIC
    files = {p.stem for p in Path(roles.__file__).parent.glob("*.py")} - {"__init__", "base"}
    registered = {type(r).__module__.removeprefix("roles.") for r in LOGIC.values()}
    assert files == registered


def test_day_limit_ends_the_game_with_no_winner(tmp_path, monkeypatch):
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    monkeypatch.setattr(mafia, "STALL_LIMIT", 100)  # so the stall rule doesn't end it first
    roles = ["Vanilla Villager", "Vanilla Villager", "Vanilla Villager", "Grunt", "Grunt"]
    path = mafia.play_game(ScriptedClient(), [Model.HAIKU_5_5], Model.HAIKU_5_5, roles, seed=1, max_days=2)
    text = path.with_suffix(".txt").read_text(encoding="utf-8")
    assert "limit of 2 days" in text and "Winners: nobody" in text


def test_puppeting_lapses_if_the_puppeteer_died(game_factory):
    client = ScriptedClient()
    game, players = game_factory(VILLAGE5[:3] + ["Grunt", "Puppeteer"], client)
    game.puppets_next = {"Bob": "Erin"}
    game.player("Erin").alive = False  # died overnight
    run_day(game, players)
    assert not any(name == "Erin" for name, _ in client.asked)
    assert not any("being puppeted" in e.text for e in game.events)


# --- Night checks -------------------------------------------------------------------------------

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


def test_logs_describe_the_game_and_its_votes(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    client = ScriptedClient(votes(guilty_for={"Bob"}, nominate={"Alice": "Bob"}))
    roles = ["Vanilla Villager", "Vanilla Villager", "Vanilla Villager", "Grunt", "Grunt"]
    path = mafia.play_game(client, [Model.HAIKU_5_5], Model.HAIKU_5_5, roles, seed=1)
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


def test_each_model_uses_its_own_effort(tmp_path, monkeypatch):
    from llm import ModelSpec, parse_model_spec
    assert parse_model_spec("opus-5.5:high") == ModelSpec(Model.OPUS_5_5, "high")
    assert parse_model_spec("haiku-5.5") == ModelSpec(Model.HAIKU_5_5, None)
    with pytest.raises(ValueError, match="effort"):
        parse_model_spec("haiku-5.5:extreme")
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    client = ScriptedClient()
    roles = ["Vanilla Villager", "Vanilla Villager", "Vanilla Villager", "Grunt", "Grunt"]
    mafia.play_game(client, [ModelSpec(Model.HAIKU_5_5, "low")], ModelSpec(Model.OPUS_5_5, "high"), roles,
                    seed=1, check_nights=True)
    assert {e for who, e in client.efforts if who not in ("moderator", "other")} == {"low"}
    assert {e for who, e in client.efforts if who in ("moderator", "other")} == {"high"}  # incl. night checks
