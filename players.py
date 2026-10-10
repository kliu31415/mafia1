"""Player prompts, structured-output schemas, notepads, and the LLM calls for players."""

import json
import re
import time
from typing import Any
from concurrent.futures import ThreadPoolExecutor

import log_viewer
from events import RESULT
from llm import SHORT_REASON, LLMClient, LLMReply, answer_json, cache_block, rules_system, schema_errors
from roles import Alignment, ROLES, logic
from state import Game, Player
from tips import player_view


NOTEPAD_WORDS = 300  # longer notepads are truncated; the cap grows with the player count (notepad_words)


def notepad_words(game: Game) -> int:
    """Room for a short line per player plus plans: 300 words was tight with 12 players."""
    return max(NOTEPAD_WORDS, 25 * len(game.players) + 100)


# Scripts written without spaces (Chinese, Japanese, Thai, ...) count one word per character, and a run of
# letters with no space counts one word per LONG_WORD characters, so word caps and prices can't be dodged
# by leaving out spaces.
NO_SPACE_SCRIPTS = re.compile("[\u0e00-\u0eff\u1000-\u109f\u1780-\u17ff\u3040-\u30ff\u3400-\u4dbf"
                              "\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]")
LONG_WORD = 20


def token_words(token: str) -> int:
    chars = len(NO_SPACE_SCRIPTS.findall(token))
    rest = len(token) - chars
    return chars + -(-rest // LONG_WORD)


def word_count(text: str) -> int:
    return sum(token_words(t) for t in text.split())


def truncate_words(text: str, words: int) -> str:
    kept: list[str] = []
    for token in text.split():
        n = token_words(token)
        if n > words:  # cut inside the token: as many characters as the words left allow
            chars = rest = end = 0
            for ch in token:
                if NO_SPACE_SCRIPTS.match(ch):
                    chars += 1
                else:
                    rest += 1
                if chars + -(-rest // LONG_WORD) > words:
                    break
                end += 1
            if end:
                kept.append(token[:end])
            break
        kept.append(token)
        words -= n
    return " ".join(kept) + " [truncated]"


def nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def obj(**props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


STR = {"type": "string"}
BOOL = {"type": "boolean"}


def name_enum(names: list[str]) -> dict:
    return {"type": "string", "enum": names}


def day_turn_schema(game: Game, me: str, can_nominate: bool, own_turn: bool = True) -> dict:
    """own_turn: false when a Puppeteer writes this turn. They can set the puppet's claim, since it's
    public chat in effect (and a claim that never changes on puppeted days would expose the puppeting),
    but not the puppet's will."""
    others = [n for n in game.alive_names() if n != me]
    props = {
        "public_message": nullable(STR),
        "private_messages": {"type": "array", "items": obj(to=name_enum(others), text=STR)},
        "claim": nullable(STR),  # recorded in the public ledger's claims list (Game.claim_record)
    }
    if own_turn:
        props["last_will"] = nullable(STR)  # so a claim made today can be in the will by tonight
    if can_nominate:
        props["nominate"] = nullable(name_enum(game.alive_names()))
    return obj(**props)


VOTE_SCHEMA = obj(vote=BOOL)
LAST_WILL_SCHEMA = obj(last_will=STR)
ANSWER_SCHEMA = obj(answer=STR)


def night_action_schema(game: Game, p: Player) -> dict:
    """One generic shape for every role; the moderator interprets it using the rules."""
    names = game.alive_names()
    props = {
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


# Every in-game player call sends one answer schema (shared_schema) instead of its task's own, because the schema
# is part of the cached prompt prefix: Claude missed the whole cache, rules included, whenever a call's schema
# differed from the last one (a vote after day turns, a will after a night action, a target list one name
# shorter; Haiku test calls 2026-10-09). The task says which fields it reads (fields_note), and the answer
# is checked against the task's own schema (fit_answer), which still limits names to living players and so on.
# Text fields are plain strings with "" for none, and booleans aren't nullable, since Claude rejects a schema
# with more than 16 nullable or union-typed fields; only the name enums are nullable.
SHARED_FIELDS: dict[str, dict] = {
    "public_message": STR, "private_messages": {"type": "array", "items": {}}, "claim": STR, "last_will": STR,
    "nominate": {}, "vote": BOOL, "answer": STR, "act": BOOL, "target": {}, "second_target": {},
    "guessed_role": {}, "tokens_to_spend": {"type": "integer"}, "details": STR, "katana_vote_holder": {},
    "katana_vote_target": {}, "message": STR, "ready": BOOL,
}  # {} marks fields whose enum of names shared_schema fills in


def shared_schema(game: Game) -> dict:
    """The answer schema of every in-game player call (see SHARED_FIELDS). Fixed for the whole game."""
    names = name_enum([p.name for p in game.players])
    fields = {**SHARED_FIELDS, "private_messages": {"type": "array", "items": obj(to=names, text=STR)},
              "guessed_role": nullable(name_enum(list(ROLES)))}
    return obj(**{k: v or nullable(names) for k, v in fields.items()})


def fields_note(schema: dict) -> str:
    return (f"\n\nAnswer in these fields: {', '.join(schema['properties'])} (plus the ones every answer has). "
            "The other fields aren't used for this answer: leave them empty (null, \"\", false, 0 or []). In a "
            "text field, \"\" means none, the same as null.")


def fit_answer(out: dict, schema: dict) -> dict:
    """An answer to shared_schema cut down to the fields of its task's own schema, "" read as null where that
    schema allows null. Raises RuntimeError if it breaks that schema (e.g. a dead player as target)."""
    out = {k: v for k, v in out.items() if k in schema["properties"]}
    for k, v in out.items():
        if v == "" and {"type": "null"} in schema["properties"][k].get("anyOf", []):
            out[k] = None
    if errors := schema_errors(out, schema):
        raise RuntimeError(f"the answer doesn't fit this question: {'; '.join(errors[:5])}")
    return out


def tokens_left(p: Player) -> str:
    """e.g. "1 mortician token left", or "" for a player without tokens."""
    return ", ".join(f"{n} {kind} token{'' if n == 1 else 's'}" for kind, n in p.tokens.items()) + " left" \
        if p.tokens else ""


def role_briefing(game: Game, p: Player) -> str:
    lines = [f"You are {p.name} (seat {p.seat + 1} of {len(game.players)}, counting from 1)."]  # p.seat counts from 0
    lines.append(f"Your role is {logic(p.role).shown_role(p)}.")
    if p.tokens:
        lines.append(f"You have {tokens_left(p)}.")
    if p.info.alignment is Alignment.EVIL:
        # Teammates' tokens too: players lost track of their own and each other's (game_20261009_055144).
        team = ", ".join(f"{y.name} ({y.role}{', ' + tokens_left(y) if y.tokens and y.alive else ''}"
                         f"{'' if y.alive else ', dead'})" for y in game.players if y.info.alignment is Alignment.EVIL)
        lines.append(f"Yakuza members: {team}. Katana holder: {game.katana_holder}.")
    lines += logic(p.role).briefing(game, p)
    return " ".join(lines)


def player_messages(game: Game, p: Player, rules: str, task: str, feedback_field: bool = False,
                    context: str = "") -> list[dict]:
    """context: text several of this player's calls share after their own part (the post-game reveal), cached too."""
    # Ordered from most to least shared, for prompt caching (llm.cache_block): the rules (every call),
    # then the general instructions and tips (players with the same tips), then this player's briefing
    # and everything they saw in earlier phases (all their calls this phase). The system message holds
    # all of it because OpenAI caches only the system message.
    order = ", ".join(f"{q.name}{'' if q.alive else ' (dead)'}" for q in game.players)
    general = (
        "\n\n---\n\nYou are a player in this game. Your only goal is to win by your role's win "
        "condition. This is a social deduction game, so lying, bluffing, false role claims, misleading "
        "arguments and betraying people's trust are all legitimate tactics, and you should use them "
        "whenever they help you win. Nobody is harmed by in-game deception, and other players will "
        "deceive you too. Play to win, not to be agreeable or transparent. Think the situation through before "
        "each answer."
    )
    from day import budget_parameters  # day imports this module
    general += f"\n\n{budget_parameters()}"
    if p.tips and (tips := player_view(p.tips)):
        general += ("\n\n---\n\nTips from past games (lessons that players and moderators drew from earlier "
                    f"games of this variant; use your own judgment):\n\n{tips}")
    earlier, current = game.history_split(p.name)
    own = f"\n\n---\n\nSeating order (clockwise): {order}.\n{role_briefing(game, p)}"
    if earlier and not context:  # the post-game context has the whole game already
        own += ("\n\n---\n\nEverything you have seen in earlier phases (this phase's events are in the "
                "next message):\n" + "\n".join(earlier))
    system = rules_system(rules, [cache_block(general), cache_block(own),
                                  *([cache_block(f"\n\n---\n\n{context}")] if context else [])])
    notepad = p.notepad or "(empty)"
    nights = night_history(game, p)
    seen = "\n".join(current) or "(nothing yet)"
    user = (("" if context else f"What you have seen this phase so far:\n{seen}\n\n---\n\n" if earlier
             else f"Everything you have seen so far:\n{seen}\n\n---\n\n")
            + f"Public ledger (a summary of public facts so far):\n{game.public_ledger()}\n\n"
            + (f"Your night history (what you submitted each night, and your private results):\n{nights}\n\n"
               if nights else "")
            + f"Your current last will (revealed to everyone if you die): {p.last_will or '(none yet)'}\n\n"
            f"Your private notepad (only you can see it; it carries over between turns):\n{notepad}\n\n"
            f"Every response has a 'notepad' field: set it to replace your notepad (max {notepad_words(game)} "
            "words; longer is truncated), or leave it empty (\"\") to keep it as is. Use it for plans, "
            "suspicions and "
            "anything you want to remember. A useful habit: one brief line per other player (their claim, "
            "key votes or actions, and your current read), e.g. \"Bob: claims Sheriff, says Carol is Not "
            "Evil; voted Guilty on Dave D2; leaning Yakuza\". Keep lines short so they all fit.\n\n"
            f"{REASON_NOTE if p.model in SHORT_REASON else LONG_REASON_NOTE}\n\n"
            + (FEEDBACK_NOTE if feedback_field else "")
            + f"---\n\n{task}")
    return [system, {"role": "user", "content": user}]


def night_history(game: Game, p: Player) -> str:
    """p's submitted action each night and the moderator's private results to p, in one place (players
    lost track of them in long transcripts, and couldn't tell when nothing had been submitted)."""
    lines = [f"- Night {night}: you submitted {log_viewer.describe_action(actions[p.name])}"
             for night, actions in game.night_actions.items()
             if p.name in actions and not actions[p.name].get("automatic")]  # e.g. the Ex-Con isn't told its visit
    lines += [f"- Day {e.day} {e.phase}, result: {e.fields.get('message', e.text)}" for e in game.events
              if e.cat == RESULT and e.visible_to is not None and p.name in e.visible_to]
    return "\n".join(lines)


# A why for each answer, for the logs: many models' reasoning comes back only summarized or not at all
# (OpenAI's Sol and Luna return a summary on about 1 call in 8). A why after the decision rather than a
# "thoughts" scratchpad before it, which Anthropic's filter likely reads as distillation (gamelog v23).
# The short one, for models in llm.SHORT_REASON:
REASON_NOTE = ("Every response also has a 'reason' field: why you chose this answer, usually in one short "
               "sentence, or a few when the choice was complicated. It is kept in the game's records only; "
               "nobody in the game sees it.")
# The default: a longer why, since for many models it's the only record of their thinking (llm.SHORT_REASON
# lists the models that get the short one, and why). Asked as an explanation of a choice already made.
LONG_REASON_NOTE = ("Every response also has a 'reason' field: explain why you chose this answer, in a dense "
                    "paragraph of up to about 150 words (shorter is fine for simple choices): the options you "
                    "weighed and why you rejected them, your current reads on the players involved, what you "
                    "expect to happen next and your plan. No filler or restating the answer. It is kept in "
                    "the game's records only; nobody in the game sees it.")

FEEDBACK_NOTE = ("Every response also has a 'feedback' field, outside the game: if a rule or this "
                 "interface is confusing, seems broken, or stops you doing something you want, say so "
                 "there briefly; otherwise leave it empty. Nobody in the game sees it.\n\n")


def with_common_fields(schema: dict, feedback_field: bool, text: dict | None = None) -> dict:
    """Adds the fields every player response carries: notepad, reason and (with --feedback-field) feedback.
    text: the schema of notepad and feedback (plain STR in shared_schema, where "" means none)."""
    text = text or nullable(STR)
    extra = {"notepad": text, "reason": STR, **({"feedback": text} if feedback_field else {})}
    return {**schema, "properties": {**schema["properties"], **extra}, "required": [*schema["required"], *extra]}


# The kinds of player decisions, logged as "step" on player_call, player_error and player_fallback records.
STEPS = ("will", "day_turn", "trial_turn", "budget_revision", "puppet_nomination", "nomination_vote", "trial_vote",
         "yakuza_chat", "night_action", "katana_revote", "ask_player", "debrief", "lessons")


def blank(text: str) -> bool:
    """An answer meaning "nothing": "" or a written-out null (Haiku wrote "null" as feedback 27 times in
    game_20261009_152339_529912, since the shared schema types text fields as plain strings)."""
    return text.strip().strip(".").lower() in ("", "null", "none", "n/a")

class Players:
    """Asks player LLMs for decisions. Retries once on unparsable output, then uses a fallback."""

    def __init__(self, game: Game, client: LLMClient, rules: str, feedback_field: bool = False,
                 shared: bool = False):
        """shared: send shared_schema in place of each task's own (OpenRouter games, for prompt caching). Offline
        clients answer the task's own schema, so mock games and tests stay simple."""
        self.game = game
        self.client = client
        self.rules = rules
        self.feedback_field = feedback_field
        self.shared = shared

    def ask(self, p: Player, task: str, schema: dict, fallback: dict, *, step: str, rnd: int | None = None,
            context: str = "", shared_with: dict | None = None) -> dict:
        """step: what kind of decision this is (one of STEPS), and rnd the chat round if there is one; logged
        with day, phase and latency on every call record, so analysis never has to parse the task's wording.
        context: see player_messages. shared_with: a schema to send instead of shared_schema when this question's
        fields aren't in it (the post-game questions share one, feedback.POST_GAME_SCHEMA), for the same caching."""
        assert step in STEPS, step
        where = {"step": step, "day": self.game.day, "phase": self.game.phase,
                 **({"round": rnd} if rnd is not None else {})}
        wanted = with_common_fields(schema, self.feedback_field)
        common = shared_with or (shared_schema(self.game) if set(schema["properties"]) <= set(SHARED_FIELDS) else None)
        shared = self.shared and common is not None
        sent = with_common_fields(common, self.feedback_field, STR) if shared and common else wanted
        messages = player_messages(self.game, p, self.rules, task + (fields_note(schema) if shared else ""),
                                   self.feedback_field, context)
        for attempt in range(2):
            reply: LLMReply | None = None
            started = time.monotonic()
            # Only the call and the answer's checks are caught: a bad answer or a request that failed after its
            # retries is the model's (retried, then the fallback). Anything else is a bug in our code, which should
            # stop the game (resumable from its checkpoint) rather than silence this player for the rest of it.
            try:
                reply = self.client.chat(p.model, messages, schema=sent, effort=p.effort)
                latency = round(time.monotonic() - started, 2)
                out = answer_json(reply, sent)
                if shared:
                    out = fit_answer(out, wanted)
            except Exception as e:
                error = str(e) if isinstance(e, (json.JSONDecodeError, RuntimeError)) else f"{type(e).__name__}: {e}"
                self.game.log.error("player_error", f"{p.name} ({p.model.short}), attempt {attempt + 1}: {error}",
                                    player=p.name, model=p.model.value, attempt=attempt, **where, task=task,
                                    latency_s=round(time.monotonic() - started, 2),
                                    **({"output": reply.content, "reasoning": reply.reasoning, "cost": reply.cost,
                                        "usage": reply.usage} if reply else {}))  # a failed answer still costs
                if reply and reply.content:  # tell the model what was wrong, so the retry isn't the same answer
                    messages = messages + [{"role": "assistant", "content": reply.content},
                                           {"role": "user", "content": f"That answer couldn't be used ({error[:300]}). "
                                            "Answer again with JSON that follows the schema exactly."}]
                continue
            before = p.notepad
            after = before
            if isinstance(note := out.get("notepad"), str) and not blank(note):  # "" keeps it, like null
                cap = notepad_words(self.game)
                after = truncate_words(note, cap) if word_count(note) > cap else note
                if after != note:  # players didn't notice the cut (Frank, game_20261009_084630_739772)
                    self.game.emit(f"(Program note: your notepad was over {cap} words, so it was cut "
                                   f"to its first {cap}.)", [p.name])
            self.game.log.write("player_call", player=p.name, model=p.model.value, **where, task=task,
                                output=out, reasoning=reply.reasoning, cost=reply.cost,
                                usage=reply.usage, latency_s=latency, notepad_before=before,
                                notepad_after=after)
            if isinstance(fb := out.pop("feedback", None), str) and not blank(fb):
                self.game.log.write("player_feedback", day=self.game.day, phase=self.game.phase, step=step,
                                    player=p.name, role=p.role, feedback=fb)
            out.pop("notepad", None)
            out.pop("reason", None)  # logged above; game code and the moderator never see it
            p.notepad = after
            return out
        self.game.log.error("player_fallback", f"{p.name} ({p.model.short}) gave no valid answer, so the "
                            f"default was used ({json.dumps(fallback)[:100]}) for: {task[:100]}",
                            player=p.name, model=p.model.value, **where, task=task, fallback=fallback)
        # Tell the player, so they don't believe their own choice happened (Heidi thought she had saved a
        # token on purpose after a failed Night 1 answer, game_20261009_084630_739772).
        self.game.emit(f"(Program note: your answer to \"{truncate_words(task, 12)}\" couldn't be used because of a "
                       f"technical error, so the default was used instead: {json.dumps(fallback)}.)", [p.name])
        return fallback

    def ask_many(self, jobs: list[tuple[Player, str, dict, dict]], *, step: str, **kw: Any) -> list[dict]:
        """kw: ask's keyword arguments, the same for every job."""
        with ThreadPoolExecutor(max_workers=max(1, len(jobs))) as pool:  # a round waits for its slowest call
            return list(pool.map(lambda j: self.ask(*j, step=step, **kw), jobs))
