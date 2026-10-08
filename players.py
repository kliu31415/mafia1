"""Player prompts, structured-output schemas, notepads, and the LLM calls for players."""

import json
from concurrent.futures import ThreadPoolExecutor

from roles import Alignment, ROLES
from state import Game, Player


NOTEPAD_WORDS = 300  # longer notepads are truncated


def word_count(text: str) -> int:
    return len(text.split())


def truncate_words(text: str, words: int) -> str:
    return " ".join(text.split()[:words]) + " [truncated]"


def nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def obj(**props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


STR = {"type": "string"}
BOOL = {"type": "boolean"}


def name_enum(names: list[str]) -> dict:
    return {"type": "string", "enum": names}


def day_turn_schema(game: Game, me: str, can_nominate: bool) -> dict:
    others = [n for n in game.alive_names() if n != me]
    props = {
        "thoughts": STR,  # private scratchpad, never shown to other players
        "public_message": nullable(STR),
        "private_messages": {"type": "array", "items": obj(to=name_enum(others), text=STR)},
    }
    if can_nominate:
        props["nominate"] = nullable(name_enum(game.alive_names()))
    return obj(**props)


VOTE_SCHEMA = obj(thoughts=STR, vote=BOOL)
LAST_WILL_SCHEMA = obj(last_will=STR)
ANSWER_SCHEMA = obj(answer=STR)


def night_action_schema(game: Game, p: Player) -> dict:
    """One generic shape for every role; the moderator interprets it using the rules."""
    names = game.alive_names()
    props = {
        "thoughts": STR,
        "act": BOOL,
        "target": nullable(name_enum(names)),
        "second_target": nullable(name_enum(names)),
        "guessed_role": nullable(name_enum(list(ROLES))),
        "tokens_to_spend": {"type": "integer"},
        "details": STR,  # anything else the action needs, e.g. "ignite" or a forged last will
    }
    if p.info.alignment is Alignment.EVIL:
        yakuza = [y.name for y in game.yakuza()]
        props["katana_vote_holder"] = name_enum(yakuza)
        props["katana_vote_target"] = nullable(name_enum(names))
    return obj(**props)


def role_briefing(game: Game, p: Player) -> str:
    lines = [f"You are {p.name} (seat {p.seat})."]
    if p.role == "Roleplayer":
        lines.append(f"Your role is {p.status['fake_role']}.")  # they're told the fake role
    else:
        lines.append(f"Your role is {p.role} ({p.info.alignment.value}).")
    if p.tokens:
        lines.append(f"Your tokens: {p.tokens}.")
    if p.info.alignment is Alignment.EVIL:
        team = ", ".join(f"{y.name} ({y.role})" for y in game.players if y.info.alignment is Alignment.EVIL)
        lines.append(f"Yakuza members: {team}. Katana holder: {game.katana_holder}.")
    if p.role == "Executioner":
        lines.append(f"Your target is {p.status['target']}.")
    return " ".join(lines)


def player_messages(game: Game, p: Player, rules: str, task: str, feedback_field: bool = False) -> list[dict]:
    order = ", ".join(f"{q.name}{'' if q.alive else ' (dead)'}" for q in game.players)
    system = (
        f"{rules}\n\n---\n\nYou are a player in this game. Your only goal is to win by your role's win "
        "condition. This is a social deduction game, so lying, bluffing, false role claims, misleading "
        "arguments and betraying people's trust are all legitimate tactics, and you should use them "
        "whenever they help you win. Nobody is harmed by in-game deception, and other players will "
        "deceive you too. Play to win, not to be agreeable or transparent. "
        f"Seating order (clockwise): {order}.\n{role_briefing(game, p)}"
    )
    notepad = p.notepad or "(empty)"
    user = (f"Everything you have seen so far:\n{game.history_for(p.name)}\n\n---\n\n"
            f"Your current last will (revealed to everyone if you die): {p.last_will or '(none yet)'}\n\n"
            f"Your private notepad (only you can see it; it carries over between turns):\n{notepad}\n\n"
            f"Every response has a 'notepad' field: set it to replace your notepad (max {NOTEPAD_WORDS} "
            "words; longer is truncated), or null to keep it as is. Use it for plans, suspicions and "
            "anything you want to remember.\n\n"
            + (FEEDBACK_NOTE if feedback_field else "")
            + f"---\n\n{task}")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


FEEDBACK_NOTE = ("Every response also has a 'feedback' field, outside the game: if a rule or this "
                 "interface is confusing, seems broken, or stops you doing something you want, say so "
                 "there briefly; otherwise leave it null. Nobody in the game sees it.\n\n")


def with_notepad(schema: dict) -> dict:
    """Adds the 'notepad' field every player response carries."""
    return {**schema, "properties": {**schema["properties"], "notepad": nullable(STR)},
            "required": [*schema["required"], "notepad"]}


class Players:
    """Asks player LLMs for decisions. Retries once on unparsable output, then uses a fallback."""

    def __init__(self, game: Game, client, rules: str, feedback_field: bool = False):
        self.game = game
        self.client = client
        self.rules = rules
        self.feedback_field = feedback_field

    def ask(self, p: Player, task: str, schema: dict, fallback: dict) -> dict:
        messages = player_messages(self.game, p, self.rules, task, self.feedback_field)
        schema = with_notepad(schema)
        if self.feedback_field:
            schema = {**schema, "properties": {**schema["properties"], "feedback": nullable(STR)},
                      "required": [*schema["required"], "feedback"]}
        for attempt in range(2):
            try:
                reply = self.client.chat(p.model, messages, schema=schema)
                out = json.loads(reply.content or "")
                self.game.log.write("player_call", player=p.name, model=p.model.value, task=task,
                                    output=out, reasoning=reply.reasoning, cost=reply.cost,
                                    usage=reply.usage)
                if isinstance(fb := out.pop("feedback", None), str) and fb.strip():
                    self.game.log.write("player_feedback", day=self.game.day, phase=self.game.phase,
                                        player=p.name, role=p.role, feedback=fb)
                if isinstance(note := out.pop("notepad", None), str):
                    p.notepad = truncate_words(note, NOTEPAD_WORDS) if word_count(note) > NOTEPAD_WORDS else note
                return out
            except (json.JSONDecodeError, RuntimeError) as e:
                self.game.log.write("player_error", player=p.name, attempt=attempt, error=str(e))
        return fallback

    def ask_many(self, jobs: list[tuple[Player, str, dict, dict]]) -> list[dict]:
        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(lambda j: self.ask(*j), jobs))
