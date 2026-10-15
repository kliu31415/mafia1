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
from roles.base import MOD_NOTICES, acted_tonight
from state import Game
from traits import TraitLogic, kill_error, trait_logic
import variants


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
        "(value null deletes the key) | {op:'set_katana', player} (not at night: code moves the Katana per the Yakuza "
        "vote and passes it on "
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
    tool("tell", "Send a message. to = list of player names, or ['all'] for a public announcement "
         "(sent at night, it is read out at the start of the next Day).",
         to={"type": "array", "items": {"type": "string"}}, text={"type": "string"}),
    tool("ask_player", "Ask one player a question and get their free-text answer.",
         player={"type": "string"}, question={"type": "string"}),
    tool("record_visits", "Night only: every visit that happened tonight (rules R6), after role-blocks, as "
         "[visitor, target] pairs: a player who visited several players gets a pair for each, a self-visit is "
         "[X, X], and repeats are fine. Call it once each night before end_phase; calling it again replaces the "
         "list. Code uses it for visit-based roles; players never see it.",
         visits={"type": "array", "items": {"type": "array", "items": {"type": "string"}}}),
    tool("end_phase", "Finish this phase. The summary is private to the game log.",
         summary={"type": "string"}),
]

# apply_changes ops: op -> (required fields, optional fields). Roles add their own (RoleLogic.ops).
# Ops are checked before any is applied, so a malformed batch changes nothing and the moderator
# gets a clear error.
CORE_OPS: dict[str, tuple[set[str], set[str]]] = {
    "kill": ({"player"}, {"cause", "by", "katana", "divine"}),  # divine: a trait's note asks for it (Narrow Escape)
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
        self.op_roles: dict[str, RoleLogic | TraitLogic] = {}  # role or trait op -> what carries it out
        self.code_told: set[str] = set()  # players whose night result code delivers (RoleLogic.code_tells_user)
        self.tells_held: set[str] = set()  # ... whose tell() was held once this phase
        self.visits_reminded = False  # end_phase was refused once this night for a missing record_visits
        self.held_unsent: set[str] = set()  # held tells not followed by another tell to that player this phase
        self.held_reminded = False  # end_phase was refused once this night for held_unsent
        # (player, token kind) set by set_tokens / spent by a role op this phase, to catch a use counted twice
        self.tokens_set: set[tuple[str, str]] = set()
        self.tokens_spent: set[tuple[str, str]] = set()
        self.op_refused: set[str] = set()  # users of a role op that apply_changes refused this phase
        self.op_results: list[str] = []  # what this apply_changes call's role ops told the moderator (apply_op)
        docs = []
        for role in sorted({p.role for p in game.players}):
            for op, (required, optional, doc) in logic(role).ops.items():
                self.ops[op] = (required, optional)
                self.op_roles[op] = logic(role)
                docs.append(doc)
        for trait in sorted({t for p in game.players for t in p.traits}):  # e.g. Armed's shot (traits.py, R24)
            for op, (required, optional, doc) in trait_logic(trait).ops.items():
                self.ops[op] = (required, optional)
                self.op_roles[op] = trait_logic(trait)
                docs.append(doc)
        self.tools = ([MODERATOR_TOOLS[0], apply_changes_tool(docs)] + MODERATOR_TOOLS[1:]
                      + ([FLAG_TOOL] if flag_issues else []))

    def run_phase(self, instructions: str) -> list[dict]:
        """Runs the moderator until it ends the phase. Returns what it did: each tool call, its
        arguments and result, in order (for the night check)."""
        transcript: list[dict] = []
        self.code_told, self.tells_held, self.visits_reminded = set(), set(), False
        self.held_unsent, self.held_reminded = set(), False
        self.tokens_set, self.tokens_spent, self.op_refused = set(), set(), set()
        messages = [
            rules_system(self.rules, "You are the omniscient moderator of "
             "this game. Code stores the state and runs the day phase; you resolve what code can't "
             "by calling tools. Be exact about the rules. Never reveal hidden information except "
             "as the rules allow. A private result contains only what the rules say its recipient "
             "learns, worded neutrally: never explain why a result came out as it did (e.g. never "
             "mention the Katana, framing or defenses to an investigator), and never name an attacker "
             "or reveal roles beyond what the rules allow."
             + variants.moderator_note(self.game.rule_settings)
             + (" If a rule is ambiguous, or you lack a tool or information you need, call flag_issue and "
                "then continue with your best interpretation." if FLAG_TOOL in self.tools else "")),
            # Cached so the phase's later steps, which resend it, read it from the cache.
            {"role": "user", "content": [cache_block(f"{instructions}\n\nCurrent state, summarized:\n"
             f"{self.game.state_summary()}\n\nCurrent full state (call get_state to "
             f"refresh after changes):\n{json.dumps(self.game.full_state())}\n\nPublic history so far:\n"
             f"{self.game.history_for('__moderator_public__')}")]},
        ]
        # What the moderator is told this phase (the public history is left out: it is the log's public events).
        self.game.log.write("moderator_prompt", day=self.game.day, phase=self.game.phase, instructions=instructions,
                            state_summary=self.game.state_summary(), full_state=self.game.full_state())
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
                ended = ended or (name == "end_phase" and result.get("ok") is not False)
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

    def apply_change(self, c: dict) -> str | None:
        """Applies one checked apply_changes op. Returns a note for the moderator if it looks like a mistake."""
        g = self.game
        if c["op"] in self.op_roles:
            user = g.player(c["by"]) if c.get("by") in {q.name for q in g.players} else None
            before = dict(user.tokens) if user else {}
            if result := self.op_roles[c["op"]].apply_op(g, c):  # e.g. which attack a Kitsune's charm swallowed
                self.op_results.append(result)
            if self.op_roles[c["op"]].code_tells_user and "by" in c:  # not e.g. the attacks op
                self.code_told.add(c["by"])
            spent = {(user.name, k) for k, n in before.items() if user.tokens.get(k, 0) < n} if user else set()
            self.tokens_spent |= spent
            if both := sorted(spent & self.tokens_set):
                return self.double_spend_note(*both[0])
            return None
        p = g.player(c["player"])  # every core op names a player
        match c["op"]:
            case "kill":
                g.kill(p.name, c.get("cause", "killed"), by=c.get("by"), katana=c.get("katana", False))
            case "set_tokens":
                p.tokens[c["token"]] = int(c["value"])
                self.tokens_set.add((p.name, c["token"]))
                if (p.name, c["token"]) in self.tokens_spent:
                    return self.double_spend_note(p.name, c["token"])
            case "set_status":
                if c.get("value") is None:
                    p.status.pop(c["key"], None)
                else:
                    p.status[c["key"]] = c["value"]
            case "set_last_will":
                p.last_will = c["text"]
            case "set_katana":
                g.katana_holder = p.name
        return None

    def double_spend_note(self, name: str, kind: str) -> str:
        """A set_tokens and a role op that spends the same token, in one night: e.g. set_tokens 1 plus the prosecute
        op took a Prosecutor from 2 to 0 (from 1 to -1 in game_20261009_232916_370745)."""
        n = self.game.player(name).tokens.get(kind, 0)
        return (f"Check {name}'s {kind} tokens, now {n}: you set them with set_tokens, and an op that spends that "
                "token already took one off itself. If that counted the use twice, set_tokens them back.")

    def dispatch(self, name: str, args: dict) -> Any:
        g = self.game
        match name:
            case "get_state":
                return g.full_state()
            case "apply_changes":
                self.op_results = []
                try:
                    changes, notes = self.check_changes(args["changes"])
                except ValueError:
                    # Its user's result now comes from the moderator, if anyone (game_20261010_053523_23052: a
                    # refused profile op, then the hand-made result was held as if code gave it).
                    raw = args["changes"] if isinstance(args["changes"], list) else []
                    self.op_refused |= {c["by"] for c in raw if isinstance(c, dict) and c.get("op") in self.op_roles
                                        and isinstance(c.get("by"), str)}
                    raise
                for note in notes:  # applied anyway, but likely a moderator mistake
                    g.log.error("moderator_warning", f"day {g.day} {g.phase}: {note}", changes=args["changes"])
                for i, c in enumerate(changes):
                    try:
                        warning = self.apply_change(c)
                        self.op_results += g.role_state.pop(MOD_NOTICES, [])
                        if warning:
                            notes.append(warning)
                            g.log.error("moderator_warning", f"day {g.day} {g.phase}: {warning}",
                                        changes=args["changes"])
                    except Exception as e:  # a bug in our code, since the batch passed its checks
                        # The earlier ops stay applied: say so, or the moderator, used to "nothing was applied",
                        # would send them again (two kills, two spent tokens).
                        done = f"Changes 0-{i - 1} were applied, and this one may be partly" if i else \
                            "It may be partly applied"
                        raise RuntimeError(f"change {i} ({c['op']}) failed: {type(e).__name__}: {e}. {done}; call "
                                           "get_state before sending anything again") from e
                # e.g. set_tokens to 0 and then a prosecute op that spends the token too (game_20261009_232916_370745)
                for q in g.players:
                    for kind, n in q.tokens.items():
                        if n < 0:
                            q.tokens[kind] = 0
                            note = (f"{q.name}'s {kind} tokens went below 0, so they were set to 0: an op that "
                                    "spends a token already does it, so don't also set_tokens for it")
                            notes.append(note)
                            g.log.error("moderator_warning", f"day {g.day} {g.phase}: {note}", changes=args["changes"])
                return {"ok": True, **({"results": self.op_results} if self.op_results else {}),
                        **({"notes": notes} if notes else {})}
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
                    held = self.held_tell(to)
                    # Only the covered recipients are held: a Yakuza summary to the whole team went nowhere
                    # because one teammate had a code-given result, and was then split by hand.
                    if sent := [n for n in to if n not in held]:
                        g.tell(sent, args["text"])
                        self.held_unsent.difference_update(sent)
                    if held:
                        return {"ok": False, "note": (f"Sent to {', '.join(sent)}. " if sent else "")
                                + f"Not sent to {', '.join(held)}: code already gives them the result of their "
                                "action tonight (or, by the rules, nothing), so don't tell them about it. If this "
                                "message is about something else, such as an attack, a role-block or the Yakuza's "
                                f"actions, send it again to {', '.join(held)} only and it will go through."}
                return {"ok": True}
            case "ask_player":
                p = g.player(args["player"])
                out = self.players.ask(p, f"The moderator asks: {args['question']}", ANSWER_SCHEMA,
                                       {"answer": ""}, step="ask_player")
                # Kept in the player's history, so later turns show what they chose.
                text = f"The moderator asked you: {args['question']} You answered: {out['answer']}"
                g.tell([p.name], text)
                return {"answer": out["answer"]}  # not the player's notepad
            case "record_visits":
                return self.record_visits(args["visits"])
            case "end_phase":
                if g.phase == "night" and g.day not in g.night_visits:
                    if not self.visits_reminded:
                        self.visits_reminded = True
                        return {"ok": False, "note": "Not ended: call record_visits with tonight's visits first "
                                "(an empty list if nobody visited anyone), then end_phase."}
                    g.log.error("visits_missing", f"the moderator ended night {g.day} without record_visits, so "
                                "visit-based roles have no visits tonight", day=g.day)
                # A held tell can carry more than the action's result: "Your Katana attack on Grace succeeded" to a
                # Diviner holder was held and never resent (game_20261010_102519_201).
                if self.held_unsent and not self.held_reminded:
                    self.held_reminded = True
                    return {"ok": False, "note": f"Not ended: your tell() to {', '.join(sorted(self.held_unsent))} "
                            "was held and not sent. If it said anything besides the result of their own action "
                            "(e.g. whether their attack succeeded, a role-block, that they died), send that part "
                            "again now; otherwise call end_phase again."}
                return {"ok": True}
            case "flag_issue":
                self.flags.append(args["issue"])
                g.log.write("moderator_flag", day=g.day, phase=g.phase, issue=args["issue"])
                return {"ok": True, "note": "Thanks; carry on."}
        raise ValueError(f"unknown tool {name!r}")

    def record_visits(self, visits: Any) -> dict:
        g = self.game
        if g.phase != "night":
            raise ValueError("record_visits is for the night's visits; nothing was recorded")
        if not isinstance(visits, list) or not all(isinstance(v, list) and len(v) == 2 and all(isinstance(n, str)
                                                    for n in v) for v in visits):
            raise ValueError("visits must be a list of [visitor, target] pairs of player names; nothing was recorded")
        names = {p.name for p in g.players}
        for n in (n for v in visits for n in v):
            if n not in names:
                raise ValueError(f"no player named {n!r}; nothing was recorded")
            if not acted_tonight(g, g.player(n)):
                raise ValueError(f"{n} wasn't alive at the start of the night; nothing was recorded")
        g.night_visits[g.day] = [list(v) for v in visits]
        g.log.write("visits", day=g.day, visits=visits)
        return {"ok": True, "recorded": len(visits)}

    def held_tell(self, to: list[str]) -> list[str]:
        """Recipients of a night tell() whose result code delivers, the first time each is told this phase."""
        g = self.game
        if g.phase != "night":
            return []
        acted = g.night_actions.get(g.day, {})
        # A player who died tonight is being told about the attack, not their action's result.
        held = [n for n in to if n not in self.tells_held and logic(g.player(n).role).code_tells_user
                and (n in self.code_told or acted.get(n, {}).get("act") and n not in self.op_refused)
                and g.player(n).alive]
        if held:
            self.tells_held.update(held)
            self.held_unsent.update(held)
            g.log.write("tell_held", day=g.day, players=held)
        return held

    def check_changes(self, changes: Any) -> tuple[list[dict], list[str]]:
        """Raises ValueError, before anything is applied, if any op is malformed. Returns the changes
        (optional fields set to null left out) and warnings about ones that apply but look wrong."""
        if not isinstance(changes, list):
            raise ValueError("changes must be a list of ops; nothing was applied")
        names = {p.name for p in self.game.players}
        notes, out = [], []
        killed: set[str] = set()
        acted: set[tuple[str, str]] = set()  # (role op, user)
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
                if key in c and not isinstance(c[key], list) and c[key] not in names \
                        and not (c[key] is None and key not in required):  # an optional name may be null
                    raise bad(f"no player named {c[key]!r}")
            if op == "kill":
                if "katana" in c and not isinstance(c["katana"], bool):
                    raise bad("katana must be true or false")
                if "divine" in c and not isinstance(c["divine"], bool):
                    raise bad("divine must be true or false")
                if "cause" in c and not isinstance(c["cause"], str):
                    raise bad("cause must be text")
                if c["player"] in killed:  # the second kill would be dropped, with its cause and katana flag
                    raise bad(f"{c['player']} is already killed by an earlier change; make it one kill that names "
                              "every fatal cause (e.g. 'Katana and Serial Killer'), with by listing every killer "
                              "and katana=true if the Katana's attack was one of them")
                if error := kill_error(self.game, c):  # e.g. a Shaky player's Katana attack (rules R24)
                    raise bad(error)
                killed.add(c["player"])
                if not self.game.player(c["player"]).alive:
                    notes.append(f"change {i} (kill): {c['player']} is already dead, so it does nothing")
            if op == "set_tokens":
                if isinstance(c["value"], bool) or not isinstance(c["value"], (int, str)) \
                        or not re.fullmatch(r"-?\d+", str(c["value"]).strip()):
                    raise bad("value must be an integer")
                p = self.game.player(c["player"])
                if p.info.token_cap and int(str(c["value"]).strip()) > p.info.tokens.get(c["token"], 0):
                    raise bad(f"{p.name}'s {c['token']} tokens can never go above {p.info.tokens.get(c['token'], 0)} "
                              f"(rules: {p.role})")
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
            # A player submits one night action. The checks above don't see the batch's earlier ops, so a second
            # one would get past "one a night" limits and spend a second token (Talent Agent, Ballot Stuffer).
            if op in self.op_roles and isinstance(c.get("by"), str):
                if (op, c["by"]) in acted:
                    raise bad(f"{c['by']} already has a {op} op in this batch; a player's action is recorded once")
                acted.add((op, c["by"]))
            if op == "set_last_will" and not isinstance(c["text"], str):
                raise bad("text must be text (an empty string for no will)")
            if op == "set_katana":
                p = self.game.player(c["player"])
                if not p.alive or p.info.alignment is not Alignment.EVIL:
                    raise bad(f"{p.name} is not a living Yakuza")
                # rules R8; game_20261010_013419_977337 passed it to a player dying that night
                if self.game.phase == "night":
                    raise bad("code moves the Katana per the Yakuza vote and passes it on after the night's results "
                              "if its holder died (R8); don't set it at night")
        return out, notes
