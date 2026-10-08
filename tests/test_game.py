"""Whole-game behavior: win checks, game-ending safeguards and model settings."""

import pytest

import mafia
from llm import Model
from tests.conftest import ScriptedClient


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


def test_day_limit_ends_the_game_with_no_winner(tmp_path, monkeypatch):
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    monkeypatch.setattr(mafia, "STALL_LIMIT", 100)  # so the stall rule doesn't end it first
    roles = ["Vanilla Villager", "Vanilla Villager", "Vanilla Villager", "Grunt", "Grunt"]
    path = mafia.play_game(ScriptedClient(), [Model.HAIKU_5_5], Model.HAIKU_5_5, roles, seed=1, max_days=2)
    text = path.with_suffix(".txt").read_text(encoding="utf-8")
    assert "limit of 2 days" in text and "Winners: nobody" in text


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


def test_rule_citations_in_code_exist_in_the_rules():
    """Code cites rules_1.txt paragraphs by label (e.g. "rules R8"); a citation to a label that no
    longer exists would silently point nowhere."""
    import re
    from pathlib import Path
    root = Path(mafia.__file__).parent
    labels = set(re.findall(r"^(R\d+) \(", (root / "rules_1.txt").read_text(encoding="utf-8"), re.M))
    assert labels, "the rules lost their R labels"
    for path in [*root.glob("*.py"), *root.glob("roles/*.py")]:
        cited = set(re.findall(r"\b(R\d{1,2})\b", path.read_text(encoding="utf-8")))
        assert cited <= labels, f"{path.name} cites {sorted(cited - labels)}, which aren't in rules_1.txt"
