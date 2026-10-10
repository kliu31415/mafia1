"""Feedback from the models themselves: post-game debriefs, an outside log review, a rules quiz,
and a report collecting everything (including moderator flags and in-game feedback) per game."""

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from events import RESULT
from llm import LLMClient, Model, ModelSpec, answer_json, rules_system
from texts import describe_action
from moderator import Moderator
from players import STR, Players, obj
from records import read_records
from state import Game
from texts import player_view
from tips import print_alert

DEBRIEF_QUESTIONS = {
    "confusing_rules": "Which rules, or parts of your instructions, were confusing or ambiguous?",
    "missing_information": "What information did you need but not have, or find hard to keep track of?",
    "wanted_but_couldnt": "What did you want to do that the game or interface didn't let you do?",
    "bugs_or_oddities": "Did anything seem broken, inconsistent with the rules, or strange?",
    "suggestions": "What would you change about the game or the interface?",
}
DEBRIEF_SCHEMA = obj(**dict.fromkeys(DEBRIEF_QUESTIONS, STR))
ISSUE_KINDS = ["rules ambiguity", "harness bug", "moderator error", "prompt problem", "player confusion", "other"]
REVIEW_SCHEMA = obj(issues={"type": "array", "items": obj(
    kind={"type": "string", "enum": ISSUE_KINDS},
    severity={"type": "string", "enum": ["high", "medium", "low"]},
    description=STR)})


def night_replay(game: Game) -> str:
    """What happened each night, now that it can be revealed: everyone's submitted actions and every
    private result (players asked for this after games, to understand failed attacks and so on)."""
    lines = []
    for night, actions in game.night_actions.items():
        lines.append(f"Night {night} actions:")
        lines += [f"- {name} ({game.player(name).role}): {describe_action(a)}" for name, a in actions.items()]
        lines += [f"- Result to {', '.join(sorted(e.visible_to or []))}: {e.fields.get('message', e.text)}"
                  for e in game.events if e.cat == RESULT and e.day == night and e.phase == "night"]
    return "\n".join(lines) or "(no nights were played)"


def when(r: dict) -> str:
    """When a player_feedback record was written: answers to the post-game questions carry the last day's
    number, which read as in-game reports from dead players (game_20261009_152339_529912)."""
    return "After the game" if r.get("step") in ("debrief", "lessons") else f"Day {r['day']} {r['phase']}"


def full_log(game: Game) -> str:
    """Every event, with who could see it. Players get it after the game too, so feedback and lessons
    from players who died early (or never saw the other side's chat) cover the whole game."""
    return "\n".join(f"[Day {e.day} {e.phase}] "
                     + ("" if e.visible_to is None else f"(to {', '.join(sorted(e.visible_to))}) ")
                     + e.text for e in game.events
                     if not e.notice)  # "X sent Y a private message" would repeat the message shown above it


def post_game_context(game: Game) -> str:
    """The reveal every post-game player question starts from. It goes in a cached part of the prompt
    (Players.ask's context), so the debrief and lessons calls share it."""
    roles = ", ".join(f"{p.name}: {p.role}" for p in game.players)
    return (f"The game is over. {game.winners_line()} Everyone's roles: {roles}.\n\n"
            f"The whole game, now revealed (every event, with who could see it):\n{full_log(game)}\n\n"
            f"What happened each night (now revealed):\n{night_replay(game)}")


def debrief_task(game: Game, with_reveal: bool = True) -> str:
    """with_reveal: start with the roles and night replay (the moderator's debrief, which has its own log)."""
    roles = ", ".join(f"{p.name}: {p.role}" for p in game.players)
    questions = "\n".join(f"- {k}: {q}" for k, q in DEBRIEF_QUESTIONS.items())
    return ((f"The game is over. {game.winners_line()} Everyone's roles: {roles}.\n\n"
             f"What happened each night (now revealed):\n{night_replay(game)}\n\n" if with_reveal else "")
            + "We're improving this game and the program that runs it. Out of character now, answer from "
            "your own experience of playing it. Be specific and concrete, and write 'none' where you have "
            f"nothing to say.\n{questions}")


POST_GAME_SECTIONS = {  # "section" records: the log views start a titled section for each post-game step
    "debrief": "Post-game feedback: rules, interface and bugs (debrief)",
    "lessons": "Post-game lessons: tips players wish they'd known, and how past tips went",
    "strategy": "Moderator strategy review",
    "review": "Outside log review (rules and bugs)",
}


def run_debrief(game: Game, players: Players, moderator: Moderator) -> None:
    game.log.write("section", title=POST_GAME_SECTIONS["debrief"])
    task = debrief_task(game, with_reveal=False)  # the reveal is in the context
    fallback = dict.fromkeys(DEBRIEF_QUESTIONS, "")
    outs = players.ask_many([(p, task, DEBRIEF_SCHEMA, fallback) for p in game.players], step="debrief",
                            context=post_game_context(game), shared_with=POST_GAME_SCHEMA)
    for p, out in zip(game.players, outs):
        game.log.write("debrief", who=p.name, role=p.role, model=p.model.value, answers=out)

    events = full_log(game)
    flags = "\n".join(f"- {f}" for f in moderator.flags) or "(none)"
    messages = [
        rules_system(moderator.rules, "You were the moderator of this game."),
        {"role": "user", "content": f"Everything that happened (with who could see each event):\n{events}\n\n"
         f"Issues you flagged during the game:\n{flags}\n\n{debrief_task(game)}\nAnswer as the moderator: also cover "
         "rules you had to interpret, and tools or state you were missing."},
    ]
    reply = moderator.client.chat(moderator.model, messages, schema=DEBRIEF_SCHEMA, schema_name="debrief",
                                  effort=moderator.effort)
    game.log.write("debrief", who="moderator", role="Moderator", model=moderator.model.value,
                   answers=answer_json(reply, DEBRIEF_SCHEMA), cost=reply.cost, usage=reply.usage)


def run_review(game: Game, client: LLMClient, model: Model, rules: str, text_log: Path,
               effort: str | None = None) -> None:
    """An outside model reads the whole human-readable log and lists problems it sees."""
    game.log.write("section", title=POST_GAME_SECTIONS["review"])
    messages = [
        rules_system(rules, "You review logs of LLMs playing this game, which "
         "is run by a program plus an LLM moderator. Find problems: rules ambiguities, program bugs, "
         "moderator mistakes, prompt problems, and places players seemed confused about the rules or "
         "interface. Ignore ordinary bad strategy. This text log leaves out the answers to the post-game "
         "questions (debrief, lessons, strategy review), which are stored separately, so those sections "
         "look empty."),
        {"role": "user", "content": f"Game log:\n{text_log.read_text(encoding='utf-8')}"},
    ]
    reply = client.chat(model, messages, schema=REVIEW_SCHEMA, schema_name="review", effort=effort)
    game.log.write("review", model=model.value, issues=answer_json(reply, REVIEW_SCHEMA)["issues"],
                   cost=reply.cost, usage=reply.usage)


LESSON_TOPICS = ["rules and mechanics", "deduction", "deception", "persuasion and voting",
                 "night actions", "coordination", "speaking budget", "other"]
LESSONS_SCHEMA = obj(lessons={"type": "array", "items": obj(
    topic={"type": "string", "enum": LESSON_TOPICS},
    applies_to=STR,  # a role, faction, or "everyone"
    tip=STR)})
# Feedback on the tips from past games (tips.py) a player was given: the ones that mattered this game.
TIPS_FEEDBACK = {"type": "array", "items": obj(
    tip=STR,  # the tip, quoted or closely paraphrased
    verdict={"type": "string", "enum": ["helped", "hurt", "wrong"]},  # wrong: false or against the rules
    why=STR)}
TIPS_FEEDBACK_TASK = ("\n\nYou were also given tips from past games (in your instructions). Which of them went "
                      "especially well or badly for you or others this game? List only tips that clearly "
                      "mattered (or none): helped, hurt (followed it and it backfired, or it was predictable "
                      "to opponents), or wrong (it is false or contradicts the rules), and why, concretely.")


def with_tips_feedback(schema: dict) -> dict:
    return {**schema, "properties": {**schema["properties"], "tips_feedback": TIPS_FEEDBACK},
            "required": [*schema["required"], "tips_feedback"]}


# The one schema post-game player questions send in live games (Players.ask shared_with), so the debrief and
# lessons calls share a cache: a different schema misses the whole cached prompt (see players.shared_schema).
POST_GAME_SCHEMA = obj(**DEBRIEF_SCHEMA["properties"], **LESSONS_SCHEMA["properties"], tips_feedback=TIPS_FEEDBACK)


def run_lessons(game: Game, players: Players, lessons_file: Path) -> None:
    """Each player lists tips and tricks they wish they'd known, and players given tips from past
    games (tips.py) say which of those went well or badly. Saved to the game log; lessons are also
    appended to `lessons_file` (one JSON object per tip, across all games) for later analysis."""
    game.log.write("section", title=POST_GAME_SECTIONS["lessons"])
    task = ("If you played this game again, what tips and tricks do you wish you'd known? "
            "Give 1-5 concrete, reusable lessons (not a recap of this game), each with a topic and who it "
            "applies to (a role, a faction, or 'everyone').")
    outs = players.ask_many([(p, task + TIPS_FEEDBACK_TASK, with_tips_feedback(LESSONS_SCHEMA),
                              {"lessons": [], "tips_feedback": []})
                             if p.tips else (p, task, LESSONS_SCHEMA, {"lessons": []}) for p in game.players],
                            step="lessons", context=post_game_context(game), shared_with=POST_GAME_SCHEMA)
    lessons_file.parent.mkdir(parents=True, exist_ok=True)
    with lessons_file.open("a", encoding="utf-8") as f:
        for p, out in zip(game.players, outs):
            game.log.write("lessons", who=p.name, role=p.role, model=p.model.value, lessons=out["lessons"],
                           **({"tips_feedback": out.get("tips_feedback", [])} if p.tips else {}))
            for lesson in out["lessons"]:
                f.write(json.dumps({"game": game.log.path.stem, "source": "player", "player": p.name,
                                    "role": p.role, "model": p.model.value,
                                    "won": p.name in (game.winners or []), **lesson}) + "\n")


STRATEGY_SCHEMA = obj(summary=STR, lessons={"type": "array", "items": obj(
    topic={"type": "string", "enum": LESSON_TOPICS},
    applies_to=STR,  # a role, faction, or "everyone"
    tip=STR,
    evidence=STR)})  # the moment in this game that shows it


def run_strategy_review(game: Game, client: LLMClient, model: Model, rules: str, text_log: Path,
                        lessons_file: Path, effort: str | None = None) -> None:
    """The moderator model, which saw everything, reads the whole log and draws general strategy
    lessons: things to do and to avoid, per role or faction. Saved to the game log and appended to
    `lessons_file` alongside the players' lessons (source "moderator"). If some players had tips from
    past games (tips.py), it also says which of those tips went especially well or badly."""
    game.log.write("section", title=POST_GAME_SECTIONS["strategy"])
    with_tips = [p for p in game.players if p.tips]
    sheets: dict[str, list[str]] = {}  # tips text -> who had it
    for p in with_tips:
        sheets.setdefault(p.tips, []).append(p.name)
    tips_task = ("" if not with_tips else
                 "\n\nSome players were given tips from past games. Also list the tips that clearly mattered "
                 "this game, for better or worse: helped, hurt (followed and it backfired, or opponents exploited "
                 "it), or wrong (false or against the rules), and why, citing what happened. Leave it empty if "
                 "none mattered."
                 + "".join(f"\n\nTips given to {', '.join(names)}:\n\n{player_view(text)}"
                           for text, names in sheets.items()))
    messages = [
        rules_system(rules, "You moderated this game and saw everything, "
         "including hidden events and night actions. Now analyze it as a strategy coach."),
        {"role": "user", "content": f"Game log:\n{text_log.read_text(encoding='utf-8')}\n\n"
         "Write a short summary of why the game went the way it did (the decisive plays and mistakes), "
         "then 3-8 general strategy lessons: things to do or to avoid that would help a player of this "
         "game in future games, not a recap. Each lesson has a topic, who it applies to (a role, a "
         "faction, or 'everyone'), the tip, and the evidence: the moment in this game that shows it. "
         "Cover good and evil play, and ignore problems with the rules or the program." + tips_task},
    ]
    schema = with_tips_feedback(STRATEGY_SCHEMA) if with_tips else STRATEGY_SCHEMA
    reply = client.chat(model, messages, schema=schema, schema_name="strategy_review", effort=effort)
    out = answer_json(reply, schema)
    lessons = out.get("lessons", [])
    game.log.write("strategy_review", model=model.value, summary=out.get("summary", ""), lessons=lessons,
                   cost=reply.cost, usage=reply.usage,
                   **({"tips_feedback": out.get("tips_feedback", [])} if with_tips else {}))
    lessons_file.parent.mkdir(parents=True, exist_ok=True)
    with lessons_file.open("a", encoding="utf-8") as f:
        for lesson in lessons:
            f.write(json.dumps({"game": game.log.path.stem, "source": "moderator", "player": None,
                                "role": "Moderator", "model": model.value, "won": None, **lesson}) + "\n")


def write_report(jsonl_path: Path) -> Path | None:
    """Collect errors, night checks, moderator flags, in-game feedback, debriefs, lessons, the strategy review
    and the review into
    <game>_feedback.md."""
    records, unreadable = read_records(jsonl_path)
    flags = [r for r in records if r["kind"] == "moderator_flag"]
    in_game = [r for r in records if r["kind"] == "player_feedback"]
    debriefs = [r for r in records if r["kind"] == "debrief"]
    reviews = [r for r in records if r["kind"] == "review"]
    lessons = [r for r in records if r["kind"] == "lessons"]
    strategy = [r for r in records if r["kind"] == "strategy_review"]
    checks = sorted((r for r in records if r["kind"] == "night_check"), key=lambda r: r["night"])
    errors = [r for r in records if r.get("alert")]
    if not (unreadable or errors or flags or in_game or debriefs or reviews or lessons or strategy or checks):
        return None
    out = [f"# Feedback for {jsonl_path.stem}\n"]
    if errors or unreadable:
        counts = Counter(r["kind"] for r in errors)
        if unreadable:
            counts["unreadable log line"] = unreadable
        out.append("## Errors (things to fix)\n")
        out.append(", ".join(f"{n} {k}" for k, n in counts.most_common()) + "\n")
        shown: Counter[tuple[str, str]] = Counter()
        for r in errors:  # the first few of each kind per player; the JSONL has them all (alert: true)
            source = (r["kind"], r.get("player", ""))
            shown[source] += 1
            if shown[source] <= 3:
                out.append(f"- {r['kind']}: {r['error']}")
        out.append("")
    if checks:
        out.append(f"## Night checks (judge: {checks[0]['judge'].split('/')[-1]})\n")
        for r in checks:
            out.append(f"- **Night {r['night']}: {r['verdict']}**" + (f" ({r['error']})" if r.get("error") else ""))
            out += [f"  - {i['severity']}, {i['rule']}, {i['kind']}: {i['description']}" for i in r["issues"]]
        out.append("")
    if flags:
        out.append("## Moderator flags (during the game)\n")
        out += [f"- Day {r['day']} {r['phase']}: {r['issue']}" for r in flags]
        out.append("")
    if in_game:
        out.append("## In-game player feedback\n")
        out += [f"- {when(r)}, {r['player']} ({r['role']}): {r['feedback']}" for r in in_game]
        out.append("")
    if debriefs:
        out.append("## Post-game debriefs\n")
        for r in debriefs:
            out.append(f"### {r['who']} ({r['role']}, {r['model'].split('/')[-1]})\n")
            for k, q in DEBRIEF_QUESTIONS.items():
                answer = (r["answers"].get(k) or "").strip()
                if answer and answer.lower().rstrip(".") != "none":
                    out.append(f"- **{q}** {answer}")
            out.append("")
    if lessons:
        out.append("## Lessons players wish they'd known\n")
        for r in lessons:
            out += [f"- **{r['who']} ({r['role']}, {r['model'].split('/')[-1]})**, {x['topic']}, for "
                    f"{x['applies_to']}: {x['tip']}" for x in r["lessons"]]
        out.append("")
    for r in strategy:
        out.append(f"## Moderator strategy review ({r['model'].split('/')[-1]})\n")
        out.append(r["summary"].strip() + "\n")
        out += [f"- **{x['topic']}, for {x['applies_to']}:** {x['tip']} _({x['evidence']})_" for x in r["lessons"]]
        out.append("")
    tips_feedback = [(r.get("who", "moderator"), r.get("role", "Moderator"), r["model"], x)
                     for r in lessons + strategy for x in r.get("tips_feedback", [])]
    if tips_feedback:
        out.append("## How the tips from past games went\n")
        out += [f"- **{x['verdict']}**, {who} ({role}, {model.split('/')[-1]}): {x['tip']} _({x['why']})_"
                for who, role, model, x in tips_feedback]
        out.append("")
    for r in reviews:
        out.append(f"## Outside review ({r['model'].split('/')[-1]})\n")
        order = {"high": 0, "medium": 1, "low": 2}
        out += [f"- **{i['severity']}, {i['kind']}:** {i['description']}"
                for i in sorted(r["issues"], key=lambda i: order.get(i["severity"], 3))]
        out.append("")
    path = jsonl_path.with_name(jsonl_path.stem + "_feedback.md")
    path.write_text("\n".join(out), encoding="utf-8", errors="replace")
    return path


# ---------------------------------------------------------------------------------------------
# Rules quiz
# ---------------------------------------------------------------------------------------------

QUIZ: list[tuple[str, str]] = [
    ("A Medic chooses Strong protection (spending a token) but is role-blocked that night. Does the Medic "
     "lose the token, and does the protection happen?",
     "No token is used and nothing happens; a role-blocked action is as if they chose not to act."),
    ("During the day, A sends B a private message. Who learns what?",
     "Everyone sees that A sent B a private message; only A and B see its contents."),
    ("A Standard Attack hits a player who has Standard Defense. Do they die?",
     "No. An attack kills only if its level is strictly higher than the defense."),
    ("On Day 3 the last Yakuza is executed, leaving only Village players and a Jester alive. What happens next?",
     "The game ends immediately (it's checked after every death). The Village wins; the Jester, still alive, loses."),
    ("A Cardinal dies at night. When does their effect happen, and to whom?",
     "At the end of that night, after its other actions, a random living Good player is dealt a Divine Attack."),
    ("The Yakuza holding the Katana at the end of the night is investigated by a Sheriff that night. Result?",
     "Not Evil."),
    ("A Fabricator frames player X. A Lookout watches X that night. Does the Lookout see the Fabricator?",
     "Yes. Framing (and forging) count as visits."),
    ("How does voting on a nomination work, and when do players see each other's votes?",
     "Everyone votes simultaneously (the nominator votes Yes automatically); all votes are revealed together "
     "afterwards; it passes with strictly more than half Yes."),
    ("An Executioner's target is killed by the Katana at night. What happens to the Executioner?",
     "They become a Jester."),
    ("Is the list of roles in the game public?", "No."),
    ("A Jester is hanged, with 4 players voting Guilty. What happens?",
     "The Jester wins. The following night, a random player who voted Guilty is dealt a Divine Attack (Astral)."),
    ("Three nominations reach trial today and all three end Innocent. What happens?", "The day ends."),
]
QUIZ_GRADE_SCHEMA = obj(results={"type": "array", "items": obj(
    question={"type": "integer"}, correct={"type": "boolean"}, note=STR)})


def quiz_answer(client: LLMClient, spec: ModelSpec, messages: list[dict], schema: dict, name: str, what: str,
                problems: list[str]) -> dict:
    """One quiz call's JSON answer. A failed call or a broken answer is printed as an ALERT, listed in the
    results' errors and treated as no answers (the quiz has no game log for GameLog.error), so one failure
    doesn't lose the other models' paid answers."""
    try:
        return answer_json(client.chat(spec.model, messages, schema=schema, schema_name=name, effort=spec.effort),
                           schema)
    except Exception as e:
        problems.append(f"{what}: {type(e).__name__}: {e}")
        print_alert("quiz_error", f"{what}: {type(e).__name__}: {e}")
        return {}


def run_quiz(client: LLMClient, specs: list[ModelSpec], grader: ModelSpec, rules: str, out_dir: Path) -> Path:
    """Ask each model the quiz questions given only the rules, then have `grader` mark the answers
    against the reference answers. Wrong or split answers point at rules that need clarifying."""
    questions = "\n".join(f"{i + 1}. {q}" for i, (q, _) in enumerate(QUIZ))
    # One named field per question, so an answer can't slip into the wrong slot.
    answer_schema = obj(**{f"q{i + 1}": STR for i in range(len(QUIZ))})
    table: dict[str, list[dict]] = {}
    answers_by_model: dict[str, list[str]] = {}
    problems: list[str] = []
    for spec in dict.fromkeys(specs):
        parsed = quiz_answer(client, spec, [
            rules_system(rules, "Answer questions about the rules above."),
            {"role": "user", "content": f"Answer each question in one or two sentences, in order:\n{questions}"},
        ], answer_schema, "quiz", f"{spec}'s answers", problems)
        answers = [parsed.get(f"q{i + 1}", "") for i in range(len(QUIZ))]
        answers_by_model[str(spec)] = answers
        marking = "\n".join(f"{i + 1}. Q: {q}\n   Reference: {ref}\n"
                            f"   Answer: {answers[i] if i < len(answers) else '(none)'}"
                            for i, (q, ref) in enumerate(QUIZ))
        table[str(spec)] = quiz_answer(client, grader, [
            {"role": "user", "content": "Mark each answer correct if it gets the reference's main point right and "
             "contradicts nothing in it; leaving out a minor detail is fine. Otherwise mark it incorrect. "
             "Give a short note either way, and say if the answer reveals a misreading of the rules."
             f"\n\n{marking}"},
        ], QUIZ_GRADE_SCHEMA, "quiz_grades", f"grading {spec}", problems).get("results", [])

    out = ["# Rules quiz\n", f"Graded by {grader}.\n"]
    if problems:
        out += ["## Errors (things to fix)\n"] + [f"- {p}" for p in problems] + [""]
    out += ["| # | Question | " + " | ".join(table) + " |",
            "|---|---|" + "---|" * len(table)]
    for i, (q, _) in enumerate(QUIZ):
        cells = []
        for m in table:
            r = next((x for x in table[m] if x.get("question") == i + 1), None)
            cells.append("?" if r is None else ("✓" if r["correct"] else "✗"))
        out.append(f"| {i + 1} | {q} | " + " | ".join(cells) + " |")
    out.append("\n## Wrong answers\n")
    for m, results in table.items():
        for r in results:
            if not r.get("correct") and 1 <= r.get("question", 0) <= len(QUIZ):
                i = r["question"] - 1
                answer = answers_by_model[m][i] if i < len(answers_by_model[m]) else "(none)"
                out.append(f"- **Q{i + 1}, {m}:** {answer} *({r['note']})*")
    path = out_dir / f"quiz_{datetime.now():%Y%m%d_%H%M%S}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8", errors="replace")
    return path
