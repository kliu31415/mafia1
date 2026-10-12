"""Hidden information must only reach the players allowed to see it. Each event's visible_to
decides what goes into a player's prompt (Game.history_for), so these tests check it per category."""

import json

import pytest

import mafia
from llm import MockClient, Model
from players import role_briefing
from roles import DEFAULT_SETUP, ROLES, Alignment, Status


def mock_game_records(tmp_path, monkeypatch, seed: int) -> list[dict]:
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    path = mafia.play_game(MockClient(seed), mafia.GameConfig([Model.HAIKU_5_5], Model.HAIKU_5_5, DEFAULT_SETUP, seed))
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture(scope="module")
def mock_games(tmp_path_factory):
    """seed -> the records of a mock game with that seed, each game played once for the tests below."""
    games: dict[int, list[dict]] = {}

    def records(seed: int) -> list[dict]:
        if seed not in games:
            with pytest.MonkeyPatch.context() as monkeypatch:
                games[seed] = mock_game_records(tmp_path_factory.mktemp(f"seed{seed}"), monkeypatch, seed)
        return games[seed]
    return records


def test_the_mock_games_exercise_private_chat(mock_games):
    # Mock answers depend on the prompt text, so any single seed may happen to skip a category
    # (e.g. after a rules edit); between them, the seeds below must cover private chat.
    seen = {r.get("cat") for seed in range(5) for r in mock_games(seed)}
    assert {"pm", "yak", "chat"} <= seen


@pytest.mark.parametrize("seed", range(5))
def test_private_events_reach_only_their_audience(mock_games, seed):
    records = mock_games(seed)
    setup = next(r for r in records if r["kind"] == "setup")
    yakuza = {p["name"] for p in setup["players"] if ROLES[p["role"]].alignment is Alignment.EVIL}
    wiretaps = {p["name"] for p in setup["players"] if p["role"] == "Wiretap"}
    events = [r for r in records if r["kind"] in ("event", "notice")]
    for r in events:
        vis = r["visible_to"]
        match r.get("cat"):
            case "pm" if r["kind"] == "event":
                assert set(vis) <= {r["speaker"], r["to"]} | wiretaps, r
            case "yak":
                assert set(vis) <= yakuza, r
            case "result":
                assert vis != "all", r
    # Everyone else learns only that a private message was sent, never its contents; with secret votes (the
    # default), each voter alone is reminded of their own vote.
    notices = [r for r in events if r["kind"] == "notice"]
    assert notices and all(r["text"].endswith("a private message.") or
                           (r["cat"] == "vote" and len(r["visible_to"]) == 1 and r["text"].startswith("(Only you"))
                           for r in notices)
    public_votes = [r["text"] for r in events if r.get("cat") == "vote" and r["visible_to"] == "all"]
    assert public_votes and not any(" - " in v for v in public_votes), "secret votes must not name voters"


def test_briefings_reveal_only_what_a_role_knows(game_factory):
    roles = ["Sheriff", "Medic", "Jester", "Grunt", "Pharmacist", "Executioner"]
    game, _ = game_factory(roles)
    game.player("Frank").status[Status.TARGET] = "Alice"
    for p in game.players:
        briefing = role_briefing(game, p)
        for q in game.players:
            if q is p:
                continue
            teammates = p.info.alignment is Alignment.EVIL and q.info.alignment is Alignment.EVIL
            assert (f"{q.name} ({q.role})" in briefing) == teammates, (p.name, briefing)


def test_mock_games_replay_from_their_seed(mock_games, tmp_path, monkeypatch):
    """Players are asked in parallel threads, so this fails if answers depend on call order."""
    def events(recs):
        return [r["text"] for r in recs if r["kind"] == "event"]
    assert events(mock_games(0)) == events(mock_game_records(tmp_path, monkeypatch, seed=0))


def test_night_history_shows_only_your_own_actions_and_results(game_factory):
    from events import RESULT
    from feedback import night_replay
    from players import player_messages
    game, _ = game_factory(["Sheriff", "Vanilla Villager", "Grunt"])
    game.night_actions[1] = {"Alice": {"act": True, "target": "Carol"},
                             "Carol": {"act": False, "katana_vote_holder": "Carol", "katana_vote_target": "Bob"}}
    game.phase = "night"
    game.emit("Moderator (private): Carol is Evil.", ["Alice"], cat=RESULT, message="Carol is Evil.")
    alice = player_messages(game, game.player("Alice"), "(rules)", "task")[1]["content"]
    carol = player_messages(game, game.player("Carol"), "(rules)", "task")[1]["content"]
    bob = player_messages(game, game.player("Bob"), "(rules)", "task")[1]["content"]
    assert "Night 1: you submitted target Carol" in alice and "result: Carol is Evil." in alice
    assert "Katana vote: Carol holds, attacks Bob" in carol and "Carol is Evil" not in carol
    assert "Your night history" not in bob  # Bob had no night action and got no results
    replay = night_replay(game)  # after the game, everything is revealed
    assert "Alice (Sheriff): target Carol" in replay and "Result to Alice: Carol is Evil." in replay


def test_night_history_shows_the_target_chosen_not_the_one_a_swap_moved_it_to(game_factory):
    # game_20261010_053523_23052 night 3: Grace's history said Carol, her result Alice, so she noticed the swap
    from players import player_messages
    game, _ = game_factory(["Medic", "Smuggler", "Vanilla Villager", "Grunt"])
    game.night_actions[1] = {"Alice": {"act": True, "target": "Carol", "chosen_target": "Bob"},
                             "Bob": {"act": True, "target": "Bob", "second_target": "Carol",
                                     "katana_vote_holder": "Bob", "katana_vote_target": "Bob",
                                     "chosen_katana_vote_target": "Carol"}}
    game.phase = "night"
    alice = player_messages(game, game.player("Alice"), "(rules)", "task")[1]["content"]
    bob = player_messages(game, game.player("Bob"), "(rules)", "task")[1]["content"]
    line = next(x for x in alice.splitlines() if x.startswith("- Night 1: you submitted"))
    assert "target Bob" in line and "Carol" not in line
    assert "attacks Carol" in bob


def test_a_confidants_hidden_message_reaches_only_its_recipient_and_listeners(game_factory):
    # rules R24 (Kevin, Oct 12 2026): no "A sent B a private message" line and no ledger count; a Wiretap still
    # hears it, marked hidden; one hidden message a game.
    from day import chat_turn
    from tests.conftest import ScriptedClient
    from traits import CONFIDANT_USED

    def decide(name, task, schema):
        if name == "Alice" and "private_messages" in schema["properties"]:
            return {"private_messages": [{"to": "Bob", "text": "I'm the Sheriff."},
                                         {"to": "Carol", "text": "Hi."}],
                    "hidden_pm": "Bob" if "hidden_pm" in schema["properties"] else None}
        return None
    game, players = game_factory(["Vanilla Villager", "Vanilla Villager", "Vanilla Villager", "Wiretap", "Grunt"],
                                 ScriptedClient(decide))
    alice = game.player("Alice")
    alice.traits = ["Confidant"]
    alice.speaking_budget = 8.0
    chat_turn(game, players, alice, rnd=1, can_nominate=False)
    hidden = next(e for e in game.events if "I'm the Sheriff." in e.text)
    assert "hidden" in hidden.text and hidden.visible_to == {"Alice", "Bob", "Dave"}  # Dave: the Wiretap
    assert not any("sent Bob" in e.text for e in game.events)
    assert any("Alice sent Carol a private message." == e.text for e in game.events)  # not hidden
    assert game.pm_record[game.day] == {"Alice -> Carol": 1}
    assert game.role_state[CONFIDANT_USED] == ["Alice"]
    chat_turn(game, players, alice, rnd=2, can_nominate=False)  # used up: the field isn't offered again
    assert any("Alice sent Bob a private message." == e.text for e in game.events)
    assert game.pm_record[game.day] == {"Alice -> Carol": 2, "Alice -> Bob": 1}
