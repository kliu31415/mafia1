"""The LLM moderator and its tools."""

import difflib
import json
from typing import Any

from llm import LLMClient, Model
from players import ANSWER_SCHEMA, Players
from events import ANNOUNCEMENT, RESULT
from roles import RoleLogic, Status, logic
from state import Game


def tool(name: str, description: str, **params: dict) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": params, "required": list(params)},
    }}


def apply_changes_tool(role_op_docs: list[str]) -> dict:
    return tool(
        "apply_changes", "Apply state changes. Ops: {op:'kill', player, cause, by, katana} (by = the "
        "killer's name if a player killed them; katana = true for the Katana attack; cause = the public wording) | "
        "{op:'set_tokens', player, token, value} | {op:'set_status', player, key, value} "
        "(value null deletes the key) | {op:'set_katana', player} | {op:'set_last_will', player, text} "
        "(e.g. a Fabricator forgery). For a Mortician clean, use set_status key 'cleaned' value true; "
        "the dawn reveal then hides the role, will and cause. Night deaths are revealed at dawn with "
        "the last will as it is then, so the order of ops within a night doesn't matter."
        + (" Ops for roles in this game, whose effects code carries out: " + " | ".join(role_op_docs)
           if role_op_docs else ""),
        changes={"type": "array", "items": {"type": "object"}})


MODERATOR_TOOLS = [
    tool("get_state", "Full hidden game state: roles, tokens, statuses, katana holder."),
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

# apply_changes ops: op -> (required fields, optional fields). Roles add their own (RoleLogic.ops).
# Ops are checked before any is applied, so a malformed batch changes nothing and the moderator
# gets a clear error.
CORE_OPS: dict[str, tuple[set[str], set[str]]] = {
    "kill": ({"player"}, {"cause", "by", "katana"}),
    "set_tokens": ({"player", "token", "value"}, set()),
    "set_status": ({"player", "key"}, {"value"}),
    "set_katana": ({"player"}, set()),
    "set_last_will": ({"player", "text"}, set()),
}
CODE_STATUS_KEYS = {v for k, v in vars(Status).items() if not k.startswith("_")}

FLAG_TOOL = tool("flag_issue", "Report a problem with the game itself without stopping it: an ambiguous or "
                 "contradictory rule, a tool or piece of state you're missing, or anything that looks "
                 "like a program bug. Cite the rule (e.g. R9) or role it concerns. Then carry on with your "
                 "best interpretation.", issue={"type": "string"})

MAX_MODERATOR_STEPS = 40


class Moderator:
    def __init__(self, game: Game, client: LLMClient, players: Players, model: Model, rules: str,
                 flag_issues: bool = False, effort: str | None = None):
        self.game = game
        self.effort = effort  # None: the client's default
        self.client = client
        self.players = players
        self.model = model
        self.rules = rules
        self.flags: list[str] = []
        self.ops = dict(CORE_OPS)
        self.op_roles: dict[str, RoleLogic] = {}  # role op -> the role that carries it out
        docs = []
        for role in sorted({p.role for p in game.players}):
            for op, (required, optional, doc) in logic(role).ops.items():
                self.ops[op] = (required, optional)
                self.op_roles[op] = logic(role)
                docs.append(doc)
        self.tools = ([MODERATOR_TOOLS[0], apply_changes_tool(docs)] + MODERATOR_TOOLS[1:]
                      + ([FLAG_TOOL] if flag_issues else []))

    def run_phase(self, instructions: str) -> list[dict]:
        """Runs the moderator until it ends the phase. Returns what it did: each tool call, its
        arguments and result, in order (for the night check)."""
        transcript: list[dict] = []
        messages = [
            {"role": "system", "content": f"{self.rules}\n\n---\n\nYou are the omniscient moderator of "
             "this game. Code stores the state and runs the day phase; you resolve what code can't "
             "by calling tools. Be exact about the rules. Never reveal hidden information except "
             "as the rules allow. A private result contains only what the rules say its recipient "
             "learns, worded neutrally: never explain why a result came out as it did (e.g. never "
             "mention the Katana, framing or defenses to an investigator), and never name an attacker "
             "or reveal roles beyond what the rules allow."
             + (" If a rule is ambiguous, or you lack a tool or information you need, call flag_issue and "
                "then continue with your best interpretation." if FLAG_TOOL in self.tools else "")},
            {"role": "user", "content": f"{instructions}\n\nCurrent full state (call get_state to "
             f"refresh after changes):\n{json.dumps(self.game.full_state())}\n\nPublic history so far:\n"
             f"{self.game.history_for('__moderator_public__')}"},
        ]
        for _ in range(MAX_MODERATOR_STEPS):
            reply = self.client.chat(self.model, messages, tools=self.tools, effort=self.effort)
            self.game.log.write("moderator_call", model=self.model.value, content=reply.content,
                                reasoning=reply.reasoning, tool_calls=reply.tool_calls, cost=reply.cost,
                                usage=reply.usage)
            messages.append(reply.message)
            if not reply.tool_calls:
                if not reply.content:  # e.g. refused or cut off; a reply in words only is just nudged
                    self.game.log.error("moderator_error", f"the moderator gave an empty answer on day "
                                        f"{self.game.day} {self.game.phase} ({reply.stop_note or 'no reason given'})")
                messages.append({"role": "user", "content": "Call end_phase when you are finished."})
                continue
            for call in reply.tool_calls:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                    result = self.dispatch(name, args)
                except Exception as e:  # report tool errors back to the moderator, and to whoever runs the game
                    result = {"error": f"{type(e).__name__}: {e}"}
                    self.game.log.error("moderator_tool_error", f"{name} failed on day {self.game.day} "
                                        f"{self.game.phase}: {result['error']}", tool=name,
                                        args=call["function"].get("arguments"))
                self.game.log.write("moderator_tool", name=name, args=call["function"].get("arguments"),
                                    result=result)
                transcript.append({"tool": name, "args": call["function"].get("arguments"),
                                   "result": "(the full state)" if name == "get_state" else result})
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)})
                if name == "end_phase":
                    return transcript
        self.game.log.error("moderator_error", f"the moderator hit its step limit ({MAX_MODERATOR_STEPS}) "
                            f"without ending the phase, day {self.game.day} {self.game.phase}")
        transcript.append({"tool": "(none)", "result": "the moderator hit its step limit without ending the phase"})
        return transcript

    def dispatch(self, name: str, args: dict) -> Any:
        g = self.game
        match name:
            case "get_state":
                return g.full_state()
            case "apply_changes":
                notes = self.check_changes(args["changes"])
                for note in notes:  # applied anyway, but likely a moderator mistake
                    g.log.error("moderator_warning", f"day {g.day} {g.phase}: {note}", changes=args["changes"])
                for c in args["changes"]:
                    if c["op"] in self.op_roles:
                        self.op_roles[c["op"]].apply_op(g, c)
                        continue
                    p = g.player(c["player"])  # every core op names a player
                    match c["op"]:
                        case "kill":
                            g.kill(p.name, c.get("cause", "killed"), by=c.get("by"), katana=bool(c.get("katana")))
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
            if not isinstance(c, dict) or c.get("op") not in self.ops:
                raise ValueError(f"change {i}: op must be one of {sorted(self.ops)}; nothing was applied")
            required, optional = self.ops[c["op"]]
            fields = set(c) - {"op"}
            if missing := required - fields:
                raise ValueError(f"change {i} ({c['op']}): missing {sorted(missing)}; nothing was applied")
            if extra := fields - required - optional:
                notes.append(f"change {i} ({c['op']}): ignored unknown fields {sorted(extra)}")
            for key in ("player", "by"):
                if key in c and c[key] not in {p.name for p in self.game.players}:
                    raise ValueError(f"change {i} ({c['op']}): no player named {c[key]!r}; nothing was applied")
            if c["op"] == "kill" and not self.game.player(c["player"]).alive:
                notes.append(f"change {i} (kill): {c['player']} is already dead, so it does nothing")
            if c["op"] == "set_tokens" and not str(c["value"]).lstrip("-").isdigit():
                raise ValueError(f"change {i} (set_tokens): value must be an integer; nothing was applied")
            if c["op"] == "set_status" and c["key"] not in CODE_STATUS_KEYS:
                close = difflib.get_close_matches(c["key"], CODE_STATUS_KEYS, n=1)
                if close:
                    notes.append(f"status key {c['key']!r} is not one code reads; did you mean {close[0]!r}?")
        return notes
