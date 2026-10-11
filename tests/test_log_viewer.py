"""The log viewer reads event categories, and still renders logs written before they existed."""

import json
import re

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
    alive = [line.split("</span>", 1)[1] for line in re.split(r"<div class='ev system'[^>]*><span class='badge'>",
                                                             html)[1:]]
    counts = [c.split(")")[0] for c in html.split("Alive (")[1:]]
    assert counts == ["4", "1", "0"]
    assert "Bob" in alive[0] and "Erin" in alive[0] and "Bob" not in alive[1] and "Dave" in alive[1]
    assert alive[2].startswith("nobody")
    assert "Night 1</summary><div class='ev system'>" not in html


def test_votes_table_player_filter_and_reasons(tmp_path):
    players = [{"name": n, "seat": i, "role": r, "model": "m"}
               for i, (n, r) in enumerate([("Bob", "Grunt"), ("Carol", "Puppeteer"), ("Dave", "Sheriff")])]
    records = [
        {"kind": "setup", "players": players, "katana": "Bob"},
        {"kind": "event", "visible_to": "all", "cat": "phase", "text": "Day 1 begins."},
        {"kind": "player_call", "player": "Carol", "model": "m", "task": "t", "output": {"reason": "Frame Dave."}},
        {"kind": "event", "visible_to": "all", "cat": "chat", "speaker": "Bob", "puppeteer": "Carol",
         "message": "Dave is Evil.", "text": "Bob (public): Dave is Evil."},
        {"kind": "event", "visible_to": "all", "cat": "claim", "speaker": "Dave", "claim": "null", "text": "x"},
        {"kind": "event", "visible_to": ["Dave"], "cat": "result", "message": "Bob is Evil.", "text": "x"},
        {"kind": "vote", "day": 1, "stage": "trial", "nominator": "Dave", "nominee": "Bob",
         "votes": {"Carol": False, "Dave": True}, "weights": {"Dave": 2}, "outcome": "executed"},
        {"kind": "player_feedback", "player": "Dave", "feedback": "A bug.", "step": "day"},
        {"kind": "moderator_flag", "issue": "Unclear rule."},
    ]
    path = tmp_path / "g.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    html = log_viewer.render_html(path).read_text(encoding="utf-8")
    # the puppeted message carries the Puppeteer's reason, and involves both of them
    assert "Frame " in html.split("(puppeted by")[1].split("<div class='ev")[0]
    assert "data-p='Bob Carol Dave'" in html  # names in the message
    assert "data-p='Bob Dave'><span class='badge'>Result" in html  # also whom a private result went to
    assert "[Claim]" not in html and ": null" not in html  # a written-out null claim is no claim
    assert html.count("<details class='votes'>") == 2  # the Day's table and the whole game's
    assert "✓×2" in html and "✗" in html
    assert "A bug." in html and "Unclear rule." in html


def test_night_card_and_roster(tmp_path):
    players = [{"name": "Bob", "seat": 0, "role": "Grunt", "model": "m"},
               {"name": "Dave", "seat": 1, "role": "Sheriff", "model": "m"},
               {"name": "Erin", "seat": 2, "role": "Roleplayer", "model": "m", "status": {"fake_role": "Lookout"}}]
    phase = {"kind": "event", "visible_to": "all", "cat": "phase"}
    records = [
        {"kind": "setup", "players": players, "katana": "Bob"},
        {**phase, "text": "Day 1 begins.", "day": 1, "phase": "day"},
        {"kind": "event", "visible_to": "all", "cat": "claim", "speaker": "Bob", "claim": "Sheriff", "text": "x"},
        {"kind": "event", "visible_to": "all", "cat": "claim", "speaker": "Erin", "claim": "Lookout.", "text": "x"},
        {**phase, "text": "Night 1 begins.", "day": 1, "phase": "night"},
        {"kind": "night_actions", "day": 1, "roles": {"Bob": "Grunt", "Dave": "Sheriff"},
         "actions": {"Bob": {"act": False}, "Dave": {"act": True, "target": "Bob"}}},
        {"kind": "death", "player": "Dave", "cause": "Katana", "day": 1, "phase": "night"},
        {"kind": "event", "visible_to": ["Dave"], "cat": "result", "message": "Bob is Evil.", "text": "x",
         "day": 1, "phase": "night"},
        {**phase, "text": "Day 2 begins.", "day": 2, "phase": "day"},
        {"kind": "night_check", "night": 1, "verdict": "correct", "issues": []},  # arrives after the night
    ]
    path = tmp_path / "g.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    html = log_viewer.render_html(path).read_text(encoding="utf-8")
    card = html.split("<details class='votes card'>")[1].split("</details>")[0]
    assert "Night 1 summary: 1 acted" in card and "night check: correct" in card and "Katana" in card
    assert "Bob is Evil." not in card and "is Evil." in card and "\0" not in html
    data = json.loads(html.split("id='roster-data'>")[1].split("</script>")[0])
    last = data["snaps"][-1]
    assert last["Dave"][0] is False and "Night 1: Katana" in last["Dave"][1]
    assert last["Bob"][2:] == ["Sheriff", "false"] and last["Erin"][3] == "true"  # a Roleplayer believes it
    assert html.count("<i class='snap'") == len(data["snaps"])


def test_claim_truth():
    assert log_viewer.claim_truth("Vanilla, no action", {"Vanilla Villager"}) == "true"
    assert log_viewer.claim_truth("I'm the sheriff", {"Grunt"}) == "false"
    assert log_viewer.claim_truth("no comment", {"Grunt"}) == ""


def test_jump_bar():
    phases = [{"id": "phase-0", "title": "Setup", "deaths": 0}, {"id": "phase-1", "title": "Night 1", "deaths": 2},
              {"id": "phase-2", "title": "Day 2", "deaths": 0},
              {"id": "phase-3", "title": "Post-game feedback: rules", "deaths": 0},
              {"id": "phase-4", "title": "Moderator strategy review", "deaths": 0},
              {"id": "phase-5", "title": "Game over", "deaths": 0}]
    links = re.findall(r"<a href='#(phase-\d)'[^>]*>([^<]*)(?:<span class='deaths'>(†*)</span>)?</a>",
                       log_viewer.jump_html(phases))
    assert links == [("phase-0", "Setup", ""), ("phase-1", "N1", "††"), ("phase-2", "D2", ""),
                     ("phase-3", "Post-game", ""), ("phase-5", "Game over", "")]


def test_secret_votes_show_who_voted_which_way():
    name = log_viewer.Namer({"Ann": "Sheriff", "Bob": "Grunt", "Cat": "Medic"})
    trial = {"stage": "trial", "nominee": "Bob", "outcome": "Guilty", "votes": {"Cat": True, "Ann": True},
             "weights": {"Cat": 2}, "reversed": ["Ann"]}
    text = re.sub("<[^>]+>", "", log_viewer.vote_split(trial, name, ["Ann", "Bob", "Cat"]))
    assert text == ("trial of Bob (Guilty) · Guilty (3): Ann (reversed by a Fixer), Cat (×2) · "
                    "Innocent (0): nobody")
