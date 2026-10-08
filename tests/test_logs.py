"""Game logs: the records analysis relies on."""

import mafia
from llm import Model
from tests.conftest import ScriptedClient, votes


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
