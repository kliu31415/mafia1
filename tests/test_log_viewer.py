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
