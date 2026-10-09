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
    path = mafia.play_game(MockClient(seed), [Model.HAIKU_5_5], Model.HAIKU_5_5, DEFAULT_SETUP, seed)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_the_mock_games_exercise_private_chat(tmp_path, monkeypatch):
    # Mock answers depend on the prompt text, so any single seed may happen to skip a category
    # (e.g. after a rules edit); between them, the seeds below must cover private chat.
    seen = {r.get("cat") for seed in range(5) for r in mock_game_records(tmp_path / str(seed), monkeypatch, seed)}
    assert {"pm", "yak", "chat"} <= seen


@pytest.mark.parametrize("seed", range(5))
def test_private_events_reach_only_their_audience(tmp_path, monkeypatch, seed):
    records = mock_game_records(tmp_path, monkeypatch, seed)
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
    # Everyone else learns only that a private message was sent, never its contents.
    notices = [r for r in events if r["kind"] == "notice"]
    assert notices and all(r["text"].endswith("a private message.") for r in notices)


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


def test_mock_games_replay_from_their_seed(tmp_path, monkeypatch):
    """Players are asked in parallel threads, so this fails if answers depend on call order."""
    def events(sub):
        (tmp_path / sub).mkdir()
        recs = mock_game_records(tmp_path / sub, monkeypatch, seed=77)
        return [r["text"] for r in recs if r["kind"] == "event"]
    assert events("a") == events("b")


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
