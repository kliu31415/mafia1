"""Role definitions from rules_1.txt and the default setup.

Each role with effects that code carries out has its own file here (e.g. roles/executioner.py),
implementing the hooks in roles/base.py. Every module here is imported at the bottom of this file, which registers it.
"""

import importlib
import pkgutil
from dataclasses import dataclass, field

from roles.base import (LOGIC, Alignment, RoleLogic, Status, code_hooks, logic,  # noqa: F401  (re-exported)
                        register)


@dataclass(frozen=True)
class RoleInfo:
    alignment: Alignment
    category: str
    sheriff_evil: bool  # how the role appears to a Sheriff, before Katana/Fabricator effects (Ex-Con: to Seers too)
    summary: str = ""  # one line for the hover text on the role's icon in HTML logs; rules_1.txt is the full text
    defense: str = "None"
    tokens: dict[str, int] = field(default_factory=dict)
    acts_at_night: bool = False  # submits a night action, which the LLM moderator resolves
    unique: bool = False  # at most one player in a game may have this role
    tested: bool = False  # seen working in at least one live (API) game; update when it first is
    notes: str = ""  # implementation notes for --list-roles


ROLES: dict[str, RoleInfo] = {
    # Village
    "Vanilla Villager": RoleInfo(Alignment.GOOD, "Townsfolk", False,
                                 summary="No night action.",
                                 tested=True),
    "Sheriff": RoleInfo(Alignment.GOOD, "Investigative", False,
                        summary="Night: investigate one player, learn Evil or Not Evil.",
                        acts_at_night=True,
                        tested=True, notes="Katana holder and framed players handled by the moderator"),
    "Tracker": RoleInfo(Alignment.GOOD, "Investigative", False,
                        summary="Night: track one player, learn whom they visited.",
                        acts_at_night=True, tested=True),
    "Lookout": RoleInfo(Alignment.GOOD, "Investigative", False,
                        summary="Night: watch one player, learn who visited them.",
                        acts_at_night=True, tested=True),
    "Seer": RoleInfo(Alignment.GOOD, "Investigative", False,
                     summary="Each night: told whether two random players share an alignment; "
                     "a token lets them pick the pair.",
                     tokens={"seer": 1}, acts_at_night=True,
                     tested=True, notes="random pair each night unless a token is spent"),
    "Fortune Teller": RoleInfo(Alignment.GOOD, "Investigative", False,
                               summary="Every night: two labeled numbers, how many players were visited "
                               "and how many visited someone that night.",
                               tested=True, notes="numbers told at the end of the night"),
    "Oracle": RoleInfo(Alignment.GOOD, "Investigative", False,
                       summary="Night: guess one player's exact role, learn whether it was right.",
                       acts_at_night=True, tested=True),
    "Eavesdropper": RoleInfo(Alignment.GOOD, "Investigative", False,
                             summary="Night: pick a player; reads every PM they send or receive the next Day.",
                             acts_at_night=True,
                             notes="moderator records the target with the eavesdrop op; code shows them the "
                             "target's PMs the next day"),
    "Archivist": RoleInfo(Alignment.GOOD, "Investigative", False,
                          summary="Once (token): sees one role per other player, unnamed and shuffled; "
                          "half are real, the rest fakes.",
                          tokens={"archive": 1}, acts_at_night=True, tested=True,
                          notes="moderator records the use with the archive op; code draws the real half "
                          "and the fakes (any role, never a second unique one), and tells it at once"),
    "Surveyor": RoleInfo(Alignment.GOOD, "Investigative", False,
                         summary="Token: survey a player; learns one random role among them and their two neighbors.",
                         tokens={"survey": 3}, acts_at_night=True, tested=True,
                         notes="moderator records the use with the survey op; code picks the group and draws the role"),
    "Census Taker": RoleInfo(Alignment.GOOD, "Investigative", False,
                             summary="Night: count the Good or the Evil players (drawn at random) among a chosen "
                             "player and two random others.",
                             acts_at_night=True,
                             notes="moderator records the use with the census op; code draws the group and the "
                             "alignment counted, counts true alignment and tells them"),
    "Profiler": RoleInfo(Alignment.GOOD, "Investigative", False,
                         summary="Token: profile a player, learn three candidate roles for them, one true.",
                         tokens={"profile": 3}, acts_at_night=True,
                         notes="moderator records the use with the profile op; code draws the decoys and tells them"),
    "Coroner": RoleInfo(Alignment.GOOD, "Investigative", False,
                        summary="Token: examine a player who died before tonight, learn their role (not if a "
                        "Mortician cleaned them).",
                        tokens={"coroner": 3}, acts_at_night=True, tested=True,
                        notes="moderator records the use with the examine op (a dead target, not a visit); code "
                        "tells them the role, or that the body was cleaned"),
    "Chronicler": RoleInfo(Alignment.GOOD, "Investigative", False,
                           summary="Token: marks a player; if they ever die, their role is revealed to everyone "
                           "(unless a Mortician cleans them).",
                           tokens={"chronicler": 2}, acts_at_night=True,
                           notes="moderator records the use with the mark op (a visit); code sets status 'marked', "
                           "and the death announcement reveals the role or says the clean hid it"),
    "Auditor": RoleInfo(Alignment.GOOD, "Investigative", False,
                        summary="Night: audit a player, learn all their nomination and trial votes from that Day.",
                        acts_at_night=True, tested=True,
                        notes="moderator records the use with the audit op (a visit); code reads the Day's votes "
                        "and tells them"),
    "Juror": RoleInfo(Alignment.GOOD, "Investigative", False,
                      summary="Night: name two players, learn how often they voted the same way all game.",
                      acts_at_night=True,
                      notes="moderator records the use with the jury op (Astral); code counts the shared votes "
                      "and tells them"),
    "Cartographer": RoleInfo(Alignment.GOOD, "Investigative", False,
                             summary="Every night: learns the sizes of the night's visit groups (visits linking "
                             "players either way). Token: learns the names in one player's group.",
                             tokens={"map": 2}, acts_at_night=True, tested=True,
                             notes="moderator lists every night's visits with record_visits and records a token use "
                             "with the map op; code finds the groups and tells them"),
    "Scout": RoleInfo(Alignment.GOOD, "Investigative", False,
                      summary="Every night: learns three players (maybe themselves) who were each in a different "
                      "visit group.", tested=True,
                      notes="passive; code draws the names from the moderator's record_visits list and tells them"),
    "Insomniac": RoleInfo(Alignment.GOOD, "Investigative", False,
                          summary="Token: learns the roles (no names) of up to 3 random players who visited someone "
                          "that night.",
                          tokens={"insomniac": 2}, acts_at_night=True, tested=True,
                          notes="moderator records the use with the stay_awake op; code draws the visitors from "
                          "record_visits and tells them at the end of the night"),
    "Accountant": RoleInfo(Alignment.GOOD, "Investigative", False,
                           summary="Night: audit one player, learn their total token count.",
                           acts_at_night=True,
                           tested=True, notes="moderator reports the end-of-night token total; "
                           "night note says Roleplayers show 0"),
    "Medic": RoleInfo(Alignment.GOOD, "Combat", False,
                      summary="Night: protect one other player (Standard Defense; tokens for Strong or for self).",
                      tokens={"medic": 2}, acts_at_night=True,
                      tested=True, notes="tokens tracked via set_tokens; briefing lists token costs"),
    "Trapper": RoleInfo(Alignment.GOOD, "Combat", False,
                        summary="Night: trap a player; the first non-Village visitor on a later night "
                        "takes a Strong Attack.",
                        acts_at_night=True,
                        tested=True,
                        notes="persistent traps tracked as player status; acting with no target removes the trap"),
    "Vigilante": RoleInfo(Alignment.GOOD, "Combat", False,
                          summary="Night: shoot a player, 1-3 tokens for a Basic, Standard or Strong Attack; "
                          "learns the role of a player it kills.",
                          tokens={"vigilante": 3}, acts_at_night=True,
                          tested=True, notes="moderator resolves the shot; code tells the victim's role on a kill"),
    "Veteran": RoleInfo(Alignment.GOOD, "Combat", False,
                        summary="Can't be role-blocked. Token: go on alert, Standard Defense "
                        "and a Strong Attack on every visitor.",
                        tokens={"alert": 3}, acts_at_night=True,
                        tested=True, notes="moderator resolves the alert; night note lists its effects"),
    "Prosecutor": RoleInfo(Alignment.GOOD, "Misc", False,
                           summary="Token: prosecute a player, who goes straight to trial the next Day.",
                           tokens={"prosecutor": 2}, acts_at_night=True,
                           tested=True, notes="moderator records the prosecution; code runs the trial next day"),
    "Philanthropist": RoleInfo(Alignment.GOOD, "Misc", False,
                               summary="Token: hand a player one token of their own role's kind.",
                               tokens={"philanthropy": 2}, acts_at_night=True,
                               tested=True, notes="moderator records the gift with the give_token op; "
                               "code adds the token and tells the recipient"),
    "Party Animal": RoleInfo(Alignment.GOOD, "Misc", False,
                             summary="Night: role-block one player. Immune to role-blocks.",
                             acts_at_night=True, tested=True),
    "Roleplayer": RoleInfo(Alignment.GOOD, "Outsider", False,
                           summary="Thinks they are a random Investigative role; gets usually false results.",
                           acts_at_night=True,
                           notes="code assigns the fake role (with its tokens and night prompts); "
                           "moderator invents its results"),
    "Ex-Con": RoleInfo(Alignment.GOOD, "Outsider", True,
                       summary="Visits a random player each night without knowing whom; "
                       "reads Evil to alignment checks.",
                       tested=True, notes="code draws the random visit each night (automatic action); "
                       "night note says it reads Evil to Sheriff and Seer"),
    "Cardinal": RoleInfo(Alignment.GOOD, "Outsider", False,
                         summary="If they die, a random living Good player is dealt a Divine Attack.",
                         tested=True, notes="curse resolved by code at the end of the night"),
    # Yakuza
    "Grunt": RoleInfo(Alignment.EVIL, "Yakuza", True,
                      summary="No night action of its own; shares the Katana.",
                      tested=True),
    "Pharmacist": RoleInfo(Alignment.EVIL, "Yakuza", True,
                           summary="Night: role-block one player. Immune to role-blocks.",
                           acts_at_night=True, tested=True),
    "Ritualist": RoleInfo(Alignment.EVIL, "Yakuza", True,
                          summary="Token: guess a player's exact role; if right, attack them, "
                          "if wrong, exposed at dawn.",
                          tokens={"ritual": 2}, acts_at_night=True,
                          notes="failed guesses must be announced publicly at dawn"),
    "Puppeteer": RoleInfo(Alignment.EVIL, "Yakuza", True,
                          summary="Token: puppet a non-Yakuza player and chat in their place for the next Day.",
                          tokens={"puppet": 1}, acts_at_night=True,
                          tested=True, notes="moderator records the puppet; code refuses self or Yakuza puppets "
                          "and swaps who chats next day"),
    "Fabricator": RoleInfo(Alignment.EVIL, "Yakuza", True,
                           summary="Night: frame a player as Evil to alignment checks; a token also forges their will.",
                           tokens={"fabricator": 1}, acts_at_night=True,
                           tested=True, notes="forged wills via set_last_will"),
    "Clerk": RoleInfo(Alignment.EVIL, "Yakuza", True,
                      summary="Token: rig the next Day so anyone successfully nominated is executed.",
                      tokens={"clerk": 1}, acts_at_night=True,
                      tested=True, notes="moderator records the rig; code executes regardless of the vote"),
    "Smuggler": RoleInfo(Alignment.EVIL, "Yakuza", True,
                            summary="Token: swap two players for the night, so every action aimed at one lands on "
                            "the other. Immune to role-blocks.",
                            tokens={"swap": 2}, acts_at_night=True, unique=True,
                            notes="code applies the swap to the submitted actions before the Katana tally and the "
                            "moderator, and tells the Smuggler and both swapped players; kept untested (Kevin, "
                            "Oct 10): only one live swap so far"),
    "Ballot Stuffer": RoleInfo(Alignment.EVIL, "Yakuza", True,
                               summary="Token: their vote counts twice in the next Day's trials.",
                               tokens={"ballot": 2}, acts_at_night=True,
                               notes="moderator records the use with the stuff_ballot op; code doubles the vote "
                               "in the next day's trials"),
    "Fixer": RoleInfo(Alignment.EVIL, "Yakuza", True,
                      summary="Token: one player's trial votes count as the opposite the next Day; nobody is told.",
                      tokens={"fixer": 2}, acts_at_night=True,
                      notes="moderator records the use with the fix op (a visit); code reverses the counted vote "
                      "in the next day's trials"),
    "Diviner": RoleInfo(Alignment.EVIL, "Yakuza", True,
                        summary="Night: pick a player; a Yakuza gets Strong Defense, "
                        "else learn a role from them and neighbors (60% theirs).",
                        acts_at_night=True,
                        tested=True, notes="divine op: code draws the role from the group; "
                        "the moderator applies the Strong Defense"),
    "Mortician": RoleInfo(Alignment.EVIL, "Yakuza", True,
                          summary="Token: clean a player; if they die that night, their will is hidden and a Coroner "
                          "can't read their role.",
                          tokens={"mortician": 3}, acts_at_night=True,
                          tested=True, notes="clean via status 'cleaned'; code hides the will in the "
                          "reveal (and the role or alignment when --flips shows them; cause shown)"),
    "Wiretap": RoleInfo(Alignment.EVIL, "Yakuza", True,
                        summary="Passively reads every Day PM between any players.",
                        notes="code adds living Wiretaps to every Day PM's audience; not role-blockable"),
    "Informant": RoleInfo(Alignment.EVIL, "Yakuza", True,
                          tested=True, summary="Passively sees how every player voted in each trial.",
                          notes="code tells living Informants each secret trial's votes; not role-blockable"),
    # Neutral
    "Vulture": RoleInfo(Alignment.NEUTRAL, "Neutral", False,
                        summary="Wins alone if alive when few enough players remain at dawn. Learns a role for each "
                        "death, true only half the time.",
                        unique=True,
                        notes="code checks the living count at each dawn and ends the game when it wins; code tells "
                        "the death reports at dawn"),
    "Serial Killer": RoleInfo(Alignment.NEUTRAL, "Neutral", False,
                              summary="Night: Strong Attack on one player. Wins alone. Standard Defense.",
                              defense="Standard", acts_at_night=True),
    "Arsonist": RoleInfo(Alignment.NEUTRAL, "Neutral", False,
                         summary="Night: douse a player (only non-Good ones are told), or ignite all doused players "
                         "with a Strong Attack. Wins alone.",
                         defense="Standard", acts_at_night=True,
                         tested=True, notes="douses tracked as player status; code tells doused non-Good players"),
    "Jester": RoleInfo(Alignment.NEUTRAL, "Neutral", True,
                       summary="Wins if hanged; then a Guilty voter dies. Reads Evil to the Sheriff.",
                       defense="Basic",
                       tested=True, notes="hanging win and revenge in code"),
    "Executioner": RoleInfo(Alignment.NEUTRAL, "Neutral", True,
                            summary="Wins if their target is hanged; becomes a Jester if the target dies otherwise.",
                            defense="Basic",
                            tested=True, notes="target, win, leaving and turning into a Jester in code"),
}

DEFAULT_SETUP = [
    "Sheriff", "Medic", "Lookout", "Vigilante", "Vanilla Villager", "Vanilla Villager",
    "Grunt", "Pharmacist", "Fabricator",
    "Jester",
]


def role_status_table() -> str:
    """How each role is implemented, for `uv run mafia.py --list-roles`. Everything but the
    live-tested flag and notes is read from the code, so it can't go stale."""
    rows = [f"{'Role':<17} {'Night action':<12} {'Code hooks (roles/<role>.py)':<52} {'Night note':<10} "
            f"{'Live-tested':<11} Notes"]
    for role, info in ROLES.items():
        hooks = ", ".join(code_hooks(logic(role))) or "-"
        rows.append(f"{role:<17} {'yes' if info.acts_at_night else '-':<12} {hooks:<52} "
                    f"{'yes' if logic(role).night_note else '-':<10} {'yes' if info.tested else 'no':<11} "
                    f"{info.notes}")
    return "\n".join(rows)


# Every module in roles/ is a role file, which registers its hooks when imported (base is already loaded).
for _module in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{_module.name}")

assert LOGIC.keys() <= ROLES.keys(), f"@register names unknown roles: {LOGIC.keys() - ROLES.keys()}"
