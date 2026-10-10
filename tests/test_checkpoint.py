"""Checkpoints (checkpoint.py): a game stopped partway and resumed plays out like one that wasn't stopped."""

import json

import pytest

import mafia
from checkpoint import load
from llm import MockClient, Model, ModelSpec
from roles import DEFAULT_SETUP


def records(path):
    """The log's records without times, game ids and durations, which differ between runs, in a fixed order."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["kind"] in ("resume", "crash"):  # a resumed game keeps the crash that stopped it
            continue
        r.pop("t")
        r.pop("game_id", None)
        r.pop("duration_s", None)
        r.pop("latency_s", None)
        r.pop("errors", None)  # the resumed game counts its crash
        out.append(r)
    return sorted(out, key=lambda r: json.dumps(r, sort_keys=True))  # players are asked in parallel


@pytest.mark.parametrize("phase", ["day", "night"])
def test_a_resumed_game_matches_an_uninterrupted_one(tmp_path, monkeypatch, phase):
    seed = 1  # any seed whose mock game has a death and lasts 2+ days (the mock reads the rules text)
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path / "full")
    full = mafia.play_game(MockClient(seed), mafia.GameConfig([Model.HAIKU_5_5], Model.HAIKU_5_5, DEFAULT_SETUP, seed))
    assert not full.with_suffix(".ckpt").exists()  # deleted once the game finishes
    assert any(r["kind"] == "death" for r in records(full)) and json.loads(
        full.read_text(encoding="utf-8").splitlines()[-1])["days"] >= 2

    # Same game, stopped at the start of day 2 or night 2 (after that phase's checkpoint).
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path / "stopped")
    real_run = getattr(mafia, f"run_{phase}")

    def crash_on_2(game, *args):
        if game.day == 2:
            raise RuntimeError("laptop went to sleep")
        real_run(game, *args)
    monkeypatch.setattr(mafia, f"run_{phase}", crash_on_2)
    with pytest.raises(RuntimeError):
        mafia.play_game(MockClient(seed), mafia.GameConfig([Model.HAIKU_5_5], Model.HAIKU_5_5, DEFAULT_SETUP, seed))
    [ckpt_path] = (tmp_path / "stopped").glob("*.ckpt")
    ckpt = load(ckpt_path)
    assert ckpt["game"].day == 2 and ckpt["at"] == phase
    crash = json.loads(ckpt_path.with_suffix(".jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert crash["kind"] == "crash" and crash["alert"] and "laptop went to sleep" in crash["error"]
    assert f"--resume {ckpt_path}" in crash["error"]
    assert "laptop went to sleep" in ckpt_path.with_suffix(".html").read_text(encoding="utf-8")  # rendered anyway

    monkeypatch.setattr(mafia, f"run_{phase}", real_run)
    resumed = mafia.play_game(MockClient(seed), mafia.GameConfig.from_checkpoint(ckpt), resume=ckpt)
    assert resumed == ckpt_path.with_suffix(".jsonl")
    assert records(resumed) == records(full)
    resumed_records = [json.loads(line) for line in resumed.read_text(encoding="utf-8").splitlines()]
    assert [r["kind"] for r in resumed_records].count("crash") == 1
    assert resumed_records[-1]["errors"] == {"crash": 1}
    text = resumed.with_suffix(".txt").read_text(encoding="utf-8")
    assert text.count("===== DAY 2 =====") == 1 and f"Resumed from the checkpoint at the start of {phase} 2" in text
    assert not ckpt_path.exists()


def test_no_checkpoint_without_the_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    monkeypatch.setattr(mafia, "run_night", lambda *args: (_ for _ in ()).throw(RuntimeError("stop")))
    with pytest.raises(RuntimeError):
        mafia.play_game(MockClient(1),
            mafia.GameConfig([Model.HAIKU_5_5], Model.HAIKU_5_5, DEFAULT_SETUP, 1), checkpoint=False)
    assert not list(tmp_path.glob("*.ckpt"))


def test_checkpoints_from_before_game_config_still_load():
    """Checkpoints saved before GameConfig kept play_game's keyword arguments as "play_args"."""
    old = {"models": [Model.HAIKU_5_5], "moderator_model": Model.OPUS_5_5, "roles": DEFAULT_SETUP, "seed": 4,
           "debrief": True, "flag_issues": True, "feedback_field": True, "review": True, "lessons": True,
           "max_days": None, "check_nights": True, "tips": None, "tips_for": "all", "player_tips": None,
           "update_tips": None, "setup": None, "moderator_fallback": None}
    config = mafia.GameConfig.from_checkpoint({"play_args": old})
    assert config.moderator == ModelSpec(Model.OPUS_5_5) and config.models == [ModelSpec(Model.HAIKU_5_5)]
    assert config.seed == 4 and config.lessons and config.player_tips == []
