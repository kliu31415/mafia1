"""Checkpoints, a program feature rather than a rule: the game state is saved next to the log at the
start of each day and each night ("at" in the checkpoint), so a game stopped by a crash, a sleeping laptop
or an API error can continue with `uv run mafia.py --resume logs/<game>.ckpt`. Resuming replays the day or
night the checkpoint was taken at.
The log is cut back to where it was then, so it reads as one game, plus a "resume" record."""

import dataclasses
import os
import pickle
from pathlib import Path
from typing import Any

from state import Game

CHECKPOINT_VERSION = 5  # 2: Game has pm_record and night_actions; 3: claim_record; 4: night_visits; 5: votes


def save(path: Path, game: Game, **extra: Any) -> None:
    """extra: whatever else resuming needs (play_game's arguments, costs so far, ...)."""
    data = pickle.dumps({"version": CHECKPOINT_VERSION, "game": game, "log_path": str(game.log.path),
                         "log_offsets": game.log.offsets(), **extra})
    tmp = path.with_suffix(".ckpt.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)  # atomic, so a crash while saving keeps the previous checkpoint


def load(path: Path, force: bool = False) -> dict[str, Any]:
    """force: load a checkpoint from another CHECKPOINT_VERSION anyway (--force-resume): fields the code has
    added since get their defaults, and data["forced"] says what didn't match, for a warning. Usually fine after
    small changes; a field whose meaning changed can still make the game go wrong."""
    data = pickle.loads(path.read_bytes())
    if data.get("version") != CHECKPOINT_VERSION:
        mismatch = (f"{path} is checkpoint version {data.get('version')}; this code reads version "
                    f"{CHECKPOINT_VERSION}")
        if not force:
            raise ValueError(f"{mismatch} (--force-resume tries anyway)")
        added = fill_missing_fields([data["game"], *data["game"].players])
        data["forced"] = mismatch + (f"; fields given their defaults: {', '.join(added)}" if added else "")
    data["log_path"] = path.with_suffix(".jsonl")  # the log next to it, wherever the checkpoint was copied
    return data


def fill_missing_fields(objects: list[Any]) -> list[str]:
    """Sets each dataclass field with a default that an unpickled object lacks (one added after it was saved) to
    that default; returns them as Class.field."""
    added = set()
    for obj in objects:
        for f in dataclasses.fields(obj):
            if f.name in vars(obj):
                continue
            if f.default is not dataclasses.MISSING:
                setattr(obj, f.name, f.default)
            elif f.default_factory is not dataclasses.MISSING:
                setattr(obj, f.name, f.default_factory())
            else:  # set on resume (Game.log, never pickled)
                continue
            added.add(f"{type(obj).__name__}.{f.name}")
    return sorted(added)
