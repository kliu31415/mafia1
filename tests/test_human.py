"""Human seats (human.py): a person's page answers Players.ask for their seat, and sees only what their seat may."""

import json
import threading
import time
import urllib.error
import urllib.request

import human
import mafia
from human import HumanSeats
from llm import MockClient, Model, ModelSpec
from players import VOTE_SCHEMA


def call(url: str, body: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, json.loads(raw) if e.headers.get_content_type() == "application/json" else {"text": raw}


def play_as_human(base: str, seen: dict, stop: threading.Event) -> None:
    """A scripted person: talks on day turns, votes Guilty, skips everything else, reports one bug."""
    since = 0
    reported = False
    while not stop.is_set():
        try:
            status, s = call(f"{base}/state?since={since}")
        except OSError:  # the server stops once the finished game has been shown
            if seen["over"]:
                return
            raise
        assert status == 200
        seen["events"] += s["events"]
        since = s["n_events"]
        seen["state"] = s
        if not reported:
            assert call(f"{base}/feedback", {"text": "The vote buttons are too small."})[0] == 200
            reported = True
        q = s["question"]
        if q:
            seen["steps"].append(q["step"])
            if q["step"] == "day_turn":
                others = [p["name"] for p in s["players"] if p["alive"] and not p["you"]]
                # a name that isn't a player breaks the schema, so the page gets the errors and asks again
                bad = call(f"{base}/answer", {"id": q["id"], "answer": {
                    "private_messages": [{"to": "Nobody", "text": "hi"}]}})
                assert bad[0] == 400 and bad[1]["errors"]
                answer = {"public_message": "I am a plain villager.", "notepad": "suspect everyone",
                          "private_messages": [{"to": others[0], "text": "trust me"}]}
                assert call(f"{base}/answer", {"id": q["id"], "answer": answer}) == (200, {"errors": []})
            elif set(q["schema"]) == {"vote"}:
                call(f"{base}/answer", {"id": q["id"], "answer": {"vote": True}})
            else:
                call(f"{base}/answer", {"id": q["id"], "skip": True})
        if s["winners"] is not None and not q:
            seen["over"] = True
        time.sleep(0.02)


def test_a_human_seat_plays_a_mock_game_through_its_page(tmp_path, monkeypatch):
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    monkeypatch.setattr(human, "LINGER_GRACE_S", 0.2)
    started: list[HumanSeats] = []
    real_start = HumanSeats.start

    def start(self, host="127.0.0.1", port=0):
        links = real_start(self, host, 0)
        started.append(self)
        return links
    monkeypatch.setattr(HumanSeats, "start", start)
    seen: dict = {"events": [], "steps": [], "over": False}
    stop = threading.Event()
    bot: list[threading.Thread] = []

    def watch() -> None:  # the page can only be opened once the game has started its server
        while not started:
            time.sleep(0.01)
        seats = started[0]
        token = next(iter(seats.tokens))
        assert seats.server is not None
        base = f"http://127.0.0.1:{seats.server.server_port}/api/{token}"
        assert call(f"http://127.0.0.1:{seats.server.server_port}/api/wrong/state")[0] == 404
        try:
            play_as_human(base, seen, stop)
        except BaseException as e:  # reported by the test; the game goes on with its time limit
            seen["error"] = repr(e)
    bot.append(threading.Thread(target=watch, daemon=True))
    bot[0].start()
    roles = ["Vanilla Villager", "Vanilla Villager", "Sheriff", "Medic", "Grunt", "Grunt"]
    models = [ModelSpec(Model.HUMAN)] + [ModelSpec(Model.HAIKU_5_5)] * 5
    try:
        path = mafia.play_game(MockClient(5), mafia.GameConfig(models, Model.HAIKU_5_5, roles, seed=5, debrief=True,
                                                                human_time_limit=2))
    finally:
        stop.set()
        bot[0].join(timeout=5)
    assert "error" not in seen, seen.get("error")
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    me = next(p for p in records[0]["players"] if p["model"] == "human")
    assert me["via"] == "human" and records[-1]["kind"] == "result"
    assert seen["over"] and "day_turn" in seen["steps"] and "debrief" in seen["steps"]
    calls = [r for r in records if r["kind"] == "player_call" and r["player"] == me["name"]]
    assert {c["human"] for c in calls} >= {"answered", "skipped"}
    assert any(r["kind"] == "player_feedback" and r["step"] == "human_report" and r["player"] == me["name"]
               for r in records)
    said = [r for r in records if r["kind"] == "event" and "I am a plain villager." in json.dumps(r)]
    assert said
    # The page showed only what this seat may see: every event in the log visible to them, and nothing else.
    visible = [r["text"] for r in records if r["kind"] in ("event", "notice")
               and (r["visible_to"] == "all" or me["name"] in r["visible_to"])]
    assert [e["text"] for e in seen["events"]] == visible[:len(seen["events"])]


def test_a_human_question_waits_and_times_out_to_its_default(game_factory):
    game, players = game_factory(["Vanilla Villager", "Vanilla Villager", "Grunt"])
    alice = game.player("Alice")
    alice.model = Model.HUMAN
    seats = HumanSeats(game, "(rules)", time_limit=0.2)
    players.humans = seats
    assert players.ask(alice, "Guilty?", VOTE_SCHEMA, {"vote": False}, step="trial_vote") == {"vote": False}
    assert any("ran out" in e.text for e in game.events if e.visible_to == frozenset({"Alice"}))

    seats.time_limit = 0  # no limit: it waits for the answer
    got: list[dict] = []
    t = threading.Thread(target=lambda: got.append(players.ask(alice, "Guilty?", VOTE_SCHEMA, {"vote": False},
                                                                 step="trial_vote")))
    t.start()
    while not seats.pending["Alice"]:
        time.sleep(0.01)
    q = seats.pending["Alice"][0]
    assert seats.answer("Alice", q.id, {"vote": "yes"})  # not a boolean: refused, still waiting
    assert seats.answer("Alice", q.id, {"vote": True}) == []
    t.join(timeout=5)
    assert got == [{"vote": True}]
