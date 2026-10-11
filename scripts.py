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
    """The roles of this game's script: what "every role in the rules" means for draws such as fakes and decoys."""
    return roles_of(game.rule_settings.get("script", DEFAULT))


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


def rules_for(rules: str, script: str) -> str:
    """The rules text a game on this script plays by: rules_1.txt itself for "all"; otherwise only the script's
    roles in the roles part, and a note after the rules saying that's the whole pool."""
    if SCRIPTS[script] is None:
        return rules
    end = rules.index("\n", rules.index("PART 6: ROLES"))  # the roles part starts after its heading's line
    head, part = rules[:end], rules[end:]
    names = roles_of(script)
    by_side = {a: sum(ROLES[r].alignment is a for r in names) for a in Alignment}
    note = (f"\n\n---\n\nScript: this game uses the {script} script, so Part 6 lists only its {len(names)} roles "
            f"({by_side[Alignment.GOOD]} Village, {by_side[Alignment.EVIL]} Yakuza, {by_side[Alignment.NEUTRAL]} "
            "Neutral). Every role in this game is one of them, though most of them aren't in play, and no other "
            "role is. Wherever a rule draws a role from all the roles in these rules, or names roles that aren't "
            "listed (e.g. as examples or as a role to choose from), it means only the listed ones.")
    return head + _filter_roles_part(part, set(names)) + note
