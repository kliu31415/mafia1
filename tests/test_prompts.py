"""What players and the moderator are actually sent, for a short scripted game (one day, one night, the next dawn).

- Snapshots: each kind of prompt is compared with a file in tests/prompts/, so a prompt change shows up as a
  readable diff in the commit. After an intended change, rewrite them with `uv run pytest --update-prompts`
  and read the diff before committing.
- Cache stability: prompt caching (llm.cache_block) only pays off if what's marked stable really is, so a
  player's system message must stay byte-identical within a phase, and every in-game call must send one schema.
"""

import json
import threading
from pathlib import Path

import pytest

from day import run_day
from llm import Model
from moderator import Moderator
from night import run_night
from players import Players
from tests.conftest import TOWN4_GRUNT, ScriptedClient, make_game

PROMPTS = Path(__file__).parent / "prompts"
ROLES = ["Sheriff", "Vanilla Villager", "Medic", "Vanilla Villager", "Grunt", "Grunt"]  # Alice ... Frank


class RecordingClient(ScriptedClient):
    """A ScriptedClient that keeps every request as sent, with the step Players.ask was called for."""

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.requests: list[dict] = []
        self.lock = threading.Lock()

    def chat(self, model, messages, *, tools=None, schema=None, schema_name="response", effort=None):
        with self.lock:
            self.requests.append({"step": getattr(CURRENT, "step", None), "phase": getattr(CURRENT, "phase", None),
                                  "messages": json.loads(json.dumps(messages)),
                                  "schema": schema, "tools": tools})
        return super().chat(model, messages, tools=tools, schema=schema, schema_name=schema_name, effort=effort)


CURRENT = threading.local()  # the step, day and phase of the Players.ask call running on this thread


def decide(name, task, schema):
    """Live games send every field (players.shared_schema), so this goes by the task, not the schema."""
    if "Vote true" in task:
        return {"vote": True}  # Dave is nominated and executed
    if "trial turn" in task:
        return {"public_message": f"{name} has a view on this trial."}
    if "It's your turn" in task and name == "Alice" and "Day 1, round 1" in task:
        return {"public_message": "Dave has been very quiet. I nominate him.", "nominate": "Dave",
                "claim": "Sheriff", "notepad": "Dave: quiet, nominated D1"}
    if "Yakuza chat" in task:
        return {"message": "Let's attack Alice.", "ready": True}
    if "Choose your night action" in task:
        return {"act": True, "target": "Alice" if name != "Alice" else "Erin",
                **({"katana_vote_holder": "Erin", "katana_vote_target": "Alice"} if name in ("Erin", "Frank") else {})}
    return None


@pytest.fixture(scope="module")
def requests(tmp_path_factory) -> list[dict]:
    client = RecordingClient(decide, moderator_calls=[
        ("tell", {"to": ["Alice"], "text": "Your target, Erin, is Evil."}),
        ("apply_changes", {"changes": [{"op": "kill", "player": "Alice", "cause": "Katana", "by": "Erin",
                                        "katana": True}]})])
    game, _ = make_game(tmp_path_factory.mktemp("prompts"), ROLES, client)
    players = Players(game, client, rules="(rules)", shared=True)  # the live games' path
    real_ask = players.ask

    def ask(*args, step, **kw):
        CURRENT.step, CURRENT.phase = step, (game.day, game.phase)
        try:
            return real_ask(*args, step=step, **kw)
        finally:
            CURRENT.step = None  # the moderator's calls on this thread aren't a player's
    players.ask = ask  # type: ignore[method-assign]
    moderator = Moderator(game, client, players, Model.HAIKU_5_5, "(rules)", flag_issues=True)
    run_day(game, players)
    run_night(game, players, moderator)
    run_day(game, players)  # everyone stays quiet, so it ends after one round
    game.log.close()
    return client.requests


def player_of(request: dict) -> str:
    text = json.dumps(request["messages"][0])
    return next(n for n in ("Alice", "Bob", "Carol", "Dave", "Erin", "Frank") if f"You are {n} (seat" in text)


def render(request: dict) -> str:
    def text(content):
        return content if isinstance(content, str) or content is None else "".join(
            b["text"] + ("\n[end of a cached prefix]\n" if "cache_control" in b else "") for b in content)
    parts = [f"=== {m['role']} ===\n{text(m.get('content'))}" for m in request["messages"]]
    if request["tools"]:
        parts.append("=== tools ===\n" + "\n".join(t["function"]["name"] for t in request["tools"]))
    return "\n\n".join(parts) + "\n"


def snapshots(requests: list[dict]) -> dict[str, str]:
    """One prompt per kind of call and day: the first moderator call, and for each step the call of the
    earliest-seated player asked (parallel calls arrive in any order)."""
    out = {"moderator_night1": render(next(r for r in requests if r["tools"]))}
    for key in dict.fromkeys(f"{r['step']}_day{r['phase'][0]}" for r in requests if r["step"]):
        out[key] = render(min((r for r in requests if r["step"] and f"{r['step']}_day{r['phase'][0]}" == key),
                              key=player_of))
    out["shared_schema"] = json.dumps(next(r["schema"] for r in requests if r["step"]), indent=1) + "\n"
    return out


def test_prompts_match_their_snapshots(requests, request):
    got = snapshots(requests)
    assert {"day_turn_day1", "trial_turn_day1", "nomination_vote_day1", "trial_vote_day1", "yakuza_chat_day1",
            "night_action_day1", "moderator_night1", "will_day1", "will_day2", "day_turn_day2"} <= set(got)
    if request.config.getoption("--update-prompts"):
        PROMPTS.mkdir(exist_ok=True)
        for old in PROMPTS.glob("*.txt"):
            old.unlink()
        for name, text in got.items():
            (PROMPTS / f"{name}.txt").write_text(text, encoding="utf-8", newline="\n")
        return
    stored = {f.stem: f.read_text(encoding="utf-8") for f in PROMPTS.glob("*.txt")}
    changed = sorted(n for n in set(got) | set(stored) if got.get(n) != stored.get(n))
    assert not changed, (f"prompts changed: {changed}. If that's intended, run `uv run pytest --update-prompts` "
                         "and check the diff of tests/prompts/ before committing.")


def test_a_players_cached_prefix_is_stable_within_a_phase(requests):
    """Claude and Gemini read a cached prefix only if it's byte-identical, and OpenAI caches only the system
    message, so the system message (rules, general instructions, briefing, earlier phases) must not change
    between one player's calls in the same phase."""
    systems: dict[tuple[str, int, str], set[str]] = {}
    for r in requests:
        if r["step"]:
            systems.setdefault((player_of(r), *r["phase"]), set()).add(json.dumps(r["messages"][0]))
    unstable = sorted(k for k, v in systems.items() if len(v) > 1)
    assert not unstable, f"system message changed within a phase for {unstable}"


def test_every_in_game_call_sends_one_schema(requests):
    """The answer schema is part of Claude's cached prefix (players.shared_schema)."""
    schemas = {json.dumps(r["schema"], sort_keys=True) for r in requests if r["step"]}
    assert len(schemas) == 1


def test_models_get_the_long_reason_note_unless_listed_short(game_factory):
    from players import LONG_REASON_NOTE, REASON_NOTE, player_messages
    game, _ = game_factory(TOWN4_GRUNT)
    alice, bob = game.players[:2]
    bob.model = Model.GPT_6_LUNA
    def text(p):
        return player_messages(game, p, "(rules)", "task")[-1]["content"]
    assert REASON_NOTE in text(alice) and LONG_REASON_NOTE not in text(alice)
    assert LONG_REASON_NOTE in text(bob) and REASON_NOTE not in text(bob)
