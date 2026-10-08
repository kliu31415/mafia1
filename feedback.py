"""Feedback from the models themselves: post-game debriefs, an outside log review, a rules quiz,
and a report collecting everything (including moderator flags and in-game feedback) per game."""

import json
from datetime import datetime
from pathlib import Path

from llm import LLMClient, Model, ModelSpec
from moderator import Moderator
from players import STR, Players, obj
from state import Game

DEBRIEF_QUESTIONS = {
    "confusing_rules": "Which rules, or parts of your instructions, were confusing or ambiguous?",
    "missing_information": "What information did you need but not have, or find hard to keep track of?",
    "wanted_but_couldnt": "What did you want to do that the game or interface didn't let you do?",
    "bugs_or_oddities": "Did anything seem broken, inconsistent with the rules, or strange?",
    "suggestions": "What would you change about the game or the interface?",
}
DEBRIEF_SCHEMA = obj(**{k: STR for k in DEBRIEF_QUESTIONS})
ISSUE_KINDS = ["rules ambiguity", "harness bug", "moderator error", "prompt problem", "player confusion", "other"]
REVIEW_SCHEMA = obj(issues={"type": "array", "items": obj(
    kind={"type": "string", "enum": ISSUE_KINDS},
    severity={"type": "string", "enum": ["high", "medium", "low"]},
    description=STR)})


def debrief_task(game: Game) -> str:
    roles = ", ".join(f"{p.name}: {p.role}" for p in game.players)
    questions = "\n".join(f"- {k}: {q}" for k, q in DEBRIEF_QUESTIONS.items())
    return (f"The game is over. Winners: {', '.join(game.winners or []) or 'nobody'}. Everyone's roles: {roles}.\n\n"
            "We're improving this game and the program that runs it. Out of character now, answer from "
            "your own experience of playing it. Be specific and concrete, and write 'none' where you have "
            f"nothing to say.\n{questions}")


def run_debrief(game: Game, players: Players, moderator: Moderator) -> None:
    task = debrief_task(game)
    fallback = {k: "" for k in DEBRIEF_QUESTIONS}
    outs = players.ask_many([(p, task, DEBRIEF_SCHEMA, fallback) for p in game.players])
    for p, out in zip(game.players, outs):
        game.log.write("debrief", who=p.name, role=p.role, model=p.model.value, answers=out)

    events = "\n".join(f"[Day {e.day} {e.phase}] "
                       + ("" if e.visible_to is None else f"(to {', '.join(sorted(e.visible_to))}) ")
                       + e.text for e in game.events)
    flags = "\n".join(f"- {f}" for f in moderator.flags) or "(none)"
    messages = [
        {"role": "system", "content": f"{moderator.rules}\n\n---\n\nYou were the moderator of this game."},
        {"role": "user", "content": f"Everything that happened (with who could see each event):\n{events}\n\n"
         f"Issues you flagged during the game:\n{flags}\n\n{task}\nAnswer as the moderator: also cover "
         "rules you had to interpret, and tools or state you were missing."},
    ]
    reply = moderator.client.chat(moderator.model, messages, schema=DEBRIEF_SCHEMA, schema_name="debrief",
                                  effort=moderator.effort)
    game.log.write("debrief", who="moderator", role="Moderator", model=moderator.model.value,
                   answers=json.loads(reply.content or "{}"), cost=reply.cost)


def run_review(game: Game, client: LLMClient, model: Model, rules: str, text_log: Path,
               effort: str | None = None) -> None:
    """An outside model reads the whole human-readable log and lists problems it sees."""
    messages = [
        {"role": "system", "content": f"{rules}\n\n---\n\nYou review logs of LLMs playing this game, which "
         "is run by a program plus an LLM moderator. Find problems: rules ambiguities, program bugs, "
         "moderator mistakes, prompt problems, and places players seemed confused about the rules or "
         "interface. Ignore ordinary bad strategy."},
        {"role": "user", "content": f"Game log:\n{text_log.read_text(encoding='utf-8')}"},
    ]
    reply = client.chat(model, messages, schema=REVIEW_SCHEMA, schema_name="review", effort=effort)
    game.log.write("review", model=model.value, issues=json.loads(reply.content or "{}").get("issues", []),
                   cost=reply.cost)


LESSON_TOPICS = ["rules and mechanics", "deduction", "deception", "persuasion and voting",
                 "night actions", "coordination", "speaking budget", "other"]
LESSONS_SCHEMA = obj(lessons={"type": "array", "items": obj(
    topic={"type": "string", "enum": LESSON_TOPICS},
    applies_to=STR,  # a role, faction, or "everyone"
    tip=STR)})


def run_lessons(game: Game, players: Players, lessons_file: Path) -> None:
    """Each player lists tips and tricks they wish they'd known. Saved to the game log and appended
    to `lessons_file` (one JSON object per tip, across all games) for later analysis."""
    roles = ", ".join(f"{p.name}: {p.role}" for p in game.players)
    task = (f"The game is over. Winners: {', '.join(game.winners or []) or 'nobody'}. Everyone's roles: "
            f"{roles}.\n\nIf you played this game again, what tips and tricks do you wish you'd known? "
            "Give 1-5 concrete, reusable lessons (not a recap of this game), each with a topic and who it "
            "applies to (a role, a faction, or 'everyone').")
    outs = players.ask_many([(p, task, LESSONS_SCHEMA, {"lessons": []}) for p in game.players])
    lessons_file.parent.mkdir(parents=True, exist_ok=True)
    with lessons_file.open("a", encoding="utf-8") as f:
        for p, out in zip(game.players, outs):
            game.log.write("lessons", who=p.name, role=p.role, model=p.model.value, lessons=out["lessons"])
            for lesson in out["lessons"]:
                f.write(json.dumps({"game": game.log.path.stem, "player": p.name, "role": p.role,
                                    "model": p.model.value, "won": p.name in (game.winners or []),
                                    **lesson}) + "\n")


def write_report(jsonl_path: Path) -> Path | None:
    """Collect night checks, moderator flags, in-game feedback, debriefs and the review into
    <game>_feedback.md."""
    records = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line]
    flags = [r for r in records if r["kind"] == "moderator_flag"]
    in_game = [r for r in records if r["kind"] == "player_feedback"]
    debriefs = [r for r in records if r["kind"] == "debrief"]
    reviews = [r for r in records if r["kind"] == "review"]
    lessons = [r for r in records if r["kind"] == "lessons"]
    checks = sorted((r for r in records if r["kind"] == "night_check"), key=lambda r: r["night"])
    if not (flags or in_game or debriefs or reviews or lessons or checks):
        return None
    out = [f"# Feedback for {jsonl_path.stem}\n"]
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
        out += [f"- Day {r['day']} {r['phase']}, {r['player']} ({r['role']}): {r['feedback']}" for r in in_game]
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
    for r in reviews:
        out.append(f"## Outside review ({r['model'].split('/')[-1]})\n")
        order = {"high": 0, "medium": 1, "low": 2}
        out += [f"- **{i['severity']}, {i['kind']}:** {i['description']}"
                for i in sorted(r["issues"], key=lambda i: order.get(i["severity"], 3))]
        out.append("")
    path = jsonl_path.with_name(jsonl_path.stem + "_feedback.md")
    path.write_text("\n".join(out), encoding="utf-8")
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
     "At the beginning of the following day, a random Good player is dealt a Divine Attack."),
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


def run_quiz(client: LLMClient, specs: list[ModelSpec], grader: ModelSpec, rules: str, out_dir: Path) -> Path:
    """Ask each model the quiz questions given only the rules, then have `grader` mark the answers
    against the reference answers. Wrong or split answers point at rules that need clarifying."""
    questions = "\n".join(f"{i + 1}. {q}" for i, (q, _) in enumerate(QUIZ))
    # One named field per question, so an answer can't slip into the wrong slot.
    answer_schema = obj(**{f"q{i + 1}": STR for i in range(len(QUIZ))})
    table: dict[str, list[dict]] = {}
    answers_by_model: dict[str, list[str]] = {}
    for spec in dict.fromkeys(specs):
        model = spec.model
        reply = client.chat(model, [
            {"role": "system", "content": f"{rules}\n\n---\n\nAnswer questions about the rules above."},
            {"role": "user", "content": f"Answer each question in one or two sentences, in order:\n{questions}"},
        ], schema=answer_schema, schema_name="quiz", effort=spec.effort)
        parsed = json.loads(reply.content or "{}")
        answers = [parsed.get(f"q{i + 1}", "") for i in range(len(QUIZ))]
        answers_by_model[str(spec)] = answers
        marking = "\n".join(f"{i + 1}. Q: {q}\n   Reference: {ref}\n   Answer: {answers[i] if i < len(answers) else '(none)'}"
                            for i, (q, ref) in enumerate(QUIZ))
        graded = client.chat(grader.model, [
            {"role": "user", "content": "Mark each answer correct if it gets the reference's main point right and "
             "contradicts nothing in it; leaving out a minor detail is fine. Otherwise mark it incorrect. "
             "Give a short note either way, and say if the answer reveals a misreading of the rules."
             f"\n\n{marking}"},
        ], schema=QUIZ_GRADE_SCHEMA, schema_name="quiz_grades", effort=grader.effort)
        table[str(spec)] = json.loads(graded.content or "{}").get("results", [])

    out = ["# Rules quiz\n", f"Graded by {grader}.\n", "| # | Question | " + " | ".join(table) + " |",
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
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path
