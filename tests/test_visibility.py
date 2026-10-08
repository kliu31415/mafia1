"""Hidden information must only reach the players allowed to see it. Each event's visible_to
decides what goes into a player's prompt (Game.history_for), so these tests check it per category."""

import json

import pytest

import mafia
from llm import MockClient, Model
from players import role_briefing
from roles import DEFAULT_SETUP, ROLES, Alignment
from state import Status


def mock_game_records(tmp_path, monkeypatch, seed: int) -> list[dict]:
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    path = mafia.play_game(MockClient(seed), [Model.HAIKU_5_5], Model.HAIKU_5_5, DEFAULT_SETUP, seed)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize("seed", range(5))
def test_private_events_reach_only_their_audience(tmp_path, monkeypatch, seed):
    records = mock_game_records(tmp_path, monkeypatch, seed)
    setup = next(r for r in records if r["kind"] == "setup")
    yakuza = {p["name"] for p in setup["players"] if ROLES[p["role"]].alignment is Alignment.EVIL}
    events = [r for r in records if r["kind"] in ("event", "notice")]
    seen = {r.get("cat") for r in events}
    assert {"pm", "yak", "chat"} <= seen, "the mock game should exercise private chat"
    for r in events:
        vis = r["visible_to"]
        match r.get("cat"):
            case "pm" if r["kind"] == "event":
                assert set(vis) <= {r["speaker"], r["to"]}, r
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
