"""The LLM moderator and its tools."""

import difflib
import json
import re
import time
from typing import Any

from llm import LLMClient, LLMReply, Model, ModelSpec, cache_block, clean_json, rules_system
from players import ANSWER_SCHEMA, Players
from events import ANNOUNCEMENT
from roles import Alignment, RoleLogic, Status, logic
from state import Game


def tool(name: str, description: str, **params: dict) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": params, "required": list(params)},
    }}


def apply_changes_tool(role_op_docs: list[str]) -> dict:
    return tool(
        "apply_changes", "Apply state changes. Ops: {op:'kill', player, cause, by, katana} (by = the "
        "killer's name if a player killed them, or a list of names if several attacks would each have killed them; "
        "katana = true if the Katana attack was one of them; cause = the killer's role or weapon, e.g. 'Katana' or "
        "'Vigilante', naming every fatal cause when there are several (R12), e.g. 'Katana and Serial Killer'; it's "
        "revealed as 'X died (killed by <cause>)') | "
        "{op:'set_tokens', player, token, value} | {op:'set_status', player, key, value} "
        "(value null deletes the key) | {op:'set_katana', player} (not at night: code moves the Katana per the Yakuza vote and passes it on "
        "after the night's results if its holder died) | {op:'set_last_will', player, text} "
        "(e.g. a Fabricator forgery). For a Mortician clean, use set_status key 'cleaned' value true; "
        "the dawn reveal then hides the role and will (the cause is still shown). "
        "Night deaths are revealed at dawn with "
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
CODE_STATUS_KEYS = {v for k, v in vars(Status).items() if not k.startswith("_") and isinstance(v, str)}

FLAG_TOOL = tool("flag_issue", "Report a problem with the game itself without stopping it: an ambiguous or "
                 "contradictory rule, a tool or piece of state you're missing, or anything that looks "
                 "like a program bug. Cite the rule (e.g. R9) or role it concerns. Then carry on with your "
                 "best interpretation.", issue={"type": "string"})

MAX_MODERATOR_STEPS = 40
# Anthropic's filter against copying model outputs sometimes blocks a moderator request (finish_reason
# content_filter; game_20261009_084630_739772, night 3, where a third try went through). This many blocks in a
# row switch the moderator to its fallback model for the rest of the game, a program safeguard, not a rule.
FILTER_BLOCKS_BEFORE_SWITCH = 3
MODERATOR_CALL_ATTEMPTS = 3
MODERATOR_RETRY_WAIT_S = 30


def filter_blocked(reply: LLMReply) -> bool:
    """An answer a provider's filter refused, e.g. Anthropic's against "duplicating model outputs", which
    blocked two Opus moderator requests in a row then let the third through (game_20261009_084630_739772)."""
    return not reply.content and not reply.tool_calls and "content_filter" in (reply.stop_note or "")


class Moderator:
    def __init__(self, game: Game, client: LLMClient, players: Players, model: Model, rules: str,
                 flag_issues: bool = False, effort: str | None = None, fallback: ModelSpec | None = None):
        self.game = game
        self.fallback = fallback  # the model to switch to if a filter keeps blocking this one
        self.filter_blocks = 0  # consecutive blocked answers
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
            rules_system(self.rules, "You are the omniscient moderator of "
             "this game. Code stores the state and runs the day phase; you resolve what code can't "
             "by calling tools. Be exact about the rules. Never reveal hidden information except "
             "as the rules allow. A private result contains only what the rules say its recipient "
             "learns, worded neutrally: never explain why a result came out as it did (e.g. never "
             "mention the Katana, framing or defenses to an investigator), and never name an attacker "
             "or reveal roles beyond what the rules allow."
             + (" If a rule is ambiguous, or you lack a tool or information you need, call flag_issue and "
                "then continue with your best interpretation." if FLAG_TOOL in self.tools else "")),
            # Cached so the phase's later steps, which resend it, read it from the cache.
            {"role": "user", "content": [cache_block(f"{instructions}\n\nCurrent state, summarized:\n"
             f"{self.game.state_summary()}\n\nCurrent full state (call get_state to "
             f"refresh after changes):\n{json.dumps(self.game.full_state())}\n\nPublic history so far:\n"
             f"{self.game.history_for('__moderator_public__')}")]},
        ]
        for _ in range(MAX_MODERATOR_STEPS):
            started = time.monotonic()
            reply = self.chat(messages)
            self.game.log.write("moderator_call", model=self.model.value, day=self.game.day, phase=self.game.phase,
                                content=reply.content, reasoning=reply.reasoning, tool_calls=reply.tool_calls,
                                cost=reply.cost, usage=reply.usage, latency_s=round(time.monotonic() - started, 2))
            messages.append(reply.message)
            if not reply.tool_calls:
                if not reply.content:  # e.g. refused or cut off; a reply in words only is just nudged
                    self.game.log.error("moderator_error", f"the moderator gave an empty answer on day "
                                        f"{self.game.day} {self.game.phase} ({reply.stop_note or 'no reason given'})")
                messages.append({"role": "user", "content": "Call end_phase when you are finished."})
                continue
            ended = False
            for call in reply.tool_calls:  # all of them, even ones listed after end_phase
                name = call["function"]["name"]
                try:
                    args = clean_json(json.loads(call["function"].get("arguments") or "{}"))
                    if not isinstance(args, dict):
                        raise ValueError(f"arguments must be a JSON object, not {args!r:.100}")
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
                ended = ended or name == "end_phase"
            if ended:
                return transcript
        self.game.log.error("moderator_error", f"the moderator hit its step limit ({MAX_MODERATOR_STEPS}) "
                            f"without ending the phase, day {self.game.day} {self.game.phase}")
        transcript.append({"tool": "(none)", "result": "the moderator hit its step limit without ending the phase"})
        return transcript

    def chat(self, messages: list[dict]) -> LLMReply:
        """One moderator call. A failed one (after the client's own retries) is logged and tried again a
        few times, since the game can't go on without its moderator; then the game stops (resumable)."""
        for attempt in range(MODERATOR_CALL_ATTEMPTS):
            try:
                model = self.model
                reply = self.client.chat(self.model, messages, tools=self.tools, effort=self.effort)
                self.note_filter_block(reply)
                if filter_blocked(reply):
                    if self.model is not model:  # just switched to the fallback, which gets the request now
                        return self.chat(messages)
                    # Retried with the same messages: appending the empty answer and a nudge to end the phase
                    # could get the phase ended unresolved.
                    raise RuntimeError(f"blocked by a content filter ({reply.stop_note})")
                return reply
            except Exception as e:
                if attempt == MODERATOR_CALL_ATTEMPTS - 1:
                    raise
                self.game.log.error("moderator_error", f"a moderator call failed on day {self.game.day} "
                                    f"{self.game.phase} (attempt {attempt + 1}), trying again: "
                                    f"{type(e).__name__}: {e}", attempt=attempt)
                time.sleep(MODERATOR_RETRY_WAIT_S * (attempt + 1))
        raise AssertionError("unreachable")

    def note_filter_block(self, reply: LLMReply) -> None:
        self.filter_blocks = self.filter_blocks + 1 if filter_blocked(reply) else 0
        if self.filter_blocks < FILTER_BLOCKS_BEFORE_SWITCH or not self.fallback or self.fallback.model == self.model:
            return
        old = self.model.short
        self.model, self.effort, self.filter_blocks = self.fallback.model, self.fallback.effort, 0
        self.game.log.error("moderator_switch", f"the moderator switched from {old} to {self.model.short} on day "
                            f"{self.game.day} {self.game.phase}: {FILTER_BLOCKS_BEFORE_SWITCH} answers in a row were "
                            f"blocked by a content filter ({reply.stop_note})", day=self.game.day,
                            phase=self.game.phase, old=old, new=self.model.value, reason=reply.stop_note)

    def dispatch(self, name: str, args: dict) -> Any:
        g = self.game
        match name:
            case "get_state":
                return g.full_state()
            case "apply_changes":
                changes, notes = self.check_changes(args["changes"])
                for note in notes:  # applied anyway, but likely a moderator mistake
                    g.log.error("moderator_warning", f"day {g.day} {g.phase}: {note}", changes=args["changes"])
                for c in changes:
                    if c["op"] in self.op_roles:
                        self.op_roles[c["op"]].apply_op(g, c)
                        continue
                    p = g.player(c["player"])  # every core op names a player
                    match c["op"]:
                        case "kill":
                            g.kill(p.name, c.get("cause", "killed"), by=c.get("by"), katana=c.get("katana", False))
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
                # e.g. set_tokens to 0 and then a prosecute op that spends the token too (game_20261009_232916_370745)
                for q in g.players:
                    for kind, n in q.tokens.items():
                        if n < 0:
                            q.tokens[kind] = 0
                            note = (f"{q.name}'s {kind} tokens went below 0, so they were set to 0: an op that "
                                    "spends a token already does it, so don't also set_tokens for it")
                            notes.append(note)
                            g.log.error("moderator_warning", f"day {g.day} {g.phase}: {note}", changes=args["changes"])
                return {"ok": True, **({"notes": notes} if notes else {})}
            case "random_choice":
                options, k = args["options"], args.get("k", 1)
                if not isinstance(options, list) or not isinstance(k, int) or isinstance(k, bool):
                    raise ValueError("options must be a list and k an integer")
                if not 0 < k <= len(options):
                    raise ValueError(f"k must be between 1 and the number of options ({len(options)})")
                return {"chosen": g.rng.sample(options, k)}
            case "tell":
                to = args["to"]
                if not isinstance(to, list) or not to or not isinstance(args["text"], str):
                    raise ValueError("to must be a non-empty list of player names, or ['all'], and text a string")
                if to == ["all"] and g.phase == "night":
                    g.pending_announcements.append(args["text"])  # read out at dawn
                elif to == ["all"]:
                    g.emit(f"Moderator: {args['text']}", cat=ANNOUNCEMENT, message=args["text"])
                else:
                    for n in to:
                        g.player(n)  # validate names
                    g.tell(to, args["text"])
                return {"ok": True}
            case "ask_player":
                p = g.player(args["player"])
                out = self.players.ask(p, f"The moderator asks: {args['question']}", ANSWER_SCHEMA,
                                       {"answer": ""}, step="ask_player")
                # Kept in the player's history, so later turns show what they chose.
                text = f"The moderator asked you: {args['question']} You answered: {out['answer']}"
                g.tell([p.name], text)
                return {"answer": out["answer"]}  # not the player's notepad
            case "end_phase":
                return {"ok": True}
            case "flag_issue":
                self.flags.append(args["issue"])
                g.log.write("moderator_flag", day=g.day, phase=g.phase, issue=args["issue"])
                return {"ok": True, "note": "Thanks; carry on."}
        raise ValueError(f"unknown tool {name!r}")

    def check_changes(self, changes: Any) -> tuple[list[dict], list[str]]:
        """Raises ValueError, before anything is applied, if any op is malformed. Returns the changes
        (optional fields set to null left out) and warnings about ones that apply but look wrong."""
        if not isinstance(changes, list):
            raise ValueError("changes must be a list of ops; nothing was applied")
        names = {p.name for p in self.game.players}
        notes, out = [], []
        killed: set[str] = set()
        for i, c in enumerate(changes):
            if not isinstance(c, dict) or c.get("op") not in self.ops:
                raise ValueError(f"change {i}: op must be one of {sorted(self.ops)}; nothing was applied")
            required, optional = self.ops[c["op"]]
            c = {k: v for k, v in c.items() if not (k in optional and v is None)}  # null means "not given"
            out.append(c)
            op, fields = c["op"], set(c) - {"op"}

            def bad(why: str, i: int = i, op: str = op) -> ValueError:
                return ValueError(f"change {i} ({op}): {why}; nothing was applied")
            if missing := required - fields:
                raise bad(f"missing {sorted(missing)}")
            if extra := fields - required - optional:
                notes.append(f"change {i} ({op}): ignored unknown fields {sorted(extra)}")
            if isinstance(c.get("by"), list):  # several fatal attackers (kill)
                if op != "kill" or not c["by"] or not all(isinstance(b, str) for b in c["by"]):
                    raise bad("by must be a player name" + (", or a list of names" if op == "kill" else ""))
                if unknown := [b for b in c["by"] if b not in names]:
                    raise bad(f"no player named {unknown[0]!r}")
            for key in ("player", "by"):
                if key in c and not isinstance(c[key], list) and c[key] not in names:
                    raise bad(f"no player named {c[key]!r}")
            if op == "kill":
                if "katana" in c and not isinstance(c["katana"], bool):
                    raise bad("katana must be true or false")
                if "cause" in c and not isinstance(c["cause"], str):
                    raise bad("cause must be text")
                if c["player"] in killed:  # the second kill would be dropped, with its cause and katana flag
                    raise bad(f"{c['player']} is already killed by an earlier change; make it one kill that names "
                              "every fatal cause (e.g. 'Katana and Serial Killer'), with by listing every killer "
                              "and katana=true if the Katana's attack was one of them")
                killed.add(c["player"])
                if not self.game.player(c["player"]).alive:
                    notes.append(f"change {i} (kill): {c['player']} is already dead, so it does nothing")
            if op == "set_tokens":
                if isinstance(c["value"], bool) or not isinstance(c["value"], (int, str)) \
                        or not re.fullmatch(r"-?\d+", str(c["value"]).strip()):
                    raise bad("value must be an integer")
                p = self.game.player(c["player"])
                if c["token"] not in p.tokens and c["token"] not in p.info.tokens:
                    notes.append(f"change {i} (set_tokens): {c['player']} ({p.role}) has no {c['token']!r} tokens"
                                 + (f" (they have {sorted(p.tokens)})" if p.tokens else ""))
            if op == "set_status":
                if not isinstance(c["key"], str):
                    raise bad("key must be text")
                if c["key"] in Status.SET_AT_SETUP:
                    raise bad(f"{c['key']!r} is set by code at setup and can't be changed")
                if isinstance(c.get("value"), str) and c["value"].strip().lower() in ("true", "false"):
                    raise bad("use JSON true/false for the value, not a string")
                if c["key"] not in CODE_STATUS_KEYS:
                    close = difflib.get_close_matches(c["key"], CODE_STATUS_KEYS, n=1)
                    if close:
                        notes.append(f"status key {c['key']!r} is not one code reads; did you mean {close[0]!r}?")
            if op in self.op_roles and (why := self.op_roles[op].check_op(self.game, c)):
                raise bad(why)
            if op == "set_last_will" and not isinstance(c["text"], str):
                raise bad("text must be text (an empty string for no will)")
            if op == "set_katana":
                p = self.game.player(c["player"])
                if not p.alive or p.info.alignment is not Alignment.EVIL:
                    raise bad(f"{p.name} is not a living Yakuza")
                if self.game.phase == "night":  # rules R8; game_20261010_013419_977337 passed it to a player dying that night
                    raise bad("code moves the Katana per the Yakuza vote and passes it on after the night's results "
                              "if its holder died (R8); don't set it at night")
        return out, notes
