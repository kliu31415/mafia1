"""Checkpoints, a program feature rather than a rule: the game state is saved next to the log at the
start of each day, so a game stopped by a crash, a sleeping laptop or an API error can continue with
`uv run mafia.py --resume logs/<game>.ckpt`. Resuming replays the day the checkpoint was taken on.
The log is cut back to where it was then, so it reads as one game, plus a "resume" record."""

import os
import pickle
from pathlib import Path
from typing import Any

from state import Game

CHECKPOINT_VERSION = 3  # 2: Game has pm_record and night_actions; 3: claim_record


def save(path: Path, game: Game, **extra: Any) -> None:
    """extra: whatever else resuming needs (play_game's arguments, costs so far, ...)."""
    data = pickle.dumps({"version": CHECKPOINT_VERSION, "game": game, "log_path": str(game.log.path),
                         "log_offsets": game.log.offsets(), **extra})
    tmp = path.with_suffix(".ckpt.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)  # atomic, so a crash while saving keeps the previous checkpoint


def load(path: Path) -> dict[str, Any]:
    data = pickle.loads(path.read_bytes())
    if data.get("version") != CHECKPOINT_VERSION:
        raise ValueError(f"{path} is checkpoint version {data.get('version')}; this code reads "
                         f"version {CHECKPOINT_VERSION}")
    data["log_path"] = path.with_suffix(".jsonl")  # the log next to it, wherever the checkpoint was copied
    return data
