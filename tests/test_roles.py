"""Role hooks and role-specific rules that code carries out (roles/*.py)."""

import pytest

from day import run_day
from llm import Model
from moderator import Moderator
from roles import Status
from tests.conftest import VILLAGE5, ScriptedClient


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


def test_puppeting_lapses_if_the_puppeteer_died(game_factory):
    client = ScriptedClient()
    game, players = game_factory(VILLAGE5[:3] + ["Grunt", "Puppeteer"], client)
    game.puppets_next = {"Bob": "Erin"}
    game.player("Erin").alive = False  # died overnight
    run_day(game, players)
    assert not any(name == "Erin" for name, _ in client.asked)
    assert not any("being puppeted" in e.text for e in game.events)
