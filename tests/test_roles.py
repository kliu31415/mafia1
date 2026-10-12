"""Role hooks and role-specific rules that code carries out (roles/*.py)."""

import json
import re

import pytest

import mafia
from day import run_day
from llm import MockClient, Model
from moderator import Moderator
from roles import ROLES, Status, logic
from tests.conftest import VILLAGE5, ScriptedClient, apply_ops, told, votes


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
    # Nobody else dies, and the revenge is revealed as a second fatal cause (R12; game_20261010_080056_104).
    assert game.pending_deaths == [("Bob", "Katana and Jester's revenge")]
    assert game.player("Bob").death["killers"] == ["Alice"]


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


def test_an_eavesdropper_moved_by_a_swap_listens_to_the_other_player_and_is_told(game_factory):
    # rules R23 (Kevin, Oct 11 2026): the listening follows the player it landed on, and the user is told why
    game, players = game_factory(["Eavesdropper", "Vanilla Villager", "Vanilla Villager", "Grunt", "Smuggler"])
    game.phase = "night"
    game.role_state["swaps"] = {game.day: [["Erin", "Bob", "Carol"]]}
    apply_ops(game, players, {"op": "eavesdrop", "player": "Carol", "by": "Alice"})  # Alice chose Bob
    game.phase = "day"
    game.day += 1
    game.run_dawn_hooks()
    assert any("A swap moved your eavesdropping from Bob to Carol" in t for t in told(game, "Alice"))
    assert "You are eavesdropping on Carol today" in told(game, "Alice")[-1]
    assert logic("Eavesdropper").hears_pm(game, game.player("Alice"), "Carol", "Dave")


def test_archivist_sees_one_role_per_other_player_three_quarters_real_once(game_factory):
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
    # Bob died tonight but counts: N = 8, floor(0.5 * 8) = 4 real
    assert "shows 8 roles" in result.text and "4 of them are the real" in result.text
    assert "other 4 are fakes" in result.text
    shown = result.fields["message"].rsplit(": ", 1)[1].rstrip(".").split(", ")
    assert len(shown) == 8 and all(r in ROLES for r in shown)
    assert result.phase == "night"  # a night result, not a dawn one
    game.announce_dawn()
    game.run_dawn_hooks()  # nothing more at dawn
    assert sum(e.cat == "result" for e in game.events) == 1


def test_archivist_fakes_are_any_role_but_never_a_second_unique_one(game_factory):
    import random
    from collections import Counter
    from roles.archivist import archive_roles
    game, _ = game_factory(["Archivist", "Vulture", "Vanilla Villager", "Vanilla Villager", "Grunt", "Jester",
                            "Sheriff", "Medic", "Pharmacist"])
    pool = Counter(["Vulture", "Vanilla Villager", "Vanilla Villager", "Grunt", "Jester", "Sheriff", "Medic",
                    "Pharmacist"])
    game.phase = "night"
    unique = {r for r, info in ROLES.items() if info.unique}
    assert unique
    fakes_seen: set[str] = set()
    for seed in range(300):
        game.rng = random.Random(seed)
        n, real, shown = archive_roles(game, game.player("Alice"))
        assert (n, real, len(shown)) == (8, 4, 8)
        counts = Counter(shown)
        assert all(counts[r] <= 1 for r in unique)
        # at least the 4 real roles come from the other players' roles
        assert sum(min(counts[r], pool[r]) for r in counts) >= 4
        fakes_seen |= set(counts - pool)
    assert fakes_seen - set(pool)  # fakes include roles not in the game
    assert fakes_seen & unique  # a unique role not drawn as real can show up as a fake


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


def test_the_rules_list_exactly_the_unique_roles():
    # The rules name the unique roles in one place (Kevin, Oct 10), so role paragraphs don't repeat it.
    from pathlib import Path
    text = " ".join(Path("rules_1.txt").read_text(encoding="utf-8").split())
    found = re.search(r"except these unique roles, which appear at most once: (.+?)\.", text)
    assert found
    assert set(found[1].split(", ")) == {r for r, i in ROLES.items() if i.unique}


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
    assert any("(4 Guilty of 7 votes; 4 needed; there are more votes than the 6 voters" in e.text for e in game.events)
    game.run_dawn_hooks()  # the next day, without a new token, Frank's Innocent is back to one vote
    guilty.clear()
    guilty.update({"Bob", "Carol", "Erin"})
    assert run_trial(game, players, game.player("Bob"), "Dave", 1) == "executed"  # 3 of 5, not 3 of 6


def test_surveyor_group_skips_itself_and_shrinks_in_small_games(game_factory):
    from roles.base import neighbor_group
    game, players = game_factory(["Surveyor", "Vanilla Villager", "Medic", "Grunt", "Pharmacist", "Jester"])
    game.phase = "night"
    assert neighbor_group(game, "Alice", "Bob") == ["Frank", "Bob", "Carol"]  # skips Alice, wraps around
    game.kill("Carol", "Katana")  # died tonight: still in the group (alive at the start of the night)
    assert neighbor_group(game, "Alice", "Bob") == ["Frank", "Bob", "Carol"]
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    mod.dispatch("apply_changes", {"changes": [{"op": "survey", "player": "Bob", "by": "Alice"}]})
    result = next(e for e in game.events if e.cat == "result")
    assert result.visible_to == {"Alice"} and "You surveyed Frank, Bob and Carol." in result.text
    assert any(role in result.text for role in ("Jester", "Vanilla Villager", "Medic"))
    assert game.player("Alice").tokens["survey"] == 2
    for name in ["Carol", "Dave", "Erin"]:
        game.player(name).alive, game.player(name).death = False, None  # died on earlier days
    assert neighbor_group(game, "Alice", "Bob") == ["Frank", "Bob"]  # two others alive
    game.player("Frank").alive, game.player("Frank").death = False, None
    assert neighbor_group(game, "Alice", "Bob") == ["Bob"]


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
    mod.dispatch("apply_changes", {"changes": [{"op": "give_token", "player": "Bob", "by": "Alice"}]})
    with pytest.raises(ValueError, match="already has a give_token op in this batch"):  # one action a night
        mod.dispatch("apply_changes", {"changes": [{"op": "give_token", "player": "Carol", "by": "Alice"}] * 2})
    game.day += 1
    mod.dispatch("apply_changes", {"changes": [{"op": "give_token", "player": "Carol", "by": "Alice"}]})
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


def test_cardinal_curse_kills_a_good_player_at_the_end_of_the_night(game_factory):
    game, _ = game_factory(["Cardinal", "Vanilla Villager", "Vanilla Villager", "Grunt"])
    game.kill("Alice", "executed by hanging", guilty_voters=["Dave"])
    game.phase = "night"
    game.run_night_end_hooks()
    assert [p.name for p in game.alive()] in (["Bob", "Dave"], ["Carol", "Dave"])
    victim = next(p for p in game.players[1:3] if not p.alive)
    assert victim.death["phase"] == "night"  # a night death, for the stall rule and wills (R13, R14)


def test_a_cursed_cardinal_curses_in_turn_the_same_night(game_factory):
    game, _ = game_factory(["Cardinal", "Cardinal", "Grunt", "Grunt"])
    game.phase = "night"
    game.kill("Alice", "Katana")
    game.run_night_end_hooks()  # Bob is the only Good player left; his curse then finds nobody
    assert [p.name for p in game.alive()] == ["Carol", "Dave"]


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


def test_op_names_are_unique_across_roles():
    """The moderator routes an op by its name alone, so two roles with one name (the Auditor's and Accountant's
    'audit') send one role's ops to the other's checks."""
    from moderator import CORE_OPS
    from roles.base import LOGIC
    owners: dict[str, list[str]] = {}
    for role, r in LOGIC.items():
        for op in r.ops:
            owners.setdefault(op, []).append(role)
    assert not {op: roles for op, roles in owners.items() if len(roles) > 1 or op in CORE_OPS}


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
    history = night_history(game, game.player("Alice"))
    assert action["target"] not in history and "Night 1: your automatic action (random visit) was due" in history


def test_trapper_is_told_whether_their_trap_still_stands(game_factory):
    from players import role_briefing
    from roles import Status
    game, _ = game_factory(["Trapper", "Vanilla Villager", "Grunt"])
    trapper = game.player("Alice")
    assert "no trap set" in role_briefing(game, trapper)
    game.player("Bob").status[Status.TRAPPED_BY] = "Alice"
    assert "Your trap is on Bob" in role_briefing(game, trapper)
    assert "can't trap Bob again" in role_briefing(game, trapper)  # Kevin, Oct 10: removing it is allowed instead
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


def test_smuggler_swap_redirects_every_other_action_before_the_katana_tally(game_factory):
    from night import run_night
    choices = {"Alice": {"act": True, "target": "Erin", "second_target": "Frank", "katana_vote_holder": "Alice",
                         "katana_vote_target": "Erin"},
               "Bob": {"act": False, "katana_vote_holder": "Alice", "katana_vote_target": "Erin"},
               "Carol": {"act": True, "target": "Erin"}, "Dave": {"act": True, "target": "Frank"}}

    def decide(name, task, schema):
        return choices.get(name) if "Choose your night action" in task else None
    roles = ["Smuggler", "Grunt", "Sheriff", "Medic", "Vanilla Villager", "Vanilla Villager"]
    game, players = game_factory(roles, ScriptedClient(decide))
    run_night(game, players, Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)"))
    acts = game.night_actions[1]
    assert acts["Alice"]["target"] == "Erin" and acts["Alice"]["second_target"] == "Frank"  # its own action stays
    assert acts["Carol"]["target"] == "Frank" and acts["Carol"]["chosen_target"] == "Erin"
    assert acts["Dave"]["target"] == "Erin" and acts["Dave"]["chosen_target"] == "Frank"
    assert acts["Bob"]["katana_vote_target"] == "Frank"
    katana = next(r for r in map(json.loads, open(game.log.path)) if r["kind"] == "katana")
    assert katana["result"]["attack"] == "Frank"
    prompt = next(r for r in map(json.loads, open(game.log.path)) if r["kind"] == "moderator_prompt")
    assert ("Alice swapped Erin and Frank. Code has ALREADY applied them" in prompt["instructions"]
            and "The Katana attack lands on Frank." in prompt["instructions"])
    assert game.player("Alice").tokens["swap"] == 1
    assert any("You swapped Erin and Frank. You have 1 swap token left." in t for t in told(game, "Alice"))
    assert len([t for t in told(game, "Erin") + told(game, "Frank") if "swapped with another player" in t]) == 2
    assert not any("swapped with another player" in t for t in told(game, "Carol"))
    from feedback import night_replay  # the after-game replay shows each choice and where the swap moved it
    replay = night_replay(game)
    assert "- Carol (Sheriff): target Erin (swapped to Frank)" in replay
    assert "Bob (Grunt): no role action; Katana vote: Alice holds, attacks Erin (swapped to Frank)" in replay
    assert "Alice (Smuggler): target Erin; second target Frank;" in replay  # the swap itself isn't moved


def test_a_swap_doesnt_move_the_jesters_revenge_or_the_cardinals_curse(game_factory):
    """Rules R23: effects that draw their own victim at random aren't actions aimed at a player."""
    from night import run_night
    choices = {"Dave": {"act": True, "target": "Bob", "second_target": "Erin"}}

    def decide(name, task, schema):
        return choices.get(name) if "Choose your night action" in task else None
    game, players = game_factory(["Jester", "Vanilla Villager", "Cardinal", "Smuggler", "Grunt", "Grunt"],
                                 ScriptedClient(decide))
    game.kill("Alice", "executed by hanging", guilty_voters=["Bob"])  # Bob: the only Guilty voter
    game.kill("Carol", "executed by hanging", guilty_voters=["Dave"])  # Bob: the only Good player left
    run_night(game, players, Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)"))
    assert any("You swapped Bob and Erin" in t for t in told(game, "Dave"))
    assert not game.player("Bob").alive and game.player("Erin").alive


def test_smuggler_without_tokens_or_two_players_does_nothing(game_factory):
    game, _ = game_factory(["Smuggler", "Grunt", "Vanilla Villager", "Vanilla Villager"])
    from roles import logic
    actions = {"Alice": {"act": True, "target": "Carol", "second_target": "Carol"},
               "Bob": {"act": False, "katana_vote_target": "Carol"}}
    logic("Smuggler").before_resolution(game, actions)
    assert actions["Bob"]["katana_vote_target"] == "Carol" and game.player("Alice").tokens["swap"] == 2


def test_a_swap_can_land_an_others_only_action_on_its_user_and_the_result_names_the_choice(game_factory):
    # game_20261010_053523_23052 night 3: Bob swapped Alice and Carol, so Alice's profile of Carol landed on Alice
    game, players = game_factory(["Profiler", "Smuggler", "Vanilla Villager", "Grunt"])
    game.phase = "night"
    with pytest.raises(ValueError, match="can't target themselves"):
        apply_ops(game, players, {"op": "profile", "by": "Alice", "player": "Alice"})
    game.role_state["swaps"] = {game.day: [["Bob", "Alice", "Carol"]]}
    apply_ops(game, players, {"op": "profile", "by": "Alice", "player": "Alice"})  # rules R23
    result = told(game, "Alice")[-1]
    assert "You profiled Carol: their role is " in result and "Profiler" in result


def test_group_results_on_a_swapped_target_trade_the_pair_s_names(game_factory):
    roles = ["Census Taker", "Smuggler", "Vanilla Villager", "Grunt", "Surveyor", "Diviner", "Vanilla Villager"]
    game, players = game_factory(roles)
    game.phase = "night"
    game.role_state["swaps"] = {game.day: [["Bob", "Carol", "Grace"]]}  # actions aimed at Carol land on Grace
    apply_ops(game, players, {"op": "census", "by": "Alice", "player": "Grace"},
              {"op": "survey", "by": "Erin", "player": "Grace"}, {"op": "divine", "by": "Frank", "player": "Grace"})
    assert "Your census of " in told(game, "Alice")[-1] and "Carol" in told(game, "Alice")[-1]
    assert told(game, "Erin")[-1].startswith("Moderator (private): You surveyed Alice, Carol and Frank.")  # rules R23
    assert "You divined Carol; the group was Alice, Carol and Erin." in told(game, "Frank")[-1]


def test_census_counts_true_alignment_and_never_neutrals(game_factory):
    from roles.census_taker import census_group
    game, players = game_factory(["Census Taker", "Grunt", "Ex-Con", "Jester", "Vanilla Villager", "Pharmacist"])
    game.phase = "night"
    assert game.katana_holder == "Bob"
    for _ in range(20):
        group = census_group(game, "Alice", "Dave")
        assert len(group) == 3 and "Dave" in group and "Alice" not in group
    for _ in range(10):  # Bob holds the Katana (still Evil here), Carol is an Ex-Con (still Good), Dave is Neutral
        apply_ops(game, players, {"op": "census", "by": "Alice", "player": "Dave"})
        text = told(game, "Alice")[-1]
        m = re.search(r"census of (.+) counted (Good|Evil) players .*: (\d) of the", text)
        assert m, text
        group = m[1].replace(" and ", ", ").split(", ")
        want = sum(game.player(q).info.alignment.value == m[2] for q in group)
        assert int(m[3]) == want and "Neutral players are never counted" in text


def test_census_group_shrinks_when_few_players_are_left(game_factory):
    from roles.census_taker import census_group
    game, _ = game_factory(["Census Taker", "Grunt", "Vanilla Villager"])
    game.phase = "night"
    assert census_group(game, "Alice", "Bob") == ["Bob", "Carol"]
    game.kill("Carol", "Katana")  # died tonight: still in the pool
    assert census_group(game, "Alice", "Bob") == ["Bob", "Carol"]
    game.day += 1
    assert census_group(game, "Alice", "Bob") == ["Bob"]


def test_profiler_gets_three_roles_one_true_with_both_good_and_not_good(game_factory):
    from roles.profiler import profile_candidates
    from roles import ROLES, Alignment
    game, players = game_factory(["Profiler", "Medic", "Sheriff", "Grunt", "Jester", "Vanilla Villager"])
    game.phase = "night"
    game.kill("Erin", "Katana")  # died tonight: the Jester is still in play
    for target in ["Bob", "Dave", "Erin"]:
        for _ in range(20):
            roles = profile_candidates(game, "Alice", target)
            assert len(set(roles)) == 3 and game.player(target).role in roles and roles == sorted(roles)
            assert {ROLES[r].alignment is Alignment.GOOD for r in roles} == {True, False}
            assert "Profiler" not in roles  # the Profiler's own seat isn't a decoy source
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    mod.dispatch("apply_changes", {"changes": [{"op": "profile", "player": "Bob", "by": "Alice"}]})
    result = [e for e in game.events if e.cat == "result"][-1]
    assert result.visible_to == {"Alice"} and "You profiled Bob: their role is" in result.text
    assert "Medic" in result.text and "2 profile tokens left" in result.text


def test_profiler_decoys_are_one_role_in_play_and_one_nobody_has(game_factory):
    import random
    from collections import Counter
    from roles.profiler import profile_candidates
    from roles import ROLES, Alignment
    game, _ = game_factory(["Profiler", "Medic", "Sheriff", "Grunt", "Jester", "Vanilla Villager"])
    game.phase = "night"
    in_play, roles_in_game = {"Sheriff", "Grunt", "Jester", "Vanilla Villager"}, {p.role for p in game.players}
    names_real_not_good: Counter = Counter()
    for seed in range(200):
        game.rng = random.Random(seed)
        decoys = set(profile_candidates(game, "Alice", "Bob")) - {"Medic"}
        assert len(decoys & in_play) == 1 and len(decoys - roles_in_game) == 1
        names_real_not_good[any(r in in_play for r in decoys if ROLES[r].alignment is not Alignment.GOOD)] += 1
    # Either decoy may supply the not-Good side: always the in-play one would name a real Evil role every time.
    assert names_real_not_good[True] > 40 and names_real_not_good[False] > 40


def test_coroner_examines_only_players_dead_before_the_night(game_factory):
    from players import night_action_schema
    game, players = game_factory(["Coroner", "Roleplayer", "Sheriff", "Grunt", "Executioner", "Vanilla Villager"])
    game.phase = "night"
    assert night_action_schema(game, game.player("Alice"))["properties"]["target"] == {"type": "null"}  # no dead yet
    for name in ("Bob", "Erin"):
        game.player(name).alive = False  # died on an earlier day
    game.player("Erin").status[Status.LEFT] = True  # left the game (an Executioner's win), didn't die
    game.kill("Carol", "Katana")  # dies tonight: not yet examinable
    assert night_action_schema(game, game.player("Alice"))["properties"]["target"]["anyOf"][0]["enum"] == ["Bob"]
    assert night_action_schema(game, game.player("Frank"))["properties"]["target"]["anyOf"][0]["enum"] == \
        ["Alice", "Dave", "Frank"]  # other roles still target the living
    for name in ("Carol", "Erin", "Dave"):
        with pytest.raises(ValueError, match="hadn't died before the night began"):
            apply_ops(game, players, {"op": "examine", "player": name, "by": "Alice"})
    apply_ops(game, players, {"op": "examine", "player": "Bob", "by": "Alice"})
    assert told(game, "Alice")[-1].endswith("You examined Bob: their role was Roleplayer. 2 coroner tokens left.")
    game.player("Bob").status[Status.CLEANED] = True  # a Mortician's clean hides the role from the Coroner
    apply_ops(game, players, {"op": "examine", "player": "Bob", "by": "Alice"})
    assert told(game, "Alice")[-1].endswith("You examined Bob: their body was cleaned by a Mortician, so you learned "
                                            "nothing more. 1 coroner token left.")


def test_profiler_decoys_fall_back_to_all_roles_in_tiny_games(game_factory):
    from roles.profiler import profile_candidates
    game, _ = game_factory(["Profiler", "Grunt", "Grunt"])
    game.phase = "night"
    roles = profile_candidates(game, "Alice", "Bob")
    assert "Grunt" in roles and len(set(roles)) == 3


@pytest.mark.parametrize("role", [r for r in ROLES if logic(r).action])
def test_recorded_actions_check_their_user_target_and_token(game_factory, role):
    action = logic(role).action
    assert action
    game, players = game_factory([role, "Vanilla Villager", "Vanilla Villager", "Grunt", "Medic"])
    game.phase = "night"
    op = {"op": action.op, "by": "Alice", **({"player": "Bob"} if action.target else {})}
    with pytest.raises(ValueError, match="is not a"):
        apply_ops(game, players, {**op, "by": "Carol"})
    if action.target == "dead":
        with pytest.raises(ValueError, match="hadn't died before the night began"):
            apply_ops(game, players, op)
        game.player("Bob").alive, game.player("Bob").death = False, None  # died on an earlier day
    elif action.target:
        game.player("Bob").alive, game.player("Bob").death = False, None  # died on an earlier day
        with pytest.raises(ValueError, match="wasn't alive at the start of the night"):
            apply_ops(game, players, op)
        game.player("Bob").alive = True
        if action.target == "other":
            with pytest.raises(ValueError, match="can't target themselves"):
                apply_ops(game, players, {**op, "player": "Alice"})
    if action.token:
        left = game.player("Alice").tokens[action.token]
        game.player("Alice").tokens[action.token] = 0
        with pytest.raises(ValueError, match=f"no {action.token} token"):
            apply_ops(game, players, op)
        game.player("Alice").tokens[action.token] = left
    apply_ops(game, players, op)
    assert game.player("Alice").tokens.get(action.token, 0) == (left - 1 if action.token else 0)
    assert action.op in logic(role).night_note


@pytest.mark.parametrize("role", [r for r in ROLES if getattr(logic(r).action, "target", "") in ("other", "any")])
def test_a_swapped_recorded_action_tells_its_user_the_player_they_chose(game_factory, role):
    """Rules R23: the moderator records the action on the player it landed on (Carol); the private result must name
    the player its user chose (Bob), in every role, so a new role can't leak the swap by naming its target."""
    game, players = game_factory([role, "Vanilla Villager", "Vanilla Villager", "Grunt", "Medic", "Smuggler"])
    game.phase = "night"
    game.role_state["swaps"] = {game.day: [["Frank", "Bob", "Carol"]]}
    before = len(told(game, "Alice"))
    action = logic(role).action
    assert action
    apply_ops(game, players, {"op": action.op, "by": "Alice", "player": "Carol"})
    game.run_night_end_hooks()  # results told at the end of the night (Accountant, Magpie) too
    for text in told(game, "Alice")[before:]:  # roles that never tell a result have nothing here
        assert "Bob" in text  # e.g. "You marked Bob"; group results list both, with the names traded


def test_chronicler_mark_moved_by_a_swap_looks_to_its_user_like_a_mark_on_the_player_they_chose(game_factory):
    game, players = game_factory(["Chronicler", "Sheriff", "Grunt", "Vanilla Villager", "Medic", "Smuggler"])
    game.phase = "night"
    game.role_state["swaps"] = {game.day: [["Frank", "Bob", "Carol"]]}
    apply_ops(game, players, {"op": "mark", "player": "Carol", "by": "Alice"})  # Alice chose Bob (rules R23)
    assert game.player("Carol").status[Status.MARKED] == "Alice" and Status.MARKED not in game.player("Bob").status
    assert "You marked Bob" in told(game, "Alice")[-1]
    assert logic("Chronicler").briefing(game, game.player("Alice")) == ["Your marks on living players: Bob."]
    game.role_state["swaps"] = {}
    with pytest.raises(ValueError, match="Alice already marked Bob"):
        apply_ops(game, players, {"op": "mark", "player": "Bob", "by": "Alice"})
    apply_ops(game, players, {"op": "mark", "player": "Carol", "by": "Alice"})  # not refused: that would show the swap
    assert "You marked Carol" in told(game, "Alice")[-1]


def test_record_visits_checks_names_and_is_needed_before_a_night_ends(game_factory):
    game, players = game_factory(["Cartographer", "Medic", "Sheriff", "Grunt", "Vanilla Villager"])
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    game.phase = "day"
    with pytest.raises(ValueError, match="night"):
        mod.dispatch("record_visits", {"visits": []})
    game.phase = "night"
    game.player("Erin").alive = False  # died on an earlier day
    for bad in ([["Bob", "Zed"]], [["Bob"]], [["Bob", "Erin"]]):
        with pytest.raises(ValueError, match="nothing was recorded"):
            mod.dispatch("record_visits", {"visits": bad})
    assert mod.dispatch("end_phase", {"summary": ""})["ok"] is False  # reminded once
    assert mod.dispatch("end_phase", {"summary": ""})["ok"] is True
    assert game.log.error_counts == {"visits_missing": 1}
    game.kill("Dave", "Katana")  # died tonight: still in tonight's graph
    assert mod.dispatch("record_visits", {"visits": [["Dave", "Bob"], ["Dave", "Bob"]]})["recorded"] == 2
    assert game.night_visits[game.day] == [["Dave", "Bob"], ["Dave", "Bob"]]


def test_visit_groups_are_undirected_components_of_players_alive_at_night_start(game_factory):
    from roles.base import visit_groups
    game, _ = game_factory(["Cartographer", "Medic", "Sheriff", "Grunt", "Vanilla Villager", "Vanilla Villager"])
    game.phase = "night"
    assert visit_groups(game) is None
    game.player("Frank").alive = False  # died on an earlier day: not in the graph
    game.kill("Dave", "Katana")
    game.night_visits[game.day] = [["Dave", "Carol"], ["Bob", "Carol"], ["Erin", "Erin"], ["Bob", "Carol"]]
    assert visit_groups(game) == [["Bob", "Carol", "Dave"], ["Alice"], ["Erin"]]


def test_cartographer_gets_sizes_every_night_and_names_with_a_token(game_factory):
    game, players = game_factory(["Cartographer", "Medic", "Sheriff", "Grunt", "Vanilla Villager"])
    game.phase = "night"
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    mod.dispatch("apply_changes", {"changes": [{"op": "map", "player": "Bob", "by": "Alice"}]})
    mod.dispatch("record_visits", {"visits": [["Dave", "Bob"], ["Bob", "Erin"], ["Carol", "Carol"]]})
    game.run_night_end_hooks()
    assert told(game, "Alice")[-1].endswith("Tonight's visit groups have sizes 3, 1, 1. You mapped Bob: their group "
                                            "is Bob, Dave and Erin. 1 map token left.")
    game.day += 1  # a night with no map (e.g. role-blocked): sizes only
    mod.dispatch("record_visits", {"visits": []})
    game.run_night_end_hooks()
    assert told(game, "Alice")[-1].endswith("Tonight's visit groups have sizes 1, 1, 1, 1, 1.")


def test_cartographer_token_is_spent_even_when_no_visits_were_recorded(game_factory):
    game, players = game_factory(["Cartographer", "Medic", "Sheriff", "Grunt", "Vanilla Villager"])
    game.phase = "night"
    apply_ops(game, players, {"op": "map", "player": "Bob", "by": "Alice"})
    game.run_night_end_hooks()
    assert game.player("Alice").tokens["map"] == 1 and game.log.error_counts == {"cartographer_no_visits": 1}


def test_scout_learns_three_players_from_different_visit_groups(game_factory):
    from roles.base import visit_groups
    game, players = game_factory(["Scout", "Medic", "Sheriff", "Grunt", "Vanilla Villager", "Vanilla Villager"])
    game.phase = "night"
    game.night_visits[game.day] = [["Dave", "Bob"], ["Carol", "Bob"], ["Erin", "Alice"]]
    groups = {n: tuple(g) for g in visit_groups(game) or [] for n in g}
    for _ in range(20):
        game.run_night_end_hooks()
        names = re.findall(r"Bob|Carol|Dave|Erin|Frank|Alice", told(game, "Alice")[-1].split(":", 1)[1])
        assert len(names) == 3 and len({groups[n] for n in names}) == 3


def test_scout_with_fewer_than_three_groups(game_factory):
    game, players = game_factory(["Scout", "Medic", "Grunt", "Vanilla Villager"])
    game.phase = "night"
    game.night_visits[game.day] = [["Carol", "Bob"], ["Bob", "Dave"], ["Alice", "Dave"]]
    game.run_night_end_hooks()
    assert "were all in one visit group tonight, including" in told(game, "Alice")[-1]
    game.night_visits[game.day] = [["Carol", "Bob"], ["Bob", "Dave"]]  # Alice alone
    game.run_night_end_hooks()
    assert "Alice" in told(game, "Alice")[-1] and "only 2 visit groups" in told(game, "Alice")[-1]
def test_a_diviner_may_pick_themselves_for_strong_defense(game_factory):
    # rules Diviner: picking a Yakuza (themselves included) gives Strong Defense, which the moderator applies; no op.
    game, players = game_factory(["Diviner", "Vanilla Villager", "Vanilla Villager", "Medic"])
    game.phase = "night"
    with pytest.raises(ValueError, match="Strong Defense"):
        apply_ops(game, players, {"op": "divine", "player": "Alice", "by": "Alice"})


def test_the_roleplayer_rule_lists_exactly_the_roles_it_can_be():
    from pathlib import Path
    rules = Path("rules_1.txt").read_text(encoding="utf-8")
    text = " ".join(rules.split("\nRoleplayer\n", 1)[1].split("\n\n")[0].split())
    found = re.search(r"at the start from (.+?)\.", text)
    assert found
    listed = set(re.split(r", | and ", found[1]))
    assert listed == {r for r, i in ROLES.items() if i.category == "Investigative" and logic(r).roleplayer_can_fake}


def test_a_game_starts_with_wills_and_night_1_without_a_day_1(tmp_path, monkeypatch):
    # rules R1 (Kevin, Oct 10): no Day 1; players write a first will, then Night 1
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    roles = ["Vanilla Villager", "Vanilla Villager", "Sheriff", "Medic", "Grunt", "Pharmacist"]
    path = mafia.play_game(MockClient(3), mafia.GameConfig([Model.HAIKU_5_5], Model.HAIKU_5_5, roles, seed=3))
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    day1 = [r for r in records if r["kind"] == "player_call" and r.get("day") == 1 and r.get("phase") == "day"]
    assert day1 and {r["step"] for r in day1} == {"will"}
    texts = [r.get("text", "") for r in records if r["kind"] == "event"]
    assert not any(t == "Day 1 begins." for t in texts) and any(t.startswith("There is no Day 1") for t in texts)


def test_vigilante_learns_the_role_of_a_player_it_kills(game_factory):
    game, players = game_factory(["Vigilante", "Roleplayer", "Grunt", "Vanilla Villager", "Vanilla Villager"])
    game.phase = "night"
    apply_ops(game, players, {"op": "kill", "player": "Bob", "cause": "Vigilante", "by": "Alice"})
    game.kill("Dave", "Katana", by="Carol", katana=True)
    game.run_night_end_hooks()
    assert told(game, "Alice")[-1].endswith("Your shot killed Bob. Their role was Roleplayer.")  # exact-role (R19)
    assert not any("Dave" in t for t in told(game, "Alice"))  # someone else's kill tells the Vigilante nothing


def test_a_vigilante_killed_earlier_in_the_resolution_still_learns_its_victims_role(game_factory):
    # rules R10: the order of the moderator's ops within a night doesn't matter
    game, players = game_factory(["Vigilante", "Grunt", "Vanilla Villager", "Vanilla Villager"])
    game.phase = "night"
    apply_ops(game, players, {"op": "kill", "player": "Alice", "cause": "Katana", "by": "Bob", "katana": True},
              {"op": "kill", "player": "Bob", "cause": "Vigilante", "by": "Alice"})
    game.run_night_end_hooks()
    assert told(game, "Alice")[-1].endswith("Your shot killed Bob. Their role was Grunt.")


def test_only_doused_players_who_arent_good_are_told(game_factory):
    from roles.base import logic
    game, players = game_factory(["Arsonist", "Grunt", "Ex-Con", "Jester", "Vanilla Villager"])
    game.phase = "night"
    apply_ops(game, players, *({"op": "set_status", "player": n, "key": "doused", "value": True}
                               for n in ("Bob", "Carol", "Dave")))
    logic("Arsonist").at_night_end(game)
    told_doused = {n for n in ("Bob", "Carol", "Dave") if any("doused you" in t for t in told(game, n))}
    assert told_doused == {"Bob", "Dave"}  # the Ex-Con reads Evil but is Good: not told
    logic("Arsonist").at_night_end(game)  # a douse that's still there isn't news the next night
    assert sum("doused you" in t for t in told(game, "Bob")) == 1
    apply_ops(game, players, {"op": "set_status", "player": "Bob", "key": "doused", "value": None})  # ignited
    logic("Arsonist").at_night_end(game)
    apply_ops(game, players, {"op": "set_status", "player": "Bob", "key": "doused", "value": True})  # doused again
    logic("Arsonist").at_night_end(game)
    assert sum("doused you" in t for t in told(game, "Bob")) == 2


def test_vulture_hears_a_half_true_role_for_each_new_death(game_factory):
    from roles.vulture import report_deaths
    game, _ = game_factory(["Vulture", "Roleplayer", "Grunt", "Executioner", "Vanilla Villager", "Vanilla Villager"])
    vulture = [game.player("Alice")]
    game.kill("Bob", "Katana")
    game.player("Dave").alive = False
    game.player("Dave").status[Status.LEFT] = True  # left the game, didn't die: no report
    game.rng.random = lambda: 0.0  # type: ignore[method-assign]  # the true role
    report_deaths(game, vulture)
    assert told(game, "Alice")[-1].endswith("Bob: Roleplayer.")  # exact-role check (R19)
    report_deaths(game, vulture)  # nothing new: no second report
    assert len(told(game, "Alice")) == 1
    game.kill("Carol", "executed by hanging")
    game.rng.random = lambda: 0.9  # type: ignore[method-assign]  # a fake: any other role
    report_deaths(game, vulture)
    fake = told(game, "Alice")[-1].rsplit("Carol: ", 1)[1].rstrip(".")
    assert fake in ROLES and fake != "Grunt" and "Bob" not in told(game, "Alice")[-1]


def test_auditor_learns_every_vote_its_target_cast_that_day(game_factory):
    game, players = game_factory(["Auditor", "Grunt", "Vanilla Villager", "Vanilla Villager", "Vanilla Villager"])
    game.day = 3
    game.votes[2] = [{"stage": "trial", "nominee": "Erin", "votes": {"Bob": True}}]  # an earlier Day: not this one
    game.votes[3] = [{"stage": "nomination", "nominee": "Carol", "votes": {"Bob": True, "Dave": False}},
                     {"stage": "trial", "nominee": "Carol", "votes": {"Bob": False, "Dave": True}}]
    game.phase = "night"
    apply_ops(game, players, {"op": "audit", "player": "Bob", "by": "Alice"})
    assert told(game, "Alice")[-1].endswith("Your audit of Bob's votes during the Day, in order: Yes on the "
                                            "nomination of Carol; Innocent in the trial of Carol.")


def test_informant_sees_every_secret_trial_vote(game_factory):
    from day import run_trial
    game, players = game_factory(["Informant", "Grunt", "Vanilla Villager", "Vanilla Villager", "Vanilla Villager"],
                                 ScriptedClient(votes(guilty_for={"Erin"})))
    run_trial(game, players, game.player("Carol"), "Erin", rnd=1)
    seen = [t for t in told(game, "Alice") if "How everyone voted" in t]
    assert len(seen) == 1 and "Guilty - Alice, Bob, Carol, Dave" in seen[0]
    assert not any("How everyone voted" in t for t in told(game, "Bob"))  # other Yakuza aren't told


def test_fixer_reverses_a_players_trial_votes_the_next_day_and_nobody_is_told(game_factory):
    from day import run_trial
    game, players = game_factory(["Fixer", "Informant", "Vanilla Villager", "Vanilla Villager", "Vanilla Villager"],
                                 ScriptedClient(votes(guilty_for={"Erin"})))
    game.phase = "night"
    apply_ops(game, players, {"op": "fix", "player": "Carol", "by": "Alice"})
    assert game.player("Alice").tokens["fixer"] == 1
    game.announce_dawn()
    game.run_dawn_hooks()
    game.phase = "day"
    run_trial(game, players, game.player("Dave"), "Erin", rnd=1)
    seen = next(t for t in told(game, "Bob") if "How everyone voted" in t)  # the Informant sees the counted vote
    assert "Innocent - Carol" in seen
    assert any(t.endswith("You voted Guilty in the trial of Erin.") for t in told(game, "Carol"))  # what she cast
    assert not any("fix" in t.lower() for t in told(game, "Carol"))
    assert game.votes[game.day][-1]["votes"]["Carol"] is False  # the Auditor reads the counted vote too


def test_insomniac_hears_up_to_three_random_visitors_roles_in_alphabetical_order(game_factory):
    game, players = game_factory(["Insomniac", "Medic", "Sheriff", "Grunt", "Tracker", "Lookout"])
    game.phase = "night"
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    mod.dispatch("apply_changes", {"changes": [{"op": "stay_awake", "by": "Alice"}]})
    mod.dispatch("record_visits", {"visits": [["Bob", "Bob"], ["Carol", "Dave"], ["Dave", "Carol"],
                                              ["Erin", "Carol"], ["Frank", "Dave"], ["Bob", "Carol"]]})
    game.run_night_end_hooks()
    last = told(game, "Alice")[-1]
    assert "More than 3 players visited" in last and last.endswith("1 insomniac token left.")
    heard = last.split("Their roles: ")[1].split(".")[0].split(", ")
    assert len(heard) == 3 and heard == sorted(heard) and set(heard) < {"Medic", "Sheriff", "Grunt", "Tracker",
                                                                         "Lookout"}
    game.day += 1  # fewer than 3 visitors: all of them, a repeated visitor once
    mod.dispatch("apply_changes", {"changes": [{"op": "stay_awake", "by": "Alice"}]})
    mod.dispatch("record_visits", {"visits": [["Erin", "Bob"], ["Carol", "Bob"], ["Carol", "Dave"]]})
    game.run_night_end_hooks()
    assert told(game, "Alice")[-1].endswith("heard every player who visited someone tonight. Their roles: Sheriff, "
                                            "Tracker. 0 insomniac tokens left.")


def test_insomniac_with_no_visitors_or_no_recorded_visits(game_factory):
    game, players = game_factory(["Insomniac", "Medic", "Sheriff", "Grunt", "Vanilla Villager"])
    game.phase = "night"
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    mod.dispatch("apply_changes", {"changes": [{"op": "stay_awake", "by": "Alice"}]})
    mod.dispatch("record_visits", {"visits": []})
    game.run_night_end_hooks()
    assert "nobody visited anyone tonight" in told(game, "Alice")[-1]
    game.day += 1
    apply_ops(game, players, {"op": "stay_awake", "by": "Alice"})
    game.run_night_end_hooks()
    assert game.player("Alice").tokens["insomniac"] == 0 and game.log.error_counts == {"insomniac_no_visits": 1}


def test_chronicler_mark_reveals_the_role_on_any_later_death_even_after_the_chronicler_died(game_factory):
    game, players = game_factory(["Chronicler", "Sheriff", "Grunt", "Vanilla Villager", "Medic"])
    game.phase = "night"
    apply_ops(game, players, {"op": "mark", "player": "Carol", "by": "Alice"})
    assert told(game, "Alice")[-1].endswith("1 chronicler token left.") and not told(game, "Carol")
    with pytest.raises(ValueError, match="Alice already marked Carol"):
        apply_ops(game, players, {"op": "mark", "player": "Carol", "by": "Alice"})
    assert logic("Chronicler").briefing(game, game.player("Alice")) == ["Your marks on living players: Carol."]
    game.kill("Alice", "Katana")  # the mark outlives the Chronicler
    game.announce_dawn()
    game.phase = "day"
    game.kill("Carol", "Execution by Hanging")
    reveal = [e.text for e in game.events if e.cat == "death"][-1]
    assert reveal.endswith("They had been marked by a Chronicler, so their role is revealed: Grunt.")
    assert "Grunt (revealed)" in game.death_record[-1]
    assert "role isn't revealed" in [e.text for e in game.events if e.cat == "death"][0]  # unmarked Alice


def test_mortician_clean_beats_a_chronicler_mark_and_the_announcement_says_so(game_factory):
    game, players = game_factory(["Chronicler", "Sheriff", "Mortician", "Grunt", "Vanilla Villager"])
    game.phase = "night"
    apply_ops(game, players, {"op": "mark", "player": "Bob", "by": "Alice"},
              {"op": "kill", "player": "Bob", "cause": "Katana"},
              {"op": "set_status", "player": "Bob", "key": Status.CLEANED, "value": True})
    game.announce_dawn()
    reveal = next(e.text for e in game.events if e.cat == "death")
    assert "Sheriff" not in reveal and "Sheriff" not in game.death_record[0]
    assert reveal.endswith("They had been marked by a Chronicler, but the Mortician's clean hides the role too, so "
                           "it isn't revealed.")


def test_juror_counts_shared_votes_over_the_game_skipping_votes_on_either(game_factory):
    game, players = game_factory(["Juror", "Medic", "Sheriff", "Grunt", "Vanilla Villager"])
    game.votes = {
        2: [{"stage": "nomination", "nominee": "Erin", "votes": {"Bob": True, "Carol": True, "Dave": False}},
            {"stage": "trial", "nominee": "Erin", "votes": {"Bob": True, "Carol": False, "Dave": True}}],
        3: [{"stage": "nomination", "nominee": "Bob", "votes": {"Bob": True, "Carol": False}},  # on Bob: skipped
            {"stage": "trial", "nominee": "Dave", "votes": {"Bob": False, "Carol": False}},
            {"stage": "trial", "nominee": "Alice", "votes": {"Bob": True}}],  # Carol didn't vote: skipped
    }
    game.phase = "night"
    apply_ops(game, players, {"op": "jury", "player": "Bob", "second": "Carol", "by": "Alice"})
    assert told(game, "Alice")[-1].endswith("Bob and Carol voted the same way in 1 of 2 trial votes and 1 of 1 "
                                            "nomination votes.")
    game.player("Erin").alive = False  # dead players can be compared
    apply_ops(game, players, {"op": "jury", "player": "Erin", "second": "Dave", "by": "Alice"})
    assert told(game, "Alice")[-1].endswith("Erin and Dave have no shared votes yet.")
    for bad in ({"player": "Bob", "second": "Bob"}, {"player": "Alice", "second": "Bob"},
                {"player": "Bob", "second": "Zed"}):
        with pytest.raises(ValueError):
            apply_ops(game, players, {"op": "jury", "by": "Alice", **bad})
    from players import night_action_schema
    assert "Erin" in json.dumps(night_action_schema(game, game.player("Alice"))["properties"]["second_target"])


def test_scrutineer_counts_guilty_votes_of_a_group_of_three_per_trial(game_factory):
    game, players = game_factory(["Scrutineer", "Medic", "Sheriff", "Grunt", "Vanilla Villager"])
    every = {"Alice": False, "Bob": True, "Carol": True, "Dave": True, "Erin": False}
    game.votes = {game.day: [{"stage": "nomination", "nominee": "Erin", "votes": {**every}},
                             {"stage": "trial", "nominee": "Erin", "votes": {**every}},
                             {"stage": "trial", "nominee": "Dave", "votes": dict.fromkeys(every, False)}]}
    game.phase = "night"
    apply_ops(game, players, {"op": "scrutinize", "player": "Bob", "by": "Alice"})
    text = told(game, "Alice")[-1]
    group = re.findall(r"Bob|Carol|Dave|Erin", text.split(":", 2)[1])
    assert "Bob" in group and "Alice" not in text.split(":", 2)[1] and len(set(group)) == 3
    assert f"{sum(every[n] for n in set(group))} in the trial of Erin; 0 in the trial of Dave." in text
    game.day += 1  # no trials that Day
    apply_ops(game, players, {"op": "scrutinize", "player": "Bob", "by": "Alice"})
    assert told(game, "Alice")[-1].endswith("there were no trials during the Day.")


def test_bloodhound_counts_recorded_attacks_of_three_players_over_the_game(game_factory):
    from roles.bloodhound import attack_count
    game, players = game_factory(["Bloodhound", "Vigilante", "Sheriff", "Grunt", "Vanilla Villager"])
    game.phase = "night"
    apply_ops(game, players, {"op": "attacks", "attackers": ["Dave", "Bob"]})
    with pytest.raises(ValueError, match="no player named"):
        apply_ops(game, players, {"op": "attacks", "attackers": ["Zed"]})
    apply_ops(game, players, {"op": "track", "player": "Dave", "by": "Alice"})
    game.run_night_end_hooks()
    text = told(game, "Alice")[-1]
    group = re.findall(r"Bob|Carol|Dave|Erin", text.split(":", 2)[1])
    assert "Dave" in group and len(group) == 3 and "1 scent token left" in text
    assert f"together they have made {attack_count(game, group)} attack" in text
    game.day += 1  # a night with no token and no attacks op: still a result, and an alert for the missing record
    game.run_night_end_hooks()
    assert "this game, tonight's included." in told(game, "Alice")[-1]
    assert game.log.error_counts == {"attacks_missing": 1}
    game.role_state["attacks"][game.day] = ["Dave"]
    assert attack_count(game, ["Dave"]) == 2 and attack_count(game, ["Bob", "Carol"]) == 1


def test_bloodhound_counts_the_cardinals_curse_and_a_dead_trappers_trap(game_factory):
    game, players = game_factory(["Bloodhound", "Cardinal", "Trapper", "Grunt", "Vanilla Villager"])
    game.player("Carol").alive, game.player("Carol").death = False, None  # died on an earlier day; the trap lasts
    game.phase = "night"
    apply_ops(game, players, {"op": "attacks", "attackers": ["Carol", "Dave"]},
              {"op": "kill", "player": "Bob", "cause": "Katana", "by": "Dave", "katana": True},
              {"op": "track", "player": "Bob", "by": "Alice"})
    game.run_night_end_hooks()  # the Cardinal killed tonight curses Alice or Erin, then the Bloodhound counts
    group = re.findall(r"Bob|Dave|Erin", told(game, "Alice")[-1].split(":", 2)[1])
    assert "Bob" in group and len(group) == 3  # Bob: the curse (a Divine Attack), Dave: the Katana
    from roles.bloodhound import attack_count
    assert attack_count(game, ["Bob"]) == 1 and attack_count(game, group) == 2


def bounty_game(game_factory, roles=("Bounty Hunter", "Vanilla Villager", "Vanilla Villager", "Vanilla Villager",
                                     "Grunt")):
    from roles.bounty_hunter import bounty
    game, players = game_factory(list(roles))
    b = bounty(game, "Alice")
    b["targets"], b["claimed"], b["lost"] = ["Bob", "Carol", "Dave"], [], []
    return game, players, b


def test_bounty_hunter_gets_three_other_targets(tmp_path):
    import random

    from gamelog import GameLog
    from players import role_briefing
    from roles.bounty_hunter import bounty
    from state import setup_game
    game = setup_game(["Bounty Hunter"] + VILLAGE5 + ["Grunt"], [Model.HAIKU_5_5], random.Random(3),
                      GameLog(tmp_path / "t.jsonl"))
    hunter = next(p for p in game.players if p.role == "Bounty Hunter")
    targets = bounty(game, hunter.name)["targets"]
    assert len(set(targets)) == 3 and hunter.name not in targets
    assert "You win once 2 of them" in role_briefing(game, hunter)


def test_bounty_hunter_wins_and_leaves_after_a_kill_and_a_guilty_hanging(game_factory):
    game, _, b = bounty_game(game_factory)
    game.phase = "night"
    game.kill("Bob", "Bounty Hunter", by="Alice")
    game.run_night_end_hooks()
    assert b["claimed"] == ["Bob"] and game.player("Alice").alive
    game.phase = "day"
    game.kill("Carol", "executed by hanging", guilty_voters=["Alice", "Erin"])
    alice = game.player("Alice")
    assert "Alice" in game.personal_winners and not alice.alive and alice.status[Status.LEFT]
    assert game.death_count() == 2  # leaving isn't a death
    assert any("was the Bounty Hunter and claimed their bounties" in e.text for e in game.events)


def test_bounty_hunter_needs_its_own_guilty_vote_and_its_own_kill(game_factory):
    game, _, b = bounty_game(game_factory)
    game.kill("Bob", "executed by hanging", guilty_voters=["Erin"])
    assert b["lost"] == ["Bob"] and game.player("Alice").alive
    game.phase = "night"
    game.kill("Carol", "Katana", by="Erin")
    game.run_night_end_hooks()
    alice = game.player("Alice")  # two bounties lost: it can't win any more
    assert not alice.alive and alice.status[Status.LEFT] and "Alice" not in game.personal_winners
    game.phase = "day"
    game.announce_dawn()
    assert any("can no longer claim enough bounties" in e.text for e in game.events)


def test_bounty_hunter_dying_the_night_it_kills_its_second_target_still_wins(game_factory):
    game, _, b = bounty_game(game_factory)
    b["claimed"] = ["Bob"]
    game.phase = "night"
    game.kill("Alice", "Katana", by="Erin")  # dies first, so on_other_death skips it for Carol's death
    game.kill("Carol", "Bounty Hunter", by="Alice")
    game.run_night_end_hooks()
    alice = game.player("Alice")
    assert "Alice" in game.personal_winners and not alice.status.get(Status.LEFT)
    assert not any("was the Bounty Hunter" in e.text for e in game.events)  # a dead winner isn't revealed


def test_bounty_hunter_never_blocks_a_win(game_factory):
    game, _, _ = bounty_game(game_factory, ("Bounty Hunter", "Vanilla Villager", "Grunt"))
    game.kill("Carol", "executed by hanging", guilty_voters=["Bob"])
    assert game.check_winner() is not None


def test_talent_agent_scans_and_counts_living_true_roles(game_factory):
    game, players = game_factory(["Talent Agent", "Sheriff", "Sheriff", "Roleplayer", "Vanilla Villager"])
    game.phase = "night"
    game.player("Bob").alive = False  # died before the night: not in play
    game.player("Bob").death = {"day": 0, "phase": "day"}
    apply_ops(game, players, {"op": "scout_talent", "role": "Sheriff", "by": "Alice"})
    assert told(game, "Alice")[-1].endswith("Your count: 1 player alive when the night began has the role Sheriff.")
    with pytest.raises(ValueError, match="one token a night"):
        apply_ops(game, players, {"op": "scout_talent", "by": "Alice"})
    game.day += 1
    apply_ops(game, players, {"op": "scout_talent", "by": "Alice"})
    scan = told(game, "Alice")[-1]
    in_play = re.search(r"Your scan: (.+) is in play, and (.+) is not in play\.", scan)
    assert in_play and in_play[1] in {"Sheriff", "Roleplayer", "Vanilla Villager"}
    assert in_play[2] not in {"Sheriff", "Roleplayer", "Vanilla Villager", "Talent Agent"}
    assert ROLES[in_play[2]].alignment.name != "EVIL"
    game.day += 1
    apply_ops(game, players, {"op": "scout_talent", "role": "Roleplayer", "by": "Alice"})
    assert told(game, "Alice")[-1].endswith("1 player alive when the night began has the role Roleplayer.")
    game.day += 1
    with pytest.raises(ValueError):  # out of tokens
        apply_ops(game, players, {"op": "scout_talent", "by": "Alice"})


def test_talent_agent_counts_only_roles_on_the_script(game_factory):
    game, players = game_factory(["Talent Agent", "Sheriff", "Vanilla Villager"])
    game.phase = "night"
    with pytest.raises(ValueError, match="isn't a role"):
        apply_ops(game, players, {"op": "scout_talent", "role": "Wizard", "by": "Alice"})


def test_magpie_steals_after_token_use_and_wins_after_three_players(game_factory):
    game, players = game_factory(["Magpie", "Vigilante", "Medic", "Roleplayer", "Prosecutor", "Accountant", "Grunt"])
    game.phase = "night"
    apply_ops(game, players, {"op": "steal", "player": "Bob", "by": "Alice"},
              {"op": "count_tokens", "player": "Bob", "by": "Frank"},
              {"op": "set_tokens", "player": "Bob", "token": "vigilante", "value": 2})  # Bob shot tonight
    game.run_night_end_hooks()
    assert game.player("Bob").tokens["vigilante"] == 1
    assert told(game, "Alice")[-1].endswith("You stole a token from Bob (1 of 3).")
    assert told(game, "Bob")[-1].endswith("A Magpie stole one of your vigilante tokens. You have 1 left.")
    assert told(game, "Frank")[-1].endswith("Your audit: Bob has 1 token in total.")  # after the steal
    game.day += 1
    apply_ops(game, players, {"op": "steal", "player": "Bob", "by": "Alice"})
    game.run_night_end_hooks()
    assert game.player("Bob").tokens["vigilante"] == 1 and "already stole from Bob" in told(game, "Alice")[-1]
    game.day += 1
    rp_tokens = dict(game.player("Dave").tokens)
    apply_ops(game, players, {"op": "steal", "player": "Dave", "by": "Alice"},
              {"op": "count_tokens", "player": "Dave", "by": "Frank"})
    game.run_night_end_hooks()
    assert game.player("Dave").tokens == rp_tokens and "had no tokens" in told(game, "Alice")[-1]
    assert not any("Magpie" in t for t in told(game, "Dave"))
    assert told(game, "Frank")[-1].endswith("Your audit: Dave has 0 tokens in total.")  # a Roleplayer shows 0
    for night, victim in ((4, "Carol"), (5, "Erin")):
        game.day = night
        apply_ops(game, players, {"op": "steal", "player": victim, "by": "Alice"})
        game.run_night_end_hooks()
        assert ("Alice" in game.personal_winners) == (victim == "Erin")
    assert game.player("Alice").status[Status.LEFT]
    game.phase = "day"
    game.announce_dawn()
    assert any("was the Magpie and stole enough tokens" in e.text for e in game.events)


def test_a_magpie_leaving_at_the_end_of_the_night_still_counts_in_tonights_visit_results(game_factory):
    # rules R10: results draw from everyone alive when the night began; the Magpie leaves before the Insomniac's hook
    game, players = game_factory(["Magpie", "Medic", "Insomniac", "Grunt", "Vanilla Villager"])
    game.phase = "night"
    game.role_state["magpie_robbed"] = {"Alice": ["Dave", "Erin"]}
    mod = Moderator(game, ScriptedClient(), players, Model.HAIKU_5_5, "(rules)")
    mod.dispatch("apply_changes", {"changes": [{"op": "steal", "player": "Bob", "by": "Alice"},
                                               {"op": "stay_awake", "by": "Carol"}]})
    mod.dispatch("record_visits", {"visits": [["Alice", "Bob"]]})
    game.run_night_end_hooks()
    assert "Alice" in game.personal_winners and game.player("Alice").status[Status.LEFT]
    assert "Their roles: Magpie." in told(game, "Carol")[-1]
    assert game.death_record[-1] == f"Night {game.day}: Alice (Magpie) won and left the game"


def test_random_setups_include_a_magpie_only_with_enough_token_roles():
    import random

    import setups
    assert not setups.fits(["Magpie", "Vanilla Villager", "Vanilla Villager", "Grunt", "Sheriff", "Vigilante"])
    assert setups.fits(["Magpie", "Vanilla Villager", "Medic", "Grunt", "Sheriff", "Vigilante"])
    for seed in range(8):
        for draw in (setups.balanced_setup, setups.random_setup):
            roles = draw(13, random.Random(seed))
            assert "Magpie" not in roles or setups.fits(roles)
