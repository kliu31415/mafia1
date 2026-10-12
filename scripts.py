"""Scripts: the roles a game can use, as in Blood on the Clocktower (Kevin, Oct 11 2026).

A script is a named list of roles (SCRIPTS, picked with --script). Players, the moderator and the night judge get
only its roles' paragraphs in the rules (rules_for), plus a note saying the list is the whole pool, so a big role
catalogue doesn't make every prompt longer. Every role in the game comes from the script (setups draw from it, and a
hand-picked list must stay on it), and code that draws "any role in the rules" (fakes, decoys) draws from the script
too (script_roles). Players know which roles are on the script, not which are in play.

"all" (the default) is every role in ROLES, so new roles join it automatically, and its rules text is rules_1.txt
unchanged. A game's script is in game.rule_settings["script"] and the log's settings.script (log 41; older logs and
checkpoints played with "all").
"""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from roles import ROLES, Alignment

DEFAULT = "all"

# Hand-picked (Oct 11 2026): 30 mostly live-tested roles whose interactions matter: frames and the Ex-Con against
# alignment checks, the Mortician against the Coroner, the Veteran and Trapper against visitors seen by the Tracker,
# Lookout, Insomniac and Fortune Teller, blocks on both sides, the Informant and the Auditor reading votes, the Clerk
# and the Prosecutor forcing trials, and Neutrals that bait or threaten everyone. Setups still balance each game's
# draw by role power (setups.py).
CORE = [
    "Vanilla Villager",
    "Sheriff", "Tracker", "Lookout", "Seer", "Fortune Teller", "Oracle", "Coroner", "Auditor", "Insomniac",
    "Medic", "Trapper", "Vigilante", "Veteran",
    "Prosecutor", "Party Animal",
    "Ex-Con", "Cardinal",
    "Grunt", "Pharmacist", "Fabricator", "Mortician", "Puppeteer", "Clerk", "Informant", "Ritualist",
    "Jester", "Executioner", "Serial Killer", "Arsonist",
]

SCRIPTS: dict[str, list[str] | None] = {  # None: every role
    "all": None,
    "core": CORE,
}


def roles_of(script: str) -> list[str]:
    """The script's roles, in ROLES order."""
    chosen = SCRIPTS[script]
    return [r for r in ROLES if chosen is None or r in chosen]


def script_roles(game) -> list[str]:
    """The roles of this game's script, less any its setup never draws: what "every role in the rules" means for
    draws such as fakes and decoys."""
    off = game.rule_settings.get("setup_off", "").split(",")  # roles the setup never draws (setups.Setup.off)
    return [r for r in roles_of(game.rule_settings.get("script", DEFAULT)) if r not in off]


def off_script(script: str, roles: list[str]) -> list[str]:
    allowed = set(roles_of(script))
    return [r for r in dict.fromkeys(roles) if r not in allowed]


def _filter_roles_part(part: str, keep: set[str]) -> str:
    """The rules' roles part with only the kept roles' paragraphs, dropping category and faction headings that no
    longer have a role under them. Blocks are separated by blank lines; a role paragraph is its name, then
    indented lines."""
    blocks = part.split("\n\n")

    def role(block: str) -> str | None:
        first = block.split("\n", 1)[0].strip()
        return first if first in ROLES else None

    def level(block: str) -> int:  # 1: a faction heading, 2: a category heading, 0: anything else
        first = block.strip().split("\n", 1)[0]
        if not first:
            return 0
        if first.startswith("--- "):
            return 1
        return 2 if "\n" not in block.strip() and not first.startswith(" ") and role(block) is None else 0

    kept = [b for b in blocks if role(b) is None or role(b) in keep]
    out = []
    for i, b in enumerate(kept):
        lvl = level(b)
        if lvl:
            following = []
            for later in kept[i + 1:]:
                if 0 < level(later) <= lvl:
                    break
                following.append(later)
            if not any(role(x) for x in following):
                continue
        out.append(b)
    return "\n\n".join(out)


def cut(rules: str, script: str) -> str:
    """rules_1.txt with only the script's roles in the roles part (the mechanical cut, before any revision)."""
    end = rules.index("\n", rules.index("PART 6: ROLES"))  # the roles part starts after its heading's line
    head, part = rules[:end], rules[end:]
    return head + _filter_roles_part(part, set(roles_of(script)))


def note(script: str) -> str:
    """The note after a script's rules saying its roles are the whole pool."""
    names = roles_of(script)
    by_side = {a: sum(ROLES[r].alignment is a for r in names) for a in Alignment}
    return (f"\n\n---\n\nScript: this game uses the {script} script, so Part 6 lists only its {len(names)} roles "
            f"({by_side[Alignment.GOOD]} Village, {by_side[Alignment.EVIL]} Yakuza, {by_side[Alignment.NEUTRAL]} "
            "Neutral). Every role in this game is one of them, though most of them aren't in play, and no other "
            "role is. Wherever a rule draws a role from all the roles in these rules, or names roles that aren't "
            "listed (e.g. as examples or as a role to choose from), it means only the listed ones.")


# --- the cached revision ------------------------------------------------------------------------------------
# The cut leaves mentions of roles that aren't on the script (examples, cross-references, lists in general rules).
# Once per script and rules version, a model tidies them up (Kevin, Oct 11 2026): it returns small edits, applied
# word for word, so nothing else in the rules can change. The result is kept in rules_scripts/NAME.txt (the text
# games use; a git diff shows exactly what was revised) and NAME.json (the cut it was made from, the edits, the
# model). When rules_1.txt or the script changes, the cut changes, the cache goes stale and
# test_every_script_revision_is_current fails until `uv run scripts.py revise` remakes it: regenerated once, at
# commit time, so every game on a script plays by the same reviewed text. A game that still finds it stale plays
# by the plain cut and logs a script_stale alert. With many scripts, regenerating all of them on every rules edit
# gets costly: see "Script revisions at scale" in IDEAS.md.

CACHE_DIR = Path(__file__).parent / "rules_scripts"
REVISER = "opus-5.5"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def cached(rules: str, script: str) -> str | None:
    """The script's revised rules (no note), if the cache was made from this cut; else None."""
    try:
        meta = json.loads((CACHE_DIR / f"{script}.json").read_text(encoding="utf-8"))
        text = (CACHE_DIR / f"{script}.txt").read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    if meta.get("cut_sha256") != digest(cut(rules, script)) or meta.get("text_sha256") != digest(text):
        return None
    return text


def stale(rules: str, script: str) -> bool:
    """Whether a script needs a (new) revision: any script but "all" whose cache doesn't match its current cut."""
    return SCRIPTS[script] is not None and cached(rules, script) is None


def rules_for(rules: str, script: str) -> str:
    """The rules text a game on this script plays by: rules_1.txt itself for "all"; otherwise the cached revision
    of the cut (or the plain cut while it's stale), and the note saying the script's roles are the whole pool."""
    if SCRIPTS[script] is None:
        return rules
    return (cached(rules, script) or cut(rules, script)) + note(script)


REVISE_TASK = (
    'You are tidying the rules of a social deduction game for one game "script". The full rules are above; the '
    "user's message has the same rules cut down to the script: role paragraphs not on the script were removed, "
    "nothing else changed. The cut can still mention roles that are no longer listed (examples, cross-references, "
    "lists of roles in general rules or in other roles' paragraphs). Players will be told that only the listed "
    "roles exist.\n\n"
    "Return edits to the CUT rules that remove or reword mentions of roles that aren't on the script, where doing "
    "so makes the rules clearer or shorter without changing any rule for the listed roles. Also remove a sentence "
    "that only explains an effect no listed role can cause (e.g. vote totals that don't match the voters when no "
    "listed role changes how votes are counted), since players would otherwise expect it. Each edit replaces one "
    'exact passage ("old", copied character for character from the cut rules, including line breaks, long enough '
    'to occur only once) with "new". Keep the text\'s style and line wrapping (about 116 characters, role lines '
    "indented by two spaces). Keep a mention when removing it would change or weaken a rule, e.g. an example that "
    "explains a mechanic the listed roles still use (reword it to a listed role if one fits, otherwise leave it). "
    "Don't rename rule labels (R1, R2, ...), don't touch role names, and don't edit anything else. Return no "
    "edits if nothing needs changing. Give each edit a short reason."
)

EDIT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["edits"], "properties": {
    "edits": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                         "required": ["old", "new", "reason"],
                                         "properties": {"old": {"type": "string"}, "new": {"type": "string"},
                                                        "reason": {"type": "string"}}}}}}


def apply_edits(text: str, edits: list[dict]) -> str:
    """The text with each edit's exact passage replaced; raises ValueError if a passage isn't there exactly once,
    or if the result no longer has the same role paragraphs and rule labels."""
    out = text
    for e in edits:
        if out.count(e["old"]) != 1:
            raise ValueError(f"edit passage found {out.count(e['old'])} times, not once: {e['old'][:80]!r}")
        out = out.replace(e["old"], e["new"])
    if role_names(out) != role_names(text) or rule_labels(out) != rule_labels(text):
        raise ValueError("the edits changed which roles or rule labels the rules have")
    return out


def role_names(text: str) -> list[str]:
    """The roles with a paragraph in this rules text (their name on its own line, then indented lines)."""
    lines = text.split("PART 6: ROLES", 1)[1].splitlines()
    return [line for i, line in enumerate(lines[:-1]) if line in ROLES and lines[i + 1].startswith("  ")]


def rule_labels(text: str) -> list[str]:
    return re.findall(r"^(R\d+) \(", text, flags=re.M)


def script_task(script: str, text: str) -> str:
    """The script-specific part of the revision task: which roles are (not) on it, and the cut to edit."""
    missing = sorted(set(ROLES) - set(roles_of(script)))
    return (f"Roles on the script: {', '.join(roles_of(script))}.\nRoles NOT on the script: {', '.join(missing)}."
            f"\n\n=== CUT RULES (edit these) ===\n{text}")


def record(rules: str, script: str, edits: list[dict], made_by: str, cost: float = 0.0) -> dict:
    """Checks the edits against the script's current cut (apply_edits) and writes the cache; returns its metadata."""
    text = cut(rules, script)
    revised = apply_edits(text, edits)
    meta = {"script": script, "cut_sha256": digest(text), "text_sha256": digest(revised), "made_by": made_by,
            "made": datetime.now().isoformat(timespec="seconds"), "cost": cost, "edits": edits}
    CACHE_DIR.mkdir(exist_ok=True)
    (CACHE_DIR / f"{script}.txt").write_text(revised, encoding="utf-8")
    (CACHE_DIR / f"{script}.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return meta


def revise(client, rules: str, script: str, reviser: str = REVISER) -> dict:
    """Asks the reviser model for edits to the script's cut and writes the cache; returns its metadata."""
    from llm import answer_json, parse_model_spec, rules_system
    spec = parse_model_spec(reviser)
    # The full rules and the task come first, cached (llm.rules_system), so revising several scripts in a row pays
    # for them once; only the script's own part differs between calls.
    system = rules_system(rules, f"The text above is the FULL RULES.\n\n{REVISE_TASK}")
    reply = client.chat(spec.model, [system, {"role": "user", "content": script_task(script, cut(rules, script))}],
                        schema=EDIT_SCHEMA, schema_name="edits", effort=spec.effort)
    return record(rules, script, answer_json(reply, EDIT_SCHEMA)["edits"], str(spec), reply.cost)


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Remake scripts' cached rules revisions (see scripts.py). A Claude Code "
                                 "session can write the edits itself instead of an API call: `task NAME` prints what "
                                 "to edit, then `apply NAME FILE` records a JSON file of edits (EDIT_SCHEMA).")
    ap.add_argument("command", choices=["check", "revise", "task", "apply"])
    ap.add_argument("names", nargs="*", help="check/revise: scripts (default: the stale ones); task: one script; "
                    "apply: one script and the edits file")
    ap.add_argument("--reviser", default=REVISER, help="the model revise asks")
    ap.add_argument("--made-by", default="a Claude Code session", help="apply: who wrote the edits, for the cache")
    args = ap.parse_args()
    rules = (Path(__file__).parent / "rules_1.txt").read_text(encoding="utf-8")
    if args.command == "task":
        (name,) = args.names
        print(f"{REVISE_TASK}\n\nThe FULL RULES are rules_1.txt.\n\n{script_task(name, cut(rules, name))}")
        return
    if args.command == "apply":
        name, file = args.names
        edits = json.loads(Path(file).read_text(encoding="utf-8"))
        meta = record(rules, name, edits["edits"] if isinstance(edits, dict) else edits, args.made_by)
        print(f"{name}: {len(meta['edits'])} edits recorded")
        return
    todo = args.names or [s for s in SCRIPTS if stale(rules, s)]
    if args.command == "check" or not todo:
        print("Stale: " + (", ".join(todo) if todo else "none"))
        return
    from claude_code import default_client
    client = default_client()  # Claude models through the Claude Code CLI where it's installed
    for name in todo:
        meta = revise(client, rules, name, args.reviser)
        print(f"{name}: {len(meta['edits'])} edits, ${meta['cost']:.2f}")
        for e in meta["edits"]:
            print(f"  - {e['reason']}")


if __name__ == "__main__":
    main()
