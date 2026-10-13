"""Human seats: people playing alongside the LLM players, each on a browser page (--humans N).

A human seat is a player whose model is Model.HUMAN. Players.ask sends its questions here instead of to an LLM:
the question waits in HumanSeats until the person answers it on their page (or skips it, or --human-time-limit runs
out, which uses the same default answer a failed LLM call gets). Nothing else in the game knows a seat is human, and
the LLM players aren't told people may be playing (Kevin, Oct 13 2026).

The page polls GET /api/<token>/state for what the seat may see (the same events its LLM prompt would show:
Event.visible, so a page shows nothing a prompt wouldn't) and its pending question, and posts answers to
/api/<token>/answer. Bug reports and feedback typed into the page's box at any time go to /api/<token>/feedback and
are logged as "player_feedback" records, like the LLM players' feedback field, so alerts.py lists them.

Each seat's link carries a random token, which is the only access check. The server listens on localhost only by
default; to let people join from elsewhere, --human-host 0.0.0.0 plus HTTPS in front (a reverse proxy or a tunnel)
is all it needs, since the tokens already keep seats apart.
"""

import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from llm import Model, schema_errors
from players import night_history, notepad_words, role_briefing
from state import Game, Player, phase_label

PAGE = Path(__file__).with_name("human_page.html")
DEFAULT_PORT = 8766
LINGER_S = 600  # after the game, how long the server waits for every human to see the result
LINGER_GRACE_S = 3.0  # then a little longer, so the last page's next poll gets the final events too


@dataclass
class Question:
    id: int
    player: str
    task: str
    schema: dict  # the task's own schema plus the fields every answer has (players.with_common_fields)
    fallback: dict
    where: dict  # step, day, phase and round, as logged
    ui: dict  # extra facts for the page (a day turn's prices)
    posted: float = field(default_factory=time.time)
    answer: dict | None = None
    how: str = ""  # "answered", "skipped" or "timeout"


class HumanSeats:
    """The questions waiting for human seats, and what each seat's page shows."""

    def __init__(self, game: Game, rules: str, time_limit: float = 0.0):
        """time_limit: seconds a human has for each question; 0 waits as long as it takes (--human-time-limit)."""
        self.game = game
        self.rules = rules
        self.time_limit = time_limit
        self.tokens = {secrets.token_urlsafe(16): p.name for p in game.players if p.model is Model.HUMAN}
        self.cond = threading.Condition()
        self.pending: dict[str, list[Question]] = {name: [] for name in self.tokens.values()}
        self.next_id = 1
        self.saw_end: set[str] = set()  # humans whose page has shown the finished game
        self.server: ThreadingHTTPServer | None = None

    # --- the game's side ---------------------------------------------------------------------------------------

    def ask(self, p: Player, task: str, schema: dict, fallback: dict, where: dict, ui: dict) -> tuple[dict, str]:
        """Waits for p's answer; returns it and how it came ("answered", "skipped" or "timeout")."""
        with self.cond:
            q = Question(self.next_id, p.name, task, schema, fallback, where, ui)
            self.next_id += 1
            self.pending[p.name].append(q)
            self.cond.notify_all()
            deadline = time.monotonic() + self.time_limit if self.time_limit > 0 else None
            while q.answer is None:
                left = None if deadline is None else deadline - time.monotonic()
                if left is not None and left <= 0:
                    q.answer, q.how = dict(fallback), "timeout"
                    break
                self.cond.wait(timeout=left)
            self.pending[p.name].remove(q)
            return q.answer, q.how

    # --- the page's side ---------------------------------------------------------------------------------------

    def answer(self, name: str, qid: int, data: Any, skip: bool = False) -> list[str]:
        """The page's answer to question qid; returns what's wrong with it (nothing if it was accepted)."""
        with self.cond:
            q = next((q for q in self.pending.get(name, []) if q.id == qid), None)
            if q is None:
                return ["that question isn't waiting any more (it was answered, or its time ran out)"]
            if skip:
                q.answer, q.how = dict(q.fallback), "skipped"
            else:
                if not isinstance(data, dict):
                    return ["the answer must be a JSON object"]
                out = self.complete(q, data)
                if errors := schema_errors(out, q.schema):
                    return errors
                q.answer, q.how = out, "answered"
            self.cond.notify_all()
            return []

    def complete(self, q: Question, data: dict) -> dict:
        """data with the fields the page may leave out: the task's own from its default answer, the common ones
        empty ("" keeps the notepad, as for LLM players; a human's reason is optional)."""
        props = q.schema["properties"]
        out = {k: v for k, v in data.items() if k in props}
        for k in props:
            if k not in out:
                out[k] = q.fallback.get(k, "" if k in ("notepad", "reason", "feedback") else None)
        if out.get("notepad") == self.game.player(q.player).notepad:
            out["notepad"] = ""
        return out

    def report(self, name: str, text: str) -> None:
        """A bug report or feedback from the page's box, logged like an LLM player's feedback field."""
        p = self.game.player(name)
        self.game.log.write("player_feedback", day=self.game.day, phase=self.game.phase, step="human_report",
                            player=name, role=p.role, feedback=text.strip())

    def state(self, name: str, since: int) -> dict:
        """What name's page shows: their events from index `since` on, their private info and any question."""
        for attempt in range(5):  # the game thread may change a dict while this reads it
            try:
                return self._state(name, since)
            except RuntimeError:
                if attempt == 4:
                    raise
                time.sleep(0.05)
        raise AssertionError("unreachable")

    def _state(self, name: str, since: int) -> dict:
        game = self.game
        p = game.player(name)
        events = [e for e in list(game.events) if e.visible(name)]
        over = game.winners is not None
        if over:
            self.saw_end.add(name)
        with self.cond:
            q = self.pending[name][0] if self.pending[name] else None
            question = q and {"id": q.id, "task": q.task, "fallback": q.fallback, "ui": q.ui, **q.where,
                              "schema": {k: v for k, v in q.schema["properties"].items()
                                         if k not in ("notepad", "reason", "feedback")},
                              "deadline": q.posted + self.time_limit if self.time_limit > 0 else None}
        return {
            "name": name, "role": p.role, "alive": p.alive, "day": game.day, "phase": game.phase,
            "players": [{"name": q.name, "alive": q.alive, "you": q.name == name,
                         **({"role": q.role, "model": q.model.short} if over else {})} for q in game.players],
            "events": [{"label": phase_label(e.day, e.phase), "cat": e.cat, "text": e.text,
                        **({k: e.fields[k] for k in ("speaker", "to") if k in e.fields})} for e in events[since:]],
            "n_events": len(events), "briefing": role_briefing(game, p), "ledger": game.public_ledger(),
            "night_history": night_history(game, p), "last_will": p.last_will, "notepad": p.notepad,
            "notepad_words": notepad_words(game), "budget": round(p.speaking_budget, 2), "tips": p.tips,
            "rules": self.rules, "question": question, "winners": game.winners if over else None,
            "result": game.winners_line() if over else None, "now": time.time(),
        }

    # --- the server --------------------------------------------------------------------------------------------

    def start(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> list[str]:
        """Starts the pages' server in the background (the next free port from `port`); returns each seat's link."""
        seats = self
        page = PAGE.read_bytes()

        class Handler(BaseHTTPRequestHandler):
            def seat(self) -> str | None:
                parts = self.path.split("?")[0].strip("/").split("/")
                return seats.tokens.get(parts[1]) if len(parts) >= 2 and parts[0] in ("seat", "api") else None

            def do_GET(self) -> None:
                name = self.seat()
                path = self.path.split("?")[0]
                if name is None:
                    self.send(404, b"Unknown seat: open the link the game printed for you.", "text/plain")
                elif path.startswith("/seat/"):
                    self.send(200, page, "text/html; charset=utf-8")
                elif path.endswith("/state"):
                    query = dict(x.split("=", 1) for x in self.path.partition("?")[2].split("&") if "=" in x)
                    since = int(query.get("since", "0") or 0)
                    self.send_json(seats.state(name, since))
                else:
                    self.send(404, b"Not found", "text/plain")

            def do_POST(self) -> None:
                name = self.seat()
                if name is None:
                    self.send(404, b"Unknown seat", "text/plain")
                    return
                try:
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                except json.JSONDecodeError:
                    self.send_json({"errors": ["not JSON"]}, 400)
                    return
                if self.path.endswith("/answer"):
                    errors = seats.answer(name, int(body.get("id", 0)), body.get("answer"), bool(body.get("skip")))
                    self.send_json({"errors": errors}, 400 if errors else 200)
                elif self.path.endswith("/feedback") and str(body.get("text", "")).strip():
                    seats.report(name, str(body["text"]))
                    self.send_json({"ok": True})
                else:
                    self.send(404, b"Not found", "text/plain")

            def send_json(self, data: dict, status: int = 200) -> None:
                self.send(status, json.dumps(data).encode(), "application/json")

            def send(self, status: int, body: bytes, kind: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                pass  # the page polls every second or two

        for p in range(port, port + 50):
            try:
                self.server = ThreadingHTTPServer((host, p), Handler)
                break
            except OSError:
                continue
        else:
            raise OSError(f"no free port for the human seats' pages in {port}-{port + 49}")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        shown = "localhost" if host in ("127.0.0.1", "0.0.0.0", "") else host
        return [f"{name}: http://{shown}:{self.server.server_port}/seat/{token}" for token, name in self.tokens.items()]

    def linger(self, timeout: float | None = None) -> None:
        """After the game: keeps the pages up until every human's page has shown the result (or timeout, by default
        LINGER_S)."""
        end = time.monotonic() + (LINGER_S if timeout is None else timeout)
        while set(self.tokens.values()) - self.saw_end and time.monotonic() < end:
            time.sleep(0.5)
        time.sleep(LINGER_GRACE_S)

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
