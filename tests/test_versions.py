"""Catches a forgotten LOG_VERSION or CHECKPOINT_VERSION bump: tests/versions.json records the fields of every
log record that code writes with `.write("kind", ...)` (read from the source) and of the classes a checkpoint
pickles, together with the versions they belong to. When the fields change, bump the version they belong to (with
a comment saying what changed), then run `uv run pytest --update-versions`."""

import ast
import dataclasses
import json
from pathlib import Path

from checkpoint import CHECKPOINT_VERSION
from gamelog import LOG_VERSION
from state import Event, Game, Player

ROOT = Path(__file__).parent.parent
FILE = Path(__file__).parent / "versions.json"


def literal_keys(node: ast.AST) -> set[str]:
    """The string keys of every dict literal in a `**` argument, e.g. **({"a": 1} if x else {})."""
    return {k.value for d in ast.walk(node) if isinstance(d, ast.Dict)
            for k in d.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}


def log_fields() -> dict[str, list[str]]:
    """Record kind -> the fields any `.write("kind", ...)` call in the program gives it."""
    fields: dict[str, set[str]] = {}
    for path in sorted(ROOT.glob("*.py")) + sorted(ROOT.glob("roles/*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "write"
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                keys = fields.setdefault(node.args[0].value, set())
                for kw in node.keywords:
                    keys |= {kw.arg} if kw.arg else literal_keys(kw.value)
    return {kind: sorted(keys) for kind, keys in sorted(fields.items())}


def checkpoint_fields() -> dict[str, list[str]]:
    return {cls.__name__: [f.name for f in dataclasses.fields(cls)] for cls in (Game, Player, Event)}


def test_record_fields_match_their_versions(request):
    now = {"log_version": LOG_VERSION, "log": log_fields(),
           "checkpoint_version": CHECKPOINT_VERSION, "checkpoint": checkpoint_fields()}
    if request.config.getoption("--update-versions"):
        def show(v):  # one line per record kind or class, so a diff shows what changed
            if not isinstance(v, dict):
                return json.dumps(v)
            return "{\n" + ",\n".join(f"  {json.dumps(n)}: {json.dumps(f)}" for n, f in v.items()) + "\n }"
        lines = [f" {json.dumps(k)}: {show(v)}" for k, v in now.items()]
        FILE.write_text("{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8")
        return
    was = json.loads(FILE.read_text(encoding="utf-8"))
    for part, version in (("log", "log_version"), ("checkpoint", "checkpoint_version")):
        if now[part] != was[part] and now[version] == was[version]:
            raise AssertionError(f"{part} fields changed but {version} is still {now[version]}: bump it (gamelog.py "
                                 "LOG_VERSION / checkpoint.py CHECKPOINT_VERSION), then run "
                                 "`uv run pytest --update-versions`")
    assert now == was, "versions changed: run `uv run pytest --update-versions` to record the new fields"
