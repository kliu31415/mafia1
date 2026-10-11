"""Cross-game statistics (stats.py) and random setups (setups.py)."""

import json
import random
from pathlib import Path
from collections import Counter

import pytest

import mafia
import stats
from tests.conftest import ScriptedClient
from llm import MockClient, Model, text_of
from roles import ROLES, Alignment
import role_power
import setups
from setups import balanced_setup, parse_setup, players_for, random_setup, setup_note


def write_log(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


ROLES_BY_NAME = {"Alice": "Sheriff", "Bob": "Medic", "Carol": "Vigilante", "Dave": "Vanilla Villager",
                 "Erin": "Grunt", "Frank": "Pharmacist", "Grace": "Jester"}


def game_records(winning_faction="Village", **extra):
    players = [{"name": n, "seat": i, "model": Model.HAIKU_5_5.value, "start_role": r, "final_role": r,
                "faction": stats.faction_of(r), "alive": True, "left": False,
                "won": stats.faction_of(r) == winning_faction, "tips": False, "death": None}
               for i, (n, r) in enumerate(ROLES_BY_NAME.items())]
    return [
        {"kind": "setup", "players": [{"name": p["name"], "role": p["start_role"]} for p in players],
         "log_version": 16, "game_id": "game_20261009_120000_1", "settings": {"mock": False, **extra}},
        # Alice (Village) nominates Erin (Yakuza): good. Frank (Yakuza) votes No: good for the Yakuza.
        {"kind": "vote", "day": 1, "stage": "nomination", "nominator": "Alice", "nominee": "Erin",
         "votes": {"Alice": True, "Bob": True, "Frank": False, "Erin": False, "Grace": True}, "outcome": "passed"},
        # Bob Guilty (good), Dave Innocent (bad), Frank Innocent (good, Yakuza), Grace not scored (Neutral).
        {"kind": "vote", "day": 1, "stage": "trial", "nominator": "Alice", "nominee": "Erin",
         "votes": {"Bob": True, "Dave": False, "Frank": False, "Erin": False, "Grace": True}, "outcome": "Innocent"},
        # Votes on the Jester: Guilty is bad for the Village.
        {"kind": "vote", "day": 2, "stage": "trial", "nominator": "Bob", "nominee": "Grace",
         "votes": {"Carol": True}, "outcome": "Innocent", "prosecuted": True},
        {"kind": "katana", "day": 1, "result": {"attack": "Alice", "holder": "Erin"}},
        {"kind": "night_actions", "day": 1, "roles": {n: ROLES_BY_NAME[n] for n in ("Alice", "Bob", "Carol", "Erin")},
         "actions": {"Alice": {"act": True, "target": "Frank"}, "Bob": {"act": True, "target": "Alice"},
                     "Carol": {"act": True, "target": "Dave"},
                     "Erin": {"act": False, "katana_vote_target": "Alice"}}},
        {"kind": "result", "winners": [p["name"] for p in players if p["won"]], "days": 2,
         "cost": {"x": 0.5}, "end_reason": "win", "winning_faction": winning_faction, "duration_s": 600,
         "players": players},
    ]


def test_decisions_are_scored_from_each_faction_s_point_of_view(tmp_path):
    g = stats.load_game(write_log(tmp_path / "game_a.jsonl", game_records()))
    assert g is not None
    got = {(d["player"], d["kind"], d["day"]): d["good"] for d in g["decisions"] if d["kind"] != "deceived_voter"}
    assert got == {
        ("Alice", "nomination", 1): True,
        ("Bob", "nomination_vote", 1): True, ("Frank", "nomination_vote", 1): True,
        ("Bob", "trial_vote", 1): True, ("Dave", "trial_vote", 1): False, ("Frank", "trial_vote", 1): True,
        ("Carol", "trial_vote", 2): False,  # Guilty on the Jester (a prosecution: no nomination scored)
        ("Alice", "sheriff_check", 1): True, ("Bob", "medic_protect", 1): True,
        ("Carol", "vigilante_shot", 1): False, ("Erin", "katana_target", 1): True,
    }
    deceived = {d["target"]: d["good"] for d in g["decisions"] if d["kind"] == "deceived_voter"}
    assert deceived == {"Bob": False, "Dave": True}  # Erin on trial: Bob voted Guilty, Dave Innocent


def test_report_counts_wins_and_skips_unfinished_and_mock_games(tmp_path):
    write_log(tmp_path / "game_a.jsonl", game_records("Village"))
    write_log(tmp_path / "game_b.jsonl", game_records("Yakuza"))
    write_log(tmp_path / "game_c.jsonl", game_records()[:-1])  # no result: stopped
    write_log(tmp_path / "mock_d.jsonl", game_records(mock=True))
    games, skipped = stats.load_games([tmp_path])
    assert len(games) == 2 and skipped == {"unfinished": 1, "mock": 1, "filtered out": 0}
    text = stats.report(games, skipped)
    assert "Village                            50% [9-91] n=2" in text
    assert "Village: medic_protect" in text and "Yakuza: katana_target" in text
    paths = stats.write_csv(games, tmp_path / "csv")
    assert [p.name for p in paths] == ["games.csv", "players.csv", "decisions.csv"]
    assert len((tmp_path / "csv" / "players.csv").read_text().splitlines()) == 1 + 2 * len(ROLES_BY_NAME)


def test_wilson_interval():
    assert stats.wilson(0, 0) == (0.0, 1.0)
    lo, hi = stats.wilson(5, 10)
    assert 0.23 < lo < 0.24 and 0.76 < hi < 0.77
    assert stats.rate(0, 0) == "-"


def test_random_setups_follow_their_proportions():
    for n in range(5, 17):
        for seed in range(50):
            roles = random_setup(n, random.Random(seed))
            assert len(roles) == n and all(r in ROLES for r in roles)
            yakuza = [r for r in roles if ROLES[r].alignment is Alignment.EVIL]
            assert len(yakuza) == max(1, round(n * 0.3))
            village = [r for r in roles if ROLES[r].alignment is Alignment.GOOD]
            assert len(village) > len(yakuza)  # rules R2: Village outnumbers Yakuza
            assert any(ROLES[r].category == "Investigative" for r in village)
            assert sum(ROLES[r].category == "Outsider" for r in village) <= 1
            counts = Counter(r for r in roles if r != "Vanilla Villager")
            assert max(counts.values()) == 1
    assert random_setup(10, random.Random(3)) == random_setup(10, random.Random(3))
    tested = {r for seed in range(100) for r in random_setup(10, random.Random(seed), "tested")}
    assert tested and all(ROLES[r].tested for r in tested)


def test_parse_setup():
    assert parse_setup("Sheriff,Grunt") is None
    assert parse_setup("random:8") == ("classic", 8) and parse_setup("standard") == ("standard", None)
    assert players_for("standard", None, 5) == 13 and 11 <= players_for("classic", None, 5) <= 15
    assert players_for("standard", 9, 5) == 9
    for bad in ("random:x", "standard:3"):
        with pytest.raises(ValueError):
            parse_setup(bad)


def test_players_are_told_how_the_roles_were_chosen_but_not_the_list():
    drawn = setup_note({"kind": "random", "name": "classic", "players": 12}, random_setup(12, random.Random(1)))
    assert "12 players" in drawn and "classic setup: about 30% of the players are Yakuza" in drawn
    hand = setup_note(None, ["Sheriff", "Medic", "Grunt", "Fixer", "Jester", "Vanilla Villager"])
    assert "picked by hand" in hand and "1 to 3 Yakuza, 0 to 2 Neutrals" in hand and "Sheriff" not in hand


def test_a_random_setup_game_is_logged_and_counted(tmp_path, monkeypatch):
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    roles = random_setup(7, random.Random(1), "tested")
    setup = {"kind": "random", "players": 7, "pool": "tested"}
    path = mafia.play_game(ScriptedClient(),
        mafia.GameConfig([Model.HAIKU_5_5], Model.HAIKU_5_5, roles, seed=1, setup=setup))
    first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert first["settings"]["setup"] == setup and first["settings"]["roles"] == roles
    g = stats.load_game(path)
    assert g is not None and g["setup"] == "random" and g["roles"] == sorted(roles)


def test_standard_setups_are_mostly_balanced_and_follow_their_shape(monkeypatch):
    monkeypatch.setattr(setups, "LOG_DIR", Path("/nonexistent"))  # no past games: the same draw everywhere
    monkeypatch.setattr(role_power, "FILE", Path("/nonexistent"))  # the priors, not the latest fit
    chances: list[float] = []
    yakuza_counts: Counter = Counter()
    repeats = 0  # setups that repeat a role other than the Vanilla Villager
    for seed in range(100):
        roles = balanced_setup(13, random.Random(seed))
        assert len(roles) == 13 and all(r in ROLES for r in roles)
        by = Counter(ROLES[r].alignment for r in roles)
        yakuza_counts[by[Alignment.EVIL]] += 1
        assert 2 <= by[Alignment.EVIL] <= 4 and by[Alignment.NEUTRAL] <= 3
        village = [r for r in roles if ROLES[r].alignment is Alignment.GOOD]
        assert sum(ROLES[r].category not in ("Outsider",) for r in village) >= 5
        assert any(ROLES[r].category == "Investigative" for r in village)
        assert sum(ROLES[r].category == "Outsider" for r in village) <= 2
        assert roles.count("Vanilla Villager") <= 2 and all(roles.count(r) == 1 for r in roles if ROLES[r].unique)
        others = [r for r in roles if r != "Vanilla Villager"]
        repeats += len(others) > len(set(others))
        chances.append(role_power.village_chance(roles))
    assert yakuza_counts.most_common(1)[0][0] == 3
    assert 5 <= repeats <= 95  # roles may repeat (Kevin, Oct 11 2026), but most draws are still varied
    assert sum(0.4 <= c <= 0.6 for c in chances) >= 80  # most setups are roughly balanced


def test_every_role_has_a_power():
    assert set(role_power.PRIOR) == set(ROLES)


def test_role_powers_are_refit_from_results_towards_the_priors(tmp_path):
    base = ["Sheriff", "Medic", "Vanilla Villager", "Vanilla Villager", "Grunt"]
    data = [(base + ["Jester"], 0, 1.0)] * 12 + [(base + ["Vulture"], 1, 1.0)] * 12
    offset, power = role_power.fit(data)
    assert power["Jester"] < role_power.PRIOR["Jester"] - 0.1 and power["Vulture"] > role_power.PRIOR["Vulture"] + 0.1
    assert power["Seer"] == role_power.PRIOR["Seer"]  # never seen: stays at its prior
    path = tmp_path / "role_power.json"
    role_power.update(tmp_path, path)  # no games: the priors
    assert role_power.load(path) == (role_power.OFFSET_PRIOR, role_power.PRIOR)
    assert "| Sheriff | Good | +0.55 | +0.55 | 0 |" in path.with_suffix(".md").read_text(encoding="utf-8")


def test_players_get_the_setup_note_and_their_tips(tmp_path, monkeypatch):
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    systems: list[str] = []
    chat = MockClient.chat

    def spy(self, model, messages, **kw):
        systems.append(" ".join(str(text_of(m.get("content"))) for m in messages if m.get("role") == "system"))
        return chat(self, model, messages, **kw)
    monkeypatch.setattr(MockClient, "chat", spy)
    tips = tmp_path / "tips.md"
    tips.write_text("# Tips\n\n## Everyone\n- A tip only this test writes.\n", encoding="utf-8")
    roles = balanced_setup(13, random.Random(1), yakuza=3)
    mafia.play_game(MockClient(1), mafia.GameConfig(
        [Model.HAIKU_5_5], Model.HAIKU_5_5, roles, 1, tips=tips, max_days=1, debrief=False, lessons=False,
        review=False, check_nights=False, setup={"kind": "random", "name": "standard", "players": 13, "yakuza": 3}),
        checkpoint=False)
    assert all("Its roles were drawn at random by the standard setup" in s for s in systems)
    # The log keeps what they were told: the setup note and the whole rules text their prompts start with.
    log = next(tmp_path.glob("mock_*.jsonl"))
    briefing = next(r for r in map(json.loads, log.read_text(encoding="utf-8").splitlines()) if r["kind"] == "briefing")
    assert "drawn at random by the standard setup" in briefing["setup_note"]
    assert all(briefing["rules"] in s for s in systems if "Its roles were drawn" in s)
    assert set(briefing["players"]) == set(mafia.PLAYER_NAMES[:13])
    assert "[Setup note to players] Setup (the role list itself is secret)." in log.with_suffix(".txt").read_text(
        encoding="utf-8")
    assert any("A tip only this test writes." in s for s in systems)
    assert not any(", ".join(roles) in s for s in systems)
