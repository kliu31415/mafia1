"""The log viewer reads event categories, and still renders logs written before they existed."""

import json

import log_viewer


def test_categorized_events():
    pm = {"kind": "event", "text": "anything", "visible_to": ["Bob", "Carol"], "cat": "pm",
          "speaker": "Bob", "to": "Carol", "message": "psst"}
    assert log_viewer.classify(pm) == ("pm", "PM", "Bob → Carol: psst")
    # Wording that the old text-guessing would have misread doesn't matter any more.
    death = {"kind": "event", "text": "Bob nominated nobody; votes everywhere", "visible_to": "all", "cat": "death"}
    assert log_viewer.classify(death)[0] == "death"


def test_legacy_logs_still_render(tmp_path):
    records = [
        {"kind": "setup", "players": [{"name": "Bob", "seat": 0, "role": "Grunt", "model": "m"}], "katana": "Bob"},
        {"kind": "event", "text": "Day 1 begins.", "visible_to": "all"},
        {"kind": "event", "text": "Bob (public): hello", "visible_to": "all"},
        {"kind": "result", "winners": ["Bob"], "cost": {}},
    ]
    path = tmp_path / "old.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    html = log_viewer.render_html(path).read_text(encoding="utf-8")
    assert "class='ev chat'" in html and "Day 1" in html


def test_alive_list_at_each_day(tmp_path):
    players = [{"name": n, "seat": i, "role": "Vanilla Villager", "model": "m"}
               for i, n in enumerate(["Bob", "Carol", "Dave", "Erin"])]
    day = {"kind": "event", "visible_to": "all", "cat": "phase"}
    records = [
        {"kind": "setup", "players": players, "katana": None},
        {**day, "text": "Day 1 begins."},
        {"kind": "death", "player": "Carol"},
        {"kind": "left", "player": "Erin"},
        {**day, "text": "Night 1 begins."},
        {"kind": "death", "player": "Bob"},  # a night death: logged before the Day starts, revealed after
        {**day, "text": "Day 2 begins."},
        # LOG_VERSION 33 and earlier: a winning Executioner left with only this event
        {"kind": "event", "visible_to": "all", "cat": "death",
         "text": "Dave was the Executioner, whose target was X. They win and leave the game."},
        {**day, "text": "Day 3 begins."},
    ]
    path = tmp_path / "g.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    html = log_viewer.render_html(path).read_text(encoding="utf-8")
    alive = [line.split("</span>", 1)[1] for line in html.split("<div class='ev system'><span class='badge'>")[1:]]
    counts = [c.split(")")[0] for c in html.split("Alive (")[1:]]
    assert counts == ["4", "1", "0"]
    assert "Bob" in alive[0] and "Erin" in alive[0] and "Bob" not in alive[1] and "Dave" in alive[1]
    assert alive[2].startswith("nobody")
    assert "Night 1</summary><div class='ev system'>" not in html
