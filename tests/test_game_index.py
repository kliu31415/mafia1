"""The game index (game_index.py): model tiers, per-game summaries, filters shared with stats.py, the page."""

import argparse

import game_index
import mafia
import stats
import sync_logs
from llm import Model, MockClient, TIERS, model_tier


def test_every_model_has_a_tier():
    assert not [m for m in Model if m.value not in TIERS]  # every model's MODELS entry has a tier
    assert set(TIERS.values()) <= {"frontier", "mid", "cheap"}
    assert model_tier("someone/new-model") == "unknown"


def test_mix_needs_two_thirds_of_the_seats():
    opus, sol, haiku, grok = (m.value for m in (Model.OPUS_5_5, Model.GPT_6_1_SOL, Model.HAIKU_5_5, Model.GROK_4_7))
    assert game_index.mix_of([opus, sol, haiku]) == (0.667, "frontier")
    assert game_index.mix_of([opus, haiku, haiku, haiku]) == (0.25, "cheap")
    assert game_index.mix_of([opus, haiku, grok]) == (0.333, "mixed")


def filters(*argv: str) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    game_index.add_filter_args(ap)
    return ap.parse_args(list(argv))


def test_filters():
    g = {"models": [Model.OPUS_5_5.value] * 2 + [Model.HAIKU_5_5.value], "frontier_share": 0.667, "mix": "frontier",
         "moderator": Model.OPUS_5_5.value, "roles": ["Sheriff", "Grunt"], "winner": "Yakuza", "n_players": 3,
         "date": "20261009"}
    passing = [(), ("--model", "opus-5.5", "--model", "haiku-5.5"), ("--min-frontier", "0.6"), ("--mix", "frontier"),
               ("--moderator", "opus-5.5"), ("--role", "Sheriff"), ("--winner", "yakuza"), ("--players", "3-12"),
               ("--since", "2026-10-09", "--until", "2026-10-09")]
    failing = [("--model", "gpt-6.1-sol"), ("--min-frontier", "0.7"), ("--mix", "cheap"), ("--role", "Medic"),
               ("--winner", "none"), ("--players", "4"), ("--since", "2026-10-10")]
    assert all(game_index.matches(g, filters(*a)) for a in passing)
    assert not any(game_index.matches(g, filters(*a)) for a in failing)


def test_index_lists_a_mock_game_and_stats_filters_it(tmp_path, monkeypatch):
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    roles = ["Vanilla Villager", "Vanilla Villager", "Sheriff", "Grunt", "Pharmacist"]
    path = mafia.play_game(MockClient(3), mafia.GameConfig([Model.HAIKU_5_5], Model.OPUS_5_5, roles, seed=3))
    assert game_index.load_summaries(tmp_path) == []  # mock games only on request
    [g] = game_index.load_summaries(tmp_path, include_mock=True)
    assert (g["game"], g["finished"], g["n_players"], g["mix"], g["frontier_share"]) == (path.stem, True, 5, "cheap", 0)
    assert g["moderator"] == Model.OPUS_5_5.value and g["links"]["log"] == path.stem + ".html"
    assert (tmp_path / game_index.CACHE).exists()
    assert game_index.load_summaries(tmp_path, include_mock=True) == [g]  # from the cache this time
    page = game_index.render([g], "now")
    assert path.stem in page and "</script>" in page.split("const DATA", 1)[1]
    games, _ = stats.load_games([path], include_mock=True, filters=filters("--mix", "cheap"))
    assert [x["game"] for x in games] == [path.stem]
    games, skipped = stats.load_games([path], include_mock=True, filters=filters("--min-frontier", "0.5"))
    assert games == [] and skipped["filtered out"] == 1


def test_the_index_is_never_synced(tmp_path):
    for name in (game_index.INDEX, game_index.CACHE, "game_1.jsonl"):
        (tmp_path / name).write_text("{}")
    assert [p.name for p in sorted(tmp_path.iterdir()) if sync_logs.syncable(p)] == ["game_1.jsonl"]
