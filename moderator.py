"""The LLM moderator and its tools."""

import difflib
import json
from typing import Any

from llm import LLMClient, Model
from players import ANSWER_SCHEMA, Players
from state import ANNOUNCEMENT, RESULT, Game, Status


def tool(name: str, description: str, **params: dict) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": params, "required": list(params)},
    }}


MODERATOR_TOOLS = [
    tool("get_state", "Full hidden game state: roles, tokens, statuses, katana holder."),
    tool("apply_changes", "Apply state changes. Ops: {op:'kill', player, cause} | "
         "{op:'set_tokens', player, token, value} | {op:'set_status', player, key, value} "
         "(value null deletes the key) | {op:'set_katana', player} | {op:'set_last_will', player, text} "
         "(e.g. a Fabricator forgery). For a Mortician clean, use set_status key 'cleaned' value true; "
         "the dawn reveal then hides the role, will and cause. Night deaths are revealed at dawn with "
         "the last will as it is then, so the order of ops within a night doesn't matter. Day effects "
         "that code carries out: {op:'prosecute', player} (they go to trial when the next day starts), "
         "{op:'rig_vote'} (Clerk: tomorrow's trials execute the accused regardless of the vote; no "
         "player field), {op:'puppet', player, by} (player is puppeted by the Puppeteer `by` tomorrow).",
         changes={"type": "array", "items": {"type": "object"}}),
    tool("random_choice", "Pick k distinct items uniformly at random using the game's RNG. "
         "Always use this instead of choosing 'randomly' yourself.",
         options={"type": "array", "items": {"type": "string"}}, k={"type": "integer"}),
    tool("tell", "Send a message. to = list of player names, or ['all'] for a public announcement.",
         to={"type": "array", "items": {"type": "string"}}, text={"type": "string"}),
    tool("ask_player", "Ask one player a question and get their free-text answer.",
         player={"type": "string"}, question={"type": "string"}),
    tool("end_phase", "Finish this phase. The summary is private to the game log.",
         summary={"type": "string"}),
]

# apply_changes ops: op -> (required fields, optional fields). Ops are checked against this before
# any is applied, so a malformed batch changes nothing and the moderator gets a clear error.
OPS: dict[str, tuple[set[str], set[str]]] = {
    "kill": ({"player"}, {"cause"}),
    "set_tokens": ({"player", "token", "value"}, set()),
    "set_status": ({"player", "key"}, {"value"}),
    "set_katana": ({"player"}, set()),
    "set_last_will": ({"player", "text"}, set()),
    "prosecute": ({"player"}, set()),
    "rig_vote": (set(), set()),
    "puppet": ({"player", "by"}, set()),
}
CODE_STATUS_KEYS = {v for k, v in vars(Status).items() if not k.startswith("_")}

FLAG_TOOL = tool("flag_issue", "Report a problem with the game itself without stopping it: an ambiguous or "
                 "contradictory rule, a tool or piece of state you're missing, or anything that looks "
                 "like a program bug. Then carry on with your best interpretation.", issue={"type": "string"})

MAX_MODERATOR_STEPS = 40


class Moderator:
    def __init__(self, game: Game, client: LLMClient, players: Players, model: Model, rules: str,
                 flag_issues: bool = False):
        self.game = game
        self.client = client
        self.players = players
        self.model = model
        self.rules = rules
        self.tools = MODERATOR_TOOLS + ([FLAG_TOOL] if flag_issues else [])
        self.flags: list[str] = []

    def run_phase(self, instructions: str) -> None:
        messages = [
            {"role": "system", "content": f"{self.rules}\n\n---\n\nYou are the omniscient moderator of "
             "this game. Code stores the state and runs the day phase; you resolve what code can't "
             "by calling tools. Be exact about the rules. Never reveal hidden information except "
             "as the rules allow. A private result contains only what the rules say its recipient "
             "learns, worded neutrally: never explain why a result came out as it did (e.g. never "
             "mention the Katana, framing or defenses to an investigator), and never name an attacker "
             "or reveal roles beyond what the rules allow."
             + (" If a rule is ambiguous, or you lack a tool or information you need, call flag_issue and "
                "then continue with your best interpretation." if len(self.tools) > len(MODERATOR_TOOLS) else "")},
            {"role": "user", "content": f"{instructions}\n\nCurrent full state (call get_state to "
             f"refresh after changes):\n{json.dumps(self.game.full_state())}\n\nPublic history so far:\n"
             f"{self.game.history_for('__moderator_public__')}"},
        ]
        for _ in range(MAX_MODERATOR_STEPS):
            reply = self.client.chat(self.model, messages, tools=self.tools)
            self.game.log.write("moderator_call", model=self.model.value, content=reply.content,
                                reasoning=reply.reasoning, tool_calls=reply.tool_calls, cost=reply.cost,
                                usage=reply.usage)
            messages.append(reply.message)
            if not reply.tool_calls:
                messages.append({"role": "user", "content": "Call end_phase when you are finished."})
                continue
            for call in reply.tool_calls:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                    result = self.dispatch(name, args)
                except Exception as e:  # report tool errors back to the moderator
                    result = {"error": f"{type(e).__name__}: {e}"}
                self.game.log.write("moderator_tool", name=name, args=call["function"].get("arguments"),
                                    result=result)
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)})
                if name == "end_phase":
                    return
        self.game.log.write("moderator_error", error="step limit reached")

    def dispatch(self, name: str, args: dict) -> Any:
        g = self.game
        match name:
            case "get_state":
                return g.full_state()
            case "apply_changes":
                notes = self.check_changes(args["changes"])
                for c in args["changes"]:
                    p = g.player(c["player"]) if "player" in c else None
                    match c["op"]:
                        case "prosecute":
                            g.prosecutions.append(p.name)
                        case "rig_vote":
                            g.rigged_day = g.day + 1
                        case "puppet":
                            g.puppets_next[p.name] = g.player(c["by"]).name
                        case "kill":
                            g.kill(p.name, c.get("cause", "killed"))
                        case "set_tokens":
                            p.tokens[c["token"]] = int(c["value"])
                        case "set_status":
                            if c.get("value") is None:
                                p.status.pop(c["key"], None)
                            else:
                                p.status[c["key"]] = c["value"]
                        case "set_last_will":
                            p.last_will = c["text"]
                        case "set_katana":
                            g.katana_holder = p.name
                return {"ok": True, **({"notes": notes} if notes else {})}
            case "random_choice":
                return {"chosen": g.rng.sample(args["options"], int(args.get("k", 1)))}
            case "tell":
                to = args["to"]
                if to == ["all"] and g.phase == "night":
                    g.pending_announcements.append(args["text"])  # read out at dawn
                elif to == ["all"]:
                    g.emit(f"Moderator: {args['text']}", cat=ANNOUNCEMENT, message=args["text"])
                else:
                    for n in to:
                        g.player(n)  # validate names
                    g.emit(f"Moderator (private): {args['text']}", to, cat=RESULT, message=args["text"])
                return {"ok": True}
            case "ask_player":
                p = g.player(args["player"])
                out = self.players.ask(p, f"The moderator asks: {args['question']}", ANSWER_SCHEMA,
                                       {"answer": ""})
                return out
            case "end_phase":
                return {"ok": True}
            case "flag_issue":
                self.flags.append(args["issue"])
                g.log.write("moderator_flag", day=g.day, phase=g.phase, issue=args["issue"])
                return {"ok": True, "note": "Thanks; carry on."}
        raise ValueError(f"unknown tool {name!r}")

    def check_changes(self, changes: list) -> list[str]:
        """Raises ValueError, before anything is applied, if any op is malformed. Returns warnings."""
        notes = []
        for i, c in enumerate(changes):
            if not isinstance(c, dict) or c.get("op") not in OPS:
                raise ValueError(f"change {i}: op must be one of {sorted(OPS)}; nothing was applied")
            required, optional = OPS[c["op"]]
            fields = set(c) - {"op"}
            if missing := required - fields:
                raise ValueError(f"change {i} ({c['op']}): missing {sorted(missing)}; nothing was applied")
            if extra := fields - required - optional:
                notes.append(f"change {i} ({c['op']}): ignored unknown fields {sorted(extra)}")
            for key in ("player", "by"):
                if key in c and c[key] not in {p.name for p in self.game.players}:
                    raise ValueError(f"change {i} ({c['op']}): no player named {c[key]!r}; nothing was applied")
            if c["op"] == "set_tokens" and not str(c["value"]).lstrip("-").isdigit():
                raise ValueError(f"change {i} (set_tokens): value must be an integer; nothing was applied")
            if c["op"] == "set_status" and c["key"] not in CODE_STATUS_KEYS:
                close = difflib.get_close_matches(c["key"], CODE_STATUS_KEYS, n=1)
                if close:
                    notes.append(f"status key {c['key']!r} is not one code reads; did you mean {close[0]!r}?")
        return notes
