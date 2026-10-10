"""Role hooks and role-specific rules that code carries out (roles/*.py)."""

import json

import pytest

import mafia
from day import run_day
from llm import MockClient, Model
from moderator import Moderator
from roles import ROLES, Status
from tests.conftest import VILLAGE5, ScriptedClient


def test_hanged_jester_wins_and_takes_revenge_on_a_guilty_voter(game_factory):
    game, _ = game_factory(["Jester", "Vanilla Villager", "Vanilla Villager", "Vanilla Villager", "Grunt"])
    game.kill("Alice", "executed by hanging", guilty_voters=["Bob", "Carol"])
    assert game.personal_winners == ["Alice"]
    game.phase = "night"
    game.resolve_revenge()
    dead = {n for n, _ in game.pending_deaths}
    assert len(dead) == 1 and dead <= {"Bob", "Carol"}


def test_jester_revenge_draws_from_voters_alive_when_the_night_began(game_factory):
    # Kevin, Oct 10: a Guilty voter killed by another attack that night is still in the draw.
    game, _ = game_factory(["Jester", "Vanilla Villager", "Vanilla Villager", "Vanilla Villager", "Grunt"])
    game.kill("Alice", "executed by hanging", guilty_voters=["Bob"])
    game.phase = "night"
    start = {p.name for p in game.alive()}
    game.kill("Bob", "Katana")
    game.resolve_revenge(start)
    assert [n for n, _ in game.pending_deaths] == ["Bob"]  # nobody else dies


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
    assert game.player("Alice").role == "Executioner"  # night deaths are simultaneous: it happens at dawn
    game.run_dawn_hooks()
    assert game.player("Alice").role == "Jester" and game.player("Alice").alive


def test_an_executioner_dying_the_same_night_as_their_target_dies_an_executioner(game_factory):
    game, _ = game_factory(["Executioner", "Vanilla Villager", "Vanilla Villager", "Grunt"])
    game.player("Alice").status[Status.TARGET] = "Bob"
    game.phase = "night"
    game.kill("Bob", "Katana")
    game.kill("Alice", "Vigilante")
    game.run_dawn_hooks()
    assert game.player("Alice").role == "Executioner"


def test_an_executioner_whose_target_leaves_becomes_a_jester(game_factory):
    game, _ = game_factory(["Executioner", "Executioner", "Vanilla Villager", "Vanilla Villager", "Grunt"])
    game.player("Alice").status[Status.TARGET] = "Bob"
    game.player("Bob").status[Status.TARGET] = "Carol"
    game.player("Bob").last_will = "Carol is lying."
    game.kill("Carol", "executed by hanging", guilty_voters=["Dave"])
    assert game.player("Bob").status[Status.LEFT] and game.player("Alice").role == "Jester"
    assert any("Carol is lying." in e.text for e in game.events)  # the leaving Executioner's will


def test_puppeteer_writes_the_puppets_messages(game_factory):
    def decide(name, task, schema):
        if name == "Erin" and "You are puppeting Bob" in task:
            assert "last_will" not in schema["properties"]  # the puppet's will stays the puppet's
            return {"public_message": "I am definitely Bob.", "claim": "Sheriff. N1: Carol Evil"}
        return None
    client = ScriptedClient(decide)
    game, players = game_factory(VILLAGE5[:4] + ["Puppeteer"], client)
    game.puppets_next = {"Bob": "Erin"}
    run_day(game, players)
    chat = {(e.fields["speaker"], e.fields["message"]) for e in game.events if e.cat == "chat"}
    assert chat == {("Bob", "I am definitely Bob.")}
    assert not any(name == "Bob" and "public_message" in task for name, task in client.asked)
    # The claim is public chat in effect, so the Puppeteer sets it too; it shows as Bob's.
    assert game.claim_record == {"Bob": [(1, "Sheriff. N1: Carol Evil")]}
    # Only the puppet (who is told about the puppeting) sees the message marked as the Puppeteer's.
    mark = "[written by your Puppeteer, not you]"
    assert any(mark in line for line in game.history_split("Bob")[1])
    assert not any(mark in line for name in ("Alice", "Erin") for line in game.history_split(name)[1])


def test_wiretap_reads_every_pm_but_a_dead_one_stops(game_factory):
    def decide(name, task, schema):
        if name == "Bob" and "public_message" in task:  # Bob is puppeted, so Erin writes as Bob
            return None
        if name == "Erin" and "You are puppeting Bob" in task:
            return {"private_messages": [{"to": "Alice", "text": "Puppet secret."}]}
        if name == "Carol" and "private_messages" in schema["properties"]:
            return {"private_messages": [{"to": "Alice", "text": "Carol secret."}]}
        return None
    game, players = game_factory(VILLAGE5[:3] + ["Wiretap", "Puppeteer", "Grunt"], ScriptedClient(decide))
    game.puppets_next = {"Bob": "Erin"}
    run_day(game, players)
    pms = [e for e in game.events if e.cat == "pm"]
    assert {e.fields["message"] for e in pms} == {"Puppet secret.", "Carol secret."}
    assert all(e.visible("Dave") and not e.visible("Frank") for e in pms)  # Frank is a Yakuza, not a Wiretap
    assert "Bob -> Alice (private): Puppet secret." in game.history_for("Dave")  # shown as the puppet's
    assert "Carol sent Alice a private message." not in game.history_for("Dave")  # no duplicate notice

    game.player("Dave").alive = False
    run_day(game, players)
    later = [e for e in game.events if e.cat == "pm"][len(pms):]
    assert later and not any(e.visible("Dave") for e in later)


def test_eavesdropper_reads_its_targets_pms_for_one_day(game_factory):
    def decide(name, task, schema):
        if "private_messages" not in schema.get("properties", {}):
            return None
        if name == "Bob":
            return {"private_messages": [{"to": "Carol", "text": f"Bob secret {game.day}."}]}
        if name == "Carol":
            return {"private_messages": [{"to": "Dave", "text": f"Carol secret {game.day}."}]}
        return None
    game, players = game_factory(["Eavesdropper", "Vanilla Villager", "Vanilla Villager", "Vanilla Villager",
                                  "Grunt"], ScriptedClient(decide))
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    with pytest.raises(ValueError, match="themselves"):
        mod.dispatch("apply_changes", {"changes": [{"op": "eavesdrop", "player": "Alice", "by": "Alice"}]})
    mod.dispatch("apply_changes", {"changes": [{"op": "eavesdrop", "player": "Bob", "by": "Alice"}]})
    run_day(game, players)
    heard = {e.fields["message"] for e in game.events if e.cat == "pm" and e.visible("Alice")}
    assert heard == {"Bob secret 1."}  # Bob's PM, not Carol's to Dave
    assert "Bob sent Carol a private message." not in game.history_for("Alice")

    game.day = 2  # no eavesdrop recorded for the next day, so nothing more is heard
    run_day(game, players)
    assert {e.fields["message"] for e in game.events if e.cat == "pm" and e.visible("Alice")} == heard


def test_archivist_sees_three_quarters_of_the_others_alive_at_night_start_once(game_factory):
    game, players = game_factory(["Archivist", "Roleplayer", "Vanilla Villager", "Vanilla Villager", "Grunt",
                                  "Jester", "Sheriff", "Medic", "Pharmacist"])
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    game.phase = "night"
    # The kill comes first: Bob died tonight but still counts.
    mod.dispatch("apply_changes", {"changes": [{"op": "kill", "player": "Bob", "cause": "Katana"},
                                               {"op": "archive", "by": "Alice"}]})
    with pytest.raises(ValueError, match="no archive token"):
        mod.dispatch("apply_changes", {"changes": [{"op": "archive", "by": "Alice"}]})
    result = next(e for e in game.events if e.cat == "result")
    assert result.visible_to == {"Alice"}
    assert "6 of the roles of the 8 other players" in result.text  # Bob died tonight but counts: N = 8
    shown = result.fields["message"].split(": ", 1)[1].rstrip(".").split(", ")
    pool = ["Roleplayer", "Vanilla Villager", "Vanilla Villager", "Grunt", "Jester", "Sheriff", "Medic", "Pharmacist"]
    assert len(shown) == 6 and all(shown.count(r) <= pool.count(r) for r in shown)
    assert result.phase == "night"  # a night result, not a dawn one
    game.announce_dawn()
    game.run_dawn_hooks()  # nothing more at dawn
    assert sum(e.cat == "result" for e in game.events) == 1


def test_roleplayers_never_get_a_role_code_delivers_results_for(game_factory):
    import random
    from roles import logic
    game, _ = game_factory(["Roleplayer", "Vanilla Villager", "Grunt"])
    for seed in range(40):
        game.rng = random.Random(seed)
        logic("Roleplayer").setup(game, game.player("Alice"))
        assert game.player("Alice").status[Status.FAKE_ROLE] not in ("Eavesdropper", "Archivist", "Surveyor")


def test_vulture_wins_alone_at_dawn_once_few_enough_are_left(game_factory):
    roles = ["Vulture", "Jester"] + ["Vanilla Villager"] * 7 + ["Grunt"]  # 10 players: threshold max(2, 2) = 2
    game, players = game_factory(roles, ScriptedClient())
    game.personal_winners.append("Bob")  # e.g. a Jester who already won
    for name in ["Carol", "Dave", "Erin", "Frank", "Grace", "Heidi", "Ivan"]:
        game.kill(name, "Katana")
    game.run_dawn_hooks()  # Alice, Bob, Judy: 3 alive
    assert game.check_winner() is None
    game.kill("Bob", "Katana")
    run_day(game, players)  # Alice and Judy: 2 alive at the start of the day
    assert game.check_winner() == ["Alice", "Bob"]
    assert any("is the Vulture" in e.text for e in game.events)


def test_a_dead_vulture_never_wins(game_factory):
    game, _ = game_factory(["Vulture", "Vanilla Villager", "Vanilla Villager", "Grunt"])
    game.kill("Alice", "Katana")
    game.kill("Bob", "Katana")
    game.run_dawn_hooks()
    assert game.sole_winner is None


def test_unique_roles_appear_at_most_once(tmp_path):
    import random
    from gamelog import GameLog
    from state import setup_game
    with pytest.raises(ValueError, match="Vulture"):
        setup_game(["Vulture", "Vulture", "Grunt", "Vanilla Villager"], [Model.HAIKU_5_5], random.Random(1),
                   GameLog(tmp_path / "t.jsonl"))


def test_ballot_stuffer_doubles_trial_votes_the_next_day_only(game_factory):
    from day import run_trial
    guilty = {"Bob", "Erin", "Frank"}

    def decide(name, task, schema):
        if "Vote true for Guilty" in task:
            return {"vote": name in guilty}
        return None
    game, players = game_factory(["Vanilla Villager"] * 4 + ["Grunt", "Ballot Stuffer"], ScriptedClient(decide))
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    alice = game.player("Alice")
    assert run_trial(game, players, alice, "Bob", 1) == "innocent"  # 3 of 6: no majority without stuffing
    mod.dispatch("apply_changes", {"changes": [{"op": "stuff_ballot", "by": "Frank"}]})
    assert game.player("Frank").tokens["ballot"] == 1
    game.run_dawn_hooks()
    assert run_trial(game, players, alice, "Alice", 1) == "executed"  # Frank counts twice: 4 of 7
    assert any("(4 Guilty of 7 votes; 4 needed; these totals don't match" in e.text for e in game.events)
    game.run_dawn_hooks()  # the next day, without a new token, Frank's Innocent is back to one vote
    guilty.clear()
    guilty.update({"Bob", "Carol", "Erin"})
    assert run_trial(game, players, game.player("Bob"), "Dave", 1) == "executed"  # 3 of 5, not 3 of 6


def test_surveyor_group_skips_itself_and_shrinks_in_small_games(game_factory):
    from roles.surveyor import survey_group
    game, players = game_factory(["Surveyor", "Vanilla Villager", "Medic", "Grunt", "Pharmacist", "Jester"])
    game.phase = "night"
    assert survey_group(game, "Alice", "Bob") == ["Frank", "Bob", "Carol"]  # skips Alice, wraps around
    game.kill("Carol", "Katana")  # died tonight: still in the group (alive at the start of the night)
    assert survey_group(game, "Alice", "Bob") == ["Frank", "Bob", "Carol"]
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    mod.dispatch("apply_changes", {"changes": [{"op": "survey", "player": "Bob", "by": "Alice"}]})
    result = next(e for e in game.events if e.cat == "result")
    assert result.visible_to == {"Alice"} and "You surveyed Frank, Bob and Carol." in result.text
    assert any(role in result.text for role in ("Jester", "Vanilla Villager", "Medic"))
    assert game.player("Alice").tokens["survey"] == 1
    for name in ["Carol", "Dave", "Erin"]:
        game.player(name).alive, game.player(name).death = False, None  # died on earlier days
    assert survey_group(game, "Alice", "Bob") == ["Frank", "Bob"]  # two others alive
    game.player("Frank").alive, game.player("Frank").death = False, None
    assert survey_group(game, "Alice", "Bob") == ["Bob"]


def test_diviner_draws_from_the_target_and_neighbors_mostly_the_target(game_factory):
    game, players = game_factory(["Diviner", "Vanilla Villager", "Medic", "Grunt", "Pharmacist", "Jester"])
    game.phase = "night"
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    with pytest.raises(ValueError, match="Strong Defense"):  # a Yakuza target: no result
        mod.dispatch("apply_changes", {"changes": [{"op": "divine", "player": "Dave", "by": "Alice"}]})
    drawn = []
    for _ in range(200):
        mod.dispatch("apply_changes", {"changes": [{"op": "divine", "player": "Bob", "by": "Alice"}]})
        result = [e for e in game.events if e.cat == "result"][-1]
        assert result.visible_to == {"Alice"} and "the group was Frank, Bob and Carol" in result.text
        drawn.append(next(r for r in ("Jester", "Vanilla Villager", "Medic") if f"role drawn is {r}" in result.text))
    assert 100 < drawn.count("Vanilla Villager") < 140 and drawn.count("Jester") > 20 and drawn.count("Medic") > 20
    for name in ["Carol", "Dave", "Erin"]:
        game.player(name).alive, game.player(name).death = False, None  # died on earlier days
    mod.dispatch("apply_changes", {"changes": [{"op": "divine", "player": "Bob", "by": "Alice"}]})
    assert "the group was Frank and Bob" in [e for e in game.events if e.cat == "result"][-1].text


def test_philanthropist_hands_a_token_of_the_recipients_kind(game_factory):
    game, players = game_factory(["Philanthropist", "Medic", "Vanilla Villager", "Grunt"])
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    game.phase = "night"
    mod.dispatch("apply_changes", {"changes": [{"op": "give_token", "player": "Bob", "by": "Alice"},
                                               {"op": "give_token", "player": "Carol", "by": "Alice"}]})
    assert game.player("Bob").tokens == {"medic": 3} and game.player("Carol").tokens == {}
    assert game.player("Alice").tokens["philanthropy"] == 0
    results = [e for e in game.events if e.cat == "result"]
    assert [sorted(e.visible_to) for e in results] == [["Bob"], ["Carol"]]  # the Philanthropist learns nothing
    assert "threw it away" in results[1].text
    with pytest.raises(ValueError, match="no philanthropy token"):
        mod.dispatch("apply_changes", {"changes": [{"op": "give_token", "player": "Bob", "by": "Alice"}]})


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
    assert f"Your role is {rp.status[Status.FAKE_ROLE]} (Good)." in briefing and "Roleplayer" not in briefing


def test_moderator_night_notes_cover_roles_in_the_game(game_factory):
    from night import role_notes
    game, _ = game_factory(["Trapper", "Seer", "Vanilla Villager", "Grunt"])
    game.kill("Alice", "Katana")  # a dead Trapper's traps still work
    notes = role_notes(game)
    assert "Trapper" in notes and "Seer" in notes and "Arsonist" not in notes


def test_moderator_is_told_ex_con_reads_evil_to_seers_too(game_factory):
    """rules Ex-Con: Evil to every alignment check, not just the Sheriff."""
    from night import role_notes
    game, _ = game_factory(["Ex-Con", "Seer", "Vanilla Villager", "Grunt"])
    notes = role_notes(game)
    assert "Ex-Con" in notes and "Seer" in notes.split("Ex-Con", 1)[1]

def test_role_ops_are_offered_only_for_roles_in_the_game(game_factory):
    game, players = game_factory(["Clerk", "Vanilla Villager", "Vanilla Villager"])
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    mod.dispatch("apply_changes", {"changes": [{"op": "rig_vote", "by": "Alice"}]})
    assert game.rigged_day == game.day + 1 and game.player("Alice").tokens["clerk"] == 0
    with pytest.raises(ValueError, match="no clerk token"):
        mod.dispatch("apply_changes", {"changes": [{"op": "rig_vote", "by": "Alice"}]})
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


# --- Every role ---------------------------------------------------------------------------------

@pytest.mark.parametrize("role", list(ROLES))
def test_every_role_survives_a_mock_game(role, tmp_path, monkeypatch):
    """A smoke test new roles get for free: setup, briefing, night note and a whole mock game
    (with night checks) run with the role in play, and the game ends with a result."""
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    roles = [role, "Vanilla Villager", "Vanilla Villager", "Sheriff", "Grunt", "Pharmacist"]
    path = mafia.play_game(MockClient(7),
        mafia.GameConfig([Model.HAIKU_5_5], Model.HAIKU_5_5, roles, seed=7, check_nights=True))
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert records[-1]["kind"] == "result"
    assert not [r for r in records if r["kind"] == "moderator_tool" and "error" in (r["result"] or {})]


# --- Mortician, Fabricator, Katana --------------------------------------------------------------

def test_mortician_clean_hides_role_and_will_but_not_the_cause(game_factory):
    game, players = game_factory(["Vanilla Villager", "Vanilla Villager", "Mortician", "Grunt"])
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    game.player("Alice").last_will = "I am the Sheriff."
    game.phase = "night"
    mod.dispatch("apply_changes", {"changes": [
        {"op": "kill", "player": "Alice", "cause": "Katana"},
        {"op": "set_status", "player": "Alice", "key": Status.CLEANED, "value": True}]})
    game.announce_dawn()
    reveal = next(e.text for e in game.events if e.cat == "death")
    assert "cleaned by a Mortician" in reveal and "Vanilla Villager" not in reveal and "Sheriff" not in reveal
    assert "(killed by Katana)" in reveal and "Vanilla" not in game.death_record[0]  # the cause still shows (rules R12)


def test_forged_will_shows_at_dawn_even_if_set_after_the_kill(game_factory):
    game, players = game_factory(["Vanilla Villager", "Vanilla Villager", "Fabricator", "Grunt"])
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    game.player("Alice").last_will = "real will"
    game.phase = "night"
    mod.dispatch("apply_changes", {"changes": [
        {"op": "kill", "player": "Alice", "cause": "Katana"},
        {"op": "set_last_will", "player": "Alice", "text": "Bob is Yakuza."}]})
    game.announce_dawn()
    reveal = next(e.text for e in game.events if e.cat == "death")
    assert "Bob is Yakuza." in reveal and "real will" not in reveal


def test_katana_needs_a_majority_and_gets_one_revote(game_factory):
    def decide(name, task, schema):
        if "katana_vote_target" not in schema["properties"]:
            return None
        if task.startswith("Revote"):  # everyone agrees on the revote
            return {"katana_vote_holder": "Carol", "katana_vote_target": "Alice"}
        own = {"Carol": "Alice", "Dave": "Bob"}  # first vote: split, so no majority
        return {"katana_vote_holder": name, "katana_vote_target": own[name], "act": False}
    game, players = game_factory(["Vanilla Villager", "Vanilla Villager", "Grunt", "Grunt"], ScriptedClient(decide))
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    from night import run_night, tally_katana
    assert tally_katana(game, {"Carol": {"katana_vote_holder": "Carol", "katana_vote_target": "Alice"},
                               "Dave": {"katana_vote_holder": "Dave", "katana_vote_target": "Bob"}})["attack"] is None
    game.katana_holder = "Dave"
    run_night(game, players, mod)
    split = [e for e in game.events if "no majority" in e.text]
    assert split and split[0].visible_to == {"Carol", "Dave"}
    katana = [json.loads(line) for line in game.log.path.read_text(encoding="utf-8").splitlines()
              if '"kind": "katana"' in line]
    assert katana[-1]["result"]["attack"] == "Alice" and game.katana_holder == "Carol"


def test_katana_holder_and_target_majorities_are_separate(game_factory):
    from night import tally_katana
    game, _ = game_factory(["Vanilla Villager", "Vanilla Villager", "Grunt", "Grunt", "Grunt"])
    game.katana_holder = "Carol"
    votes: dict[str, dict[str, str | None]] = {y: {"katana_vote_holder": y, "katana_vote_target": "Alice"}
                                               for y in ("Carol", "Dave", "Erin")}
    assert tally_katana(game, votes) == {"attack": "Alice", "holder": "Carol", "attack_level": "Standard"}  # rules R8
    votes = {y: {"katana_vote_holder": "Dave", "katana_vote_target": t} for y, t in
             (("Carol", "Alice"), ("Dave", "Bob"), ("Erin", None))}
    assert tally_katana(game, votes)["attack"] is None and game.katana_holder == "Dave"


def test_yakuza_are_told_that_two_of_them_must_both_agree_on_the_katana(game_factory):
    client = ScriptedClient()
    game, players = game_factory(["Grunt", "Pharmacist", "Vanilla Villager", "Vanilla Villager"], client)
    from moderator import Moderator
    from llm import Model
    from night import run_night
    run_night(game, players, Moderator(game, client, players, Model.HAIKU_5_5, "(rules)"))
    yakuza_tasks = [task for name, task in client.asked if name in ("Alice", "Bob")]
    assert yakuza_tasks and all("both must agree" in task for task in yakuza_tasks if "Katana" in task)


def test_medic_briefing_spells_out_token_costs(game_factory):
    from players import role_briefing
    game, _ = game_factory(["Medic", "Grunt"])
    assert "yourself with Standard Defense costs 1 token" in role_briefing(game, game.player("Alice"))


def test_ask_player_answer_is_kept_in_the_players_history_and_hides_their_notepad(game_factory):
    def decide(name, task, schema):
        return {"notepad": "secret plan", "answer": "ignite"} if name == "Alice" and "answer" in schema["properties"] \
            else None
    game, players = game_factory(["Arsonist", "Vanilla Villager", "Grunt"], ScriptedClient(decide))
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    assert mod.dispatch("ask_player", {"player": "Alice", "question": "Ignite or douse?"}) == {"answer": "ignite"}
    assert "You answered: ignite" in game.history_for("Alice") and "ignite" not in game.history_for("Bob")


def test_ex_con_visit_is_drawn_by_code_and_hidden_from_the_ex_con(game_factory):
    """rules Ex-Con: a random visit each night, and the Ex-Con isn't told whom."""
    from night import run_night
    from players import night_history
    game, players = game_factory(["Ex-Con", "Vanilla Villager", "Vanilla Villager", "Grunt"])
    run_night(game, players, Moderator(game, players.client, players, Model.HAIKU_5_5, "(rules)"))
    action = game.night_actions[1]["Alice"]
    assert action["automatic"] and action["target"] in ("Bob", "Carol", "Dave")
    assert "Alice" not in night_history(game, game.player("Alice"))


def test_trapper_is_told_whether_their_trap_still_stands(game_factory):
    from players import role_briefing
    from roles import Status
    game, _ = game_factory(["Trapper", "Vanilla Villager", "Grunt"])
    trapper = game.player("Alice")
    assert "no trap set" in role_briefing(game, trapper)
    game.player("Bob").status[Status.TRAPPED_BY] = "Alice"
    assert "Your trap is on Bob" in role_briefing(game, trapper)
    assert "trap" not in role_briefing(game, game.player("Bob"))


def test_a_token_op_counts_its_user_as_alive_all_night_whatever_the_op_order(game_factory):
    # rules R10 (simultaneous) and R21: a Clerk killed earlier in tonight's resolution still rigs tomorrow
    game, players = game_factory(["Clerk", "Grunt", "Vanilla Villager", "Vanilla Villager", "Vanilla Villager"])
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    game.phase = "night"
    mod.dispatch("apply_changes", {"changes": [{"op": "kill", "player": "Alice", "cause": "Vigilante"}]})
    mod.dispatch("apply_changes", {"changes": [{"op": "rig_vote", "by": "Alice"}]})
    assert game.rigged_day == game.day + 1 and game.player("Alice").tokens["clerk"] == 0
    game.day += 1  # a Clerk who died on an earlier night can't
    game.player("Alice").tokens["clerk"] = 1
    with pytest.raises(ValueError, match="alive when the night began"):
        mod.dispatch("apply_changes", {"changes": [{"op": "rig_vote", "by": "Alice"}]})
