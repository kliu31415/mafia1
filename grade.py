"""Grades each player's play in finished games with an LLM judge, blind to which model played.

Usage:
    uv run grade.py logs/game_X.jsonl [more logs]   # one grade per player, written to grades/<game>.jsonl
    uv run grade.py --judge opus-5.5 --out DIR ...  # judge model (default Opus 5.5) and output folder

The judge gets the rules, the game's full log (everything up to the post-game sections, with model names
removed) and the graded player's private "reason" notes from each turn. It lists the player's important
decisions, grades each from -2 (blunder) to +2 (strong) against what the player knew at the time (not the
true roles they couldn't see, and not how luck turned out), and scores six skills and overall play from 1 to
10. The log is cached after a game's first call, so each further player costs mostly the judge's output.
"""

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from llm import OpenRouterClient, answer_json, cache_block, load_api_key, parse_model_spec, rules_system
from players import STR, obj
import variants

ROOT = Path(__file__).parent
RULES_PATH = ROOT / "rules_1.txt"

INT = {"type": "integer"}
DECISION_KINDS = ["claim", "nomination", "nomination_vote", "trial_vote", "night_action", "katana", "speech",
                  "private_message", "will", "other"]
SKILLS = ["deduction", "persuasion", "deception_or_credibility", "mechanics", "resource_use", "team_play"]
GRADE_SCHEMA = obj(
    decisions={"type": "array", "items": obj(
        when=STR,  # "Day 2", "Night 3"
        kind={"type": "string", "enum": DECISION_KINDS},
        what=STR,
        grade=INT,  # -2..2
        why=STR)},
    scores=obj(**{k: INT for k in SKILLS}, overall=INT),  # 1..10
    best_play=STR,
    worst_play=STR,
    summary=STR)

JUDGE_TASK = """You are an expert judge of this Mafia variant. You will grade how well ONE player played a \
finished game, for a benchmark comparing players across many games.

Rules for grading:
- Judge each decision by what that player could know at the time: public events, private lines addressed to \
them ("(to X)" lines that include them), and their faction's shared information. Do not punish a reasonable \
choice that true roles they couldn't see made wrong, and do not reward a lucky one. Judge play, not the result.
- Grade from the player's own faction's point of view (Village, Yakuza, or their Neutral win condition).
- The player's private "reason" notes show their intent; use them to understand a choice, but grade the \
choice itself, not how well it was explained.
- Grades per decision: +2 strong (clearly the best available, or a play that changed the game), +1 good, \
0 reasonable or neutral, -1 a mistake, -2 a blunder (e.g. exposing their own team, a fake claim that collides \
with a known live role, spending a key token against their own faction).
- List the 6-15 decisions that mattered most (claims, nominations, votes, night actions and Katana choices, \
speeches or private messages that moved others, wills, tokens held too long). Include the bad ones.
- Skill scores, 1-10 (use 0 for a skill the player had no chance to show, e.g. died on Night 1):
  deduction: reading the evidence and other players correctly.
  persuasion: moving votes and opinions toward their goal.
  deception_or_credibility: for Yakuza and Neutrals, how convincing their cover was; for Village, how \
believable they made true information.
  mechanics: using the rules correctly (no impossible claims, right understanding of results and tokens).
  resource_use: night actions, tokens and timing of claims.
  team_play: coordinating with their faction (votes, Yakuza chat, protecting and trusting the right people).
- overall, 1-10: 1-2 actively helped the other side; 3-4 weak, with real mistakes; 5 an average, competent \
player; 6-7 good; 8-9 strong, few mistakes and some excellent plays; 10 near flawless. Use the whole range."""

POST_GAME = re.compile(r"^===== POST-GAME", re.M)


def blind_log(text: str, models: set[str]) -> str:
    """The game's text log without the post-game sections and without the players' model ids."""
    m = POST_GAME.search(text)
    text = text[:m.start()] if m else text
    for model in models:
        text = text.replace(model, "")
    return text


def reason_notes(records: list[dict], name: str) -> str:
    """The player's private "reason" from each turn's answer, in order."""
    lines = []
    for r in records:
        if r.get("kind") != "player_call" or r.get("player") != name:
            continue
        out = r.get("output")
        reason = out.get("reason") if isinstance(out, dict) else None
        if reason:
            lines.append(f"{r.get('phase', '?')} {r.get('day', '?')} ({r.get('step', '?')}): {reason}")
    return "\n".join(lines) or "(none recorded)"


def grade_game(client: OpenRouterClient, spec, rules: str, path: Path, out_dir: Path) -> list[dict]:
    records = [json.loads(line) for line in path.open(encoding="utf-8")]
    setup = next(r for r in records if r["kind"] == "setup")
    result: dict = next((r for r in records if r["kind"] == "result"), {})
    log_text = blind_log(path.with_suffix(".txt").read_text(encoding="utf-8"),
                         {p["model"] for p in setup["players"]})
    rules += variants.rules_notes(variants.full(setup.get("settings")))  # the settings this game was played with
    system = rules_system(rules, [cache_block(f"\n\n---\n\n{JUDGE_TASK}\n\nGame log:\n{log_text}")])

    def grade(p: dict) -> dict:
        task = (f"Grade {p['name']}, who started as {p['role']}.\n\n{p['name']}'s private reason notes, "
                f"turn by turn:\n{reason_notes(records, p['name'])}")
        reply = client.chat(spec.model, [system, {"role": "user", "content": task}], schema=GRADE_SCHEMA,
                            schema_name="grade", effort=spec.effort)
        winners = result.get("winners") or []
        won = p["name"] in winners if isinstance(winners, list) else None
        return {"game": path.stem, "player": p["name"], "model": p["model"], "role": p["role"], "won": won,
                "judge": spec.model.value, "grade": answer_json(reply, GRADE_SCHEMA), "cost": reply.cost,
                "usage": reply.usage}

    players = setup["players"]
    rows = [grade(players[0])]  # writes the cached log; the rest read it
    with ThreadPoolExecutor(6) as pool:
        rows += list(pool.map(grade, players[1:]))
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / f"{path.stem}.jsonl").open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    print(f"{path.stem}: {len(rows)} players, ${sum(r['cost'] for r in rows):.2f}")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logs", nargs="+", type=Path)
    ap.add_argument("--judge", default="opus-5.5")
    ap.add_argument("--out", type=Path, default=ROOT / "grades")
    args = ap.parse_args()
    spec = parse_model_spec(args.judge)
    client = OpenRouterClient(load_api_key())
    rules = RULES_PATH.read_text(encoding="utf-8")
    total = sum(r["cost"] for path in args.logs for r in grade_game(client, spec, rules, path, args.out))
    print(f"total ${total:.2f}")


if __name__ == "__main__":
    main()
