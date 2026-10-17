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
    category: str  # the heading its rules paragraph is under (Investigative, Killing, Protective, Yakuza, ...)
    sheriff_evil: bool  # how the role appears to a Sheriff, before Katana/Fabricator effects (Ex-Con: to Seers too)
    summary: str = ""  # one line for the hover text on the role's icon in HTML logs; rules_1.txt is the full text
    defense: str = "None"
    tokens: dict[str, int] = field(default_factory=dict)
    acts_at_night: bool = False  # submits a night action, which the LLM moderator resolves
    unique: bool = False  # at most one player in a game may have this role
    tested: bool = False  # seen working in at least one live (API) game; update when it first is
    notes: str = ""  # implementation notes for --list-roles
    # Investigative roles: what they learn (Alignment check, Role info, ...), in code only. Neutral roles: Killing or
    # Chaos, their heading in the rules; Chaos reads Evil to the Sheriff, Killing Not Evil (rules R19)
    subcategory: str = ""
    # Its tokens never go above the starting count (rules: Oathsworn): Stocked never goes to it, and set_tokens
    # can't raise them
    token_cap: bool = False


ROLES: dict[str, RoleInfo] = {
    # Village
    "Vanilla Villager": RoleInfo(Alignment.GOOD, "Townsfolk", False,
                                 summary="No night action.",
                                 tested=True),
    "Sheriff": RoleInfo(Alignment.GOOD, "Investigative", False, subcategory="Alignment check",
                        summary="Night: investigate one player, learn Evil or Not Evil.",
                        acts_at_night=True,
                        tested=True, notes="Katana holder and framed players handled by the moderator"),
    "Tracker": RoleInfo(Alignment.GOOD, "Investigative", False, subcategory="Visit info",
                        summary="Night: track one player, learn whom they visited.",
                        acts_at_night=True, tested=True),
    "Lookout": RoleInfo(Alignment.GOOD, "Investigative", False, subcategory="Visit info",
                        summary="Night: watch one player, learn who visited them.",
                        acts_at_night=True, tested=True),
    "Seer": RoleInfo(Alignment.GOOD, "Investigative", False, subcategory="Alignment check",
                     summary="Each night: told whether two random players share an alignment; "
                     "a token lets them pick the pair.",
                     tokens={"seer": 1}, acts_at_night=True,
                     tested=True, notes="random pair each night unless a token is spent"),
    "Fortune Teller": RoleInfo(Alignment.GOOD, "Investigative", False, subcategory="Visit info",
                               summary="Every night: two labeled numbers, how many players were visited "
                               "and how many visited someone that night.",
                               tested=True, notes="numbers told at the end of the night"),
    "Oracle": RoleInfo(Alignment.GOOD, "Investigative", False, subcategory="Role info",
                       summary="Night: guess one player's exact role, learn whether it was right.",
                       acts_at_night=True, tested=True),
    "Eavesdropper": RoleInfo(Alignment.GOOD, "Investigative", False, subcategory="Vote and talk info",
                             summary="Night: pick a player; reads every PM they send or receive the next Day.",
                             acts_at_night=True, tested=True,
                             notes="moderator records the target with the eavesdrop op; code shows them the "
                             "target's PMs the next day"),
    "Archivist": RoleInfo(Alignment.GOOD, "Investigative", False, subcategory="Role info",
                          summary="Once (token): sees one role per other player, unnamed and shuffled; "
                          "half are real, the rest fakes.",
                          tokens={"archive": 1}, acts_at_night=True, tested=True,
                          notes="moderator records the use with the archive op; code draws the real half "
                          "and the fakes (any role, never a second unique one), and tells it at once"),
    "Census Taker": RoleInfo(Alignment.GOOD, "Investigative", False, subcategory="Alignment check",
                             summary="Night: count the Good or the Evil players (drawn at random) among a chosen "
                             "player and two random others.",
                             acts_at_night=True, tested=True,
                             notes="moderator records the use with the census op; code draws the group and the "
                             "alignment counted, counts true alignment and tells them"),
    "Profiler": RoleInfo(Alignment.GOOD, "Investigative", False, subcategory="Role info",
                         summary="Token: profile a player, learn three candidate roles for them, one true.",
                         tokens={"profile": 3}, acts_at_night=True, tested=True,
                         notes="moderator records the use with the profile op; code draws the decoys and tells them"),
    "Coroner": RoleInfo(Alignment.GOOD, "Investigative", False, subcategory="Role info",
                        summary="Token: examine a player who died before tonight, learn their role (not if a "
                        "Mortician cleaned them).",
                        tokens={"coroner": 3}, acts_at_night=True, tested=True,
                        notes="moderator records the use with the examine op (a dead target, not a visit); code "
                        "tells them the role, or that the body was cleaned"),
    "Chronicler": RoleInfo(Alignment.GOOD, "Investigative", False, subcategory="Vote and talk info",
                           summary="Token: marks a player; if they ever die, their role is revealed to everyone "
                           "(unless a Mortician cleans them).",
                           tokens={"chronicler": 2}, acts_at_night=True, tested=True,
                           notes="moderator records the use with the mark op (a visit); code sets status 'marked', "
                           "and the death announcement reveals the role or says the clean hid it"),
    "Auditor": RoleInfo(Alignment.GOOD, "Investigative", False, subcategory="Vote and talk info",
                        summary="Night: audit a player, learn all their nomination and trial votes from that Day.",
                        acts_at_night=True, tested=True,
                        notes="moderator records the use with the audit op (a visit); code reads the Day's votes "
                        "and tells them"),
    "Bloodhound": RoleInfo(Alignment.GOOD, "Investigative", False, subcategory="Vote and talk info",
                           summary="Every night: learns the total attacks three random players have made this game. "
                           "Token: choose one of the three.",
                           tokens={"scent": 2}, acts_at_night=True, tested=True,
                           notes="moderator lists each night's attackers with the attacks op and records a token use "
                           "with the track op; code draws the group, counts and tells them"),
    "Cartographer": RoleInfo(Alignment.GOOD, "Investigative", False, subcategory="Visit info",
                             summary="Every night: learns the sizes of the night's visit groups (visits linking "
                             "players either way). Token: learns the names in one player's group.",
                             tokens={"map": 2}, acts_at_night=True, tested=True,
                             notes="moderator lists every night's visits with record_visits and records a token use "
                             "with the map op; code finds the groups and tells them"),
    "Scout": RoleInfo(Alignment.GOOD, "Investigative", False, subcategory="Visit info",
                      summary="Every night: learns three players (maybe themselves) who were each in a different "
                      "visit group.", tested=True,
                      notes="passive; code draws the names from the moderator's record_visits list and tells them"),
    "Insomniac": RoleInfo(Alignment.GOOD, "Investigative", False, subcategory="Role info",
                          summary="Token: learns the roles (no names) of up to 3 random players who visited someone "
                          "that night.",
                          tokens={"insomniac": 2}, acts_at_night=True, tested=True,
                          notes="moderator records the use with the stay_awake op; code draws the visitors from "
                          "record_visits and tells them at the end of the night"),
    "Medic": RoleInfo(Alignment.GOOD, "Protective", False,
                      summary="Night: protect a player (Standard Defense; 1 token for Strong, 1 token to protect "
                      "yourself).",
                      tokens={"medic": 2}, acts_at_night=True,
                      tested=True, notes="tokens tracked via set_tokens; briefing lists token costs"),
    "Trapper": RoleInfo(Alignment.GOOD, "Protective", False,
                        summary="Night: trap a player; on a later night the trap stops one attack on them and "
                        "deals a visiting attacker a Strong Attack.",
                        acts_at_night=True,
                        tested=False,
                        notes="moderator records each trap with the set_trap op (null: removed); code keeps the traps "
                        "(several may share a player), and for the attacks the moderator lists on a trapped player "
                        "(spring_trap op) checks which are armed, picks the stopped attacks, clears them and tells the "
                        "Trappers"),
    "Kitsune": RoleInfo(Alignment.GOOD, "Protective", False,
                        summary="Night: a fox charm swallows one attack on a player; the Kitsune must later "
                        "release it, same level and cause.",
                        tokens={"kitsune": 1}, acts_at_night=True, tested=True,
                        notes="moderator records the charm's attacks and the release with ops; code picks the "
                        "swallowed attack, keeps the charge and tells the Kitsune"),
    "Mirror Maker": RoleInfo(Alignment.GOOD, "Protective", False,
                             summary="Night: a token places a mirror that stops every attack on a player and sends "
                             "each visiting attack back at its attacker.",
                             tokens={"mirror": 2}, acts_at_night=True,
                             notes="moderator lists the attacks on the mirrored player (mirror op); code picks the "
                             "stopped ones, says which are reflected at whom and tells the Mirror Maker its count"),
    "Vigilante": RoleInfo(Alignment.GOOD, "Killing", False,
                          summary="Night: shoot a player, 1-3 tokens for a Basic, Standard or Strong Attack; "
                          "learns the role of a player it kills.",
                          tokens={"vigilante": 3}, acts_at_night=True,
                          tested=True, notes="moderator resolves the shot; code tells the victim's role on a kill"),
    "Enforcer": RoleInfo(Alignment.GOOD, "Killing", False,
                         summary="Night: visit a player (a token: two) and attack one who made an Attack tonight; "
                         "Basic, or Strong for a token.",
                         tokens={"enforcer": 3}, acts_at_night=True, tested=True,
                         notes="moderator resolves it; briefing lists the token costs"),
    "Veteran": RoleInfo(Alignment.GOOD, "Killing", False,
                        summary="Can't be role-blocked. Token: go on alert, Standard Defense "
                        "and a Strong Attack on every visitor.",
                        tokens={"alert": 3}, acts_at_night=True,
                        tested=True, notes="moderator resolves the alert; night note lists its effects"),
    "Sniper": RoleInfo(Alignment.GOOD, "Killing", False,
                       summary="Day: an anonymous shot with 1-3 tokens (Basic, Standard or Strong Attack), fired "
                       "after a random 0 to n-1 more speaking turns; everyone hears it.",
                       tokens={"sniper": 3},
                       tested=True, notes="day action (R25): taken on its own speaking turn, fired by code after a "
                       "random delay of speaking turns (or when the Day ends); no moderator"),
    "Prosecutor": RoleInfo(Alignment.GOOD, "Support", False,
                           summary="Token: prosecute a player, who goes straight to trial the next Day.",
                           tokens={"prosecutor": 2}, acts_at_night=True,
                           tested=True, notes="moderator records the prosecution; code runs the trial next day"),
    "Party Animal": RoleInfo(Alignment.GOOD, "Support", False,
                             summary="Night: role-block one player. Immune to role-blocks.",
                             acts_at_night=True, tested=True,
                             notes="moderator resolves the block; code leaves last night's target out of its "
                             "choices (R9)"),
    "Mayor": RoleInfo(Alignment.GOOD, "Support", False,
                      summary="Day, once: reveal as the Mayor (confirmed); then trial votes count twice.",
                      unique=True, tested=True,
                      notes="day action (act) on its own speaking turn, announced at once, not after R25's delay; code "
                      "doubles its trial votes after the reveal (Kevin, Oct 15)"),
    "Magistrate": RoleInfo(Alignment.GOOD, "Support", False,
                           summary="Day, once: call a second session, so that Day's first hanging doesn't end it.",
                           tokens={"session": 1}, unique=True,
                           notes="day action (act) after R25's delay, or at once when a hanging comes first; core "
                           "day code asks RoleLogic.hanging_keeps_day_going (Kevin, Oct 17)"),
    "Roleplayer": RoleInfo(Alignment.GOOD, "Outsider", False,
                           summary="Thinks they are a random Investigative role; gets random results.",
                           acts_at_night=True, tested=True,
                           notes="code assigns the fake role (with its tokens and night prompts); the moderator "
                           "draws its results at random, or for a role set to roleplayer='code' (Coroner, Profiler, "
                           "Archivist, Bloodhound, Scout, Cartographer, Insomniac; Oct 16, untested live) records its "
                           "op as for a real user and the role's code draws them (fake_carry_out, is_fake)"),
    "Saint": RoleInfo(Alignment.GOOD, "Outsider", False,
                      summary="No night action. If hanged, the Village loses at once and the Yakuza win.",
                      unique=True, notes="code ends the game when it's hanged (RoleLogic.decides_game)"),
    # Yakuza
    "Grunt": RoleInfo(Alignment.EVIL, "Yakuza", True,
                      summary="No night action of its own; shares the Katana.",
                      tested=True),
    "Pharmacist": RoleInfo(Alignment.EVIL, "Yakuza", True,
                           summary="Night: role-block one player. Immune to role-blocks.",
                           acts_at_night=True, tested=True,
                           notes="moderator resolves the block; code leaves last night's target out of its "
                           "choices (R9)"),
    "Ritualist": RoleInfo(Alignment.EVIL, "Yakuza", True,
                          summary="Token: guess a player's exact role; if right, attack them, "
                          "if wrong, exposed at dawn.",
                          tokens={"ritual": 2}, acts_at_night=True, tested=True,
                          notes="moderator resolves the guess; its night note says to announce a wrong guess with a "
                          "public tell at night, read out at dawn"),
    "Fabricator": RoleInfo(Alignment.EVIL, "Yakuza", True,
                           summary="Night: frame a player as Evil to alignment checks; a token also forges their will.",
                           tokens={"fabricator": 1}, acts_at_night=True,
                           tested=True, notes="forged wills via set_last_will"),
    "Ballot Stuffer": RoleInfo(Alignment.EVIL, "Yakuza", True,
                               summary="Token: at a trial vote, may make that vote count twice.",
                               tokens={"ballot": 2},
                               notes="chosen with the trial vote itself (Kevin, Oct 13); code spends the token and "
                               "doubles that vote; no night action"),
    "Fixer": RoleInfo(Alignment.EVIL, "Yakuza", True,
                      summary="Token: one player's trial votes count as the opposite the next Day; nobody is told.",
                      tokens={"fixer": 2}, acts_at_night=True, tested=True,
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
                        tested=True, notes="code adds living Wiretaps to every Day PM's audience; not role-blockable"),
    "Informant": RoleInfo(Alignment.EVIL, "Yakuza", True,
                          tested=True, summary="Passively sees how every player voted in each trial.",
                          notes="code tells living Informants each secret trial's votes; not role-blockable"),
    "Talent Agent": RoleInfo(Alignment.EVIL, "Yakuza", True,
                             summary="Token (one a night): learn a random non-Yakuza role in play and one not, or how "
                             "many living players have a named role.",
                             tokens={"talent": 3}, acts_at_night=True, tested=True,
                             notes="moderator records the scout_talent op; code reads true roles and tells the result"),
    "Oathsworn": RoleInfo(Alignment.EVIL, "Yakuza", True,
                          summary="One token, never more: mark a player; if the Oathsworn is dead by the next Night, "
                          "a Divine Attack hits them and everyone who visits them.",
                          tokens={"oath": 1}, token_cap=True, acts_at_night=True,
                          notes="mark recorded with the swear op; code says the next Night whether it fires; after "
                          "record_visits the moderator's fulfil_oath op lists the Divine Attacks, which it resolves"),
    # Neutral Killing
    "Serial Killer": RoleInfo(Alignment.NEUTRAL, "Neutral", False, subcategory="Killing",
                              summary="Night: Strong Attack on one player. Wins alone. Standard Defense.",
                              defense="Standard", acts_at_night=True, tested=True),
    "Arsonist": RoleInfo(Alignment.NEUTRAL, "Neutral", False, subcategory="Killing",
                         summary="Night: douse a player (only non-Good ones are told), or ignite all doused players "
                         "with a Strong Attack. Wins alone.",
                         defense="Standard", acts_at_night=True,
                         tested=True, notes="douses tracked as player status; code tells doused non-Good players"),
    "Werewolf": RoleInfo(Alignment.NEUTRAL, "Neutral", False, subcategory="Killing",
                         summary="Even nights only: rampage at a player's house (a Strong Attack on them and every "
                         "visitor) or at home (on every visitor). Wins alone. Standard Defense.",
                         defense="Standard", acts_at_night=True,
                         notes="asked for an action only on even nights; moderator resolves the attacks, after the "
                         "rampage op lists them from record_visits"),
    "Bounty Hunter": RoleInfo(Alignment.NEUTRAL, "Neutral", False, subcategory="Killing",
                              summary="Has 3 random targets and one Strong Attack; wins and leaves once 2 targets die "
                              "by its attack or by a hanging it voted Guilty in.",
                              tokens={"attack": 1}, acts_at_night=True, tested=True,
                              notes="targets, bounty credit (from death killers and Guilty voters), win, loss and "
                              "leaving in code; moderator resolves the attack"),
    "Hitman": RoleInfo(Alignment.NEUTRAL, "Neutral", False, subcategory="Killing",
                       summary="Night: Basic Attack on one player; wins and leaves once its attacks kill 2 Good "
                       "players, loses and leaves if one kills a non-Good player.",
                       acts_at_night=True, unique=True, tested=True,
                       notes="moderator resolves the attack (by=Hitman); code counts kills from death killers, "
                       "tells it, handles win, loss and leaving"),
    # Neutral Chaos
    "Vulture": RoleInfo(Alignment.NEUTRAL, "Neutral", True, subcategory="Chaos",
                        summary="Wins alone if alive when few enough players remain at dawn. Each night may visit a "
                        "player: if they die that night, learns their role and powers up.",
                        acts_at_night=True, unique=True,
                        notes="moderator records the visit (scavenge); code checks at night end whether the target "
                        "died, tells the role and applies the power-up (threshold or Defense, told to the moderator "
                        "each night), and checks the living count at each dawn"),
    "Magpie": RoleInfo(Alignment.NEUTRAL, "Neutral", True, subcategory="Chaos",
                       summary="Night: steal a token from a player; wins and leaves once it has stolen from 3 "
                       "different players. Basic Defense.",
                       defense="Basic", acts_at_night=True, tested=True,
                       notes="moderator records the steal; code takes the token at the end of the night, tells both, "
                       "handles the win; random setups need a third of roles with tokens"),
    "Decoy": RoleInfo(Alignment.NEUTRAL, "Neutral", True, subcategory="Chaos",
                      summary="Wins if it dies at night; then the next Day names 3 players, at least one of them its "
                      "killer.",
                      tested=True, notes="win, role reveal and the 3 names in code, from the kill's `by`"),
    "Jester": RoleInfo(Alignment.NEUTRAL, "Neutral", True, subcategory="Chaos",
                       summary="Wins if hanged; then a Guilty voter dies.",
                       defense="Basic",
                       tested=True, notes="hanging win and revenge in code"),
    "Executioner": RoleInfo(Alignment.NEUTRAL, "Neutral", True, subcategory="Chaos",
                            summary="Wins if their target is hanged; becomes a Jester if the target dies otherwise.",
                            defense="Basic",
                            tested=True, notes="target, win, leaving and turning into a Jester in code"),
}



@dataclass(frozen=True)
class RetiredRole:
    """A role taken out of the game (rules, setups, scripts), kept so logs written while it existed still read
    right, even after its name is reused for a new role. Log readers rename it with log_role."""
    info: RoleInfo  # as it was, for faction, stats and the HTML log's hover text
    until: int  # the first LOG_VERSION without it: a log older than this means the old role by this name
    icon: str  # its icon in roles/icons/retired/ (the file name), so a new role can take the name's icon file
    now: tuple[str, tuple[str, ...]]  # what a checkpoint saved with it resumes as: (role, traits added)
    rules: str = ""  # its rules_1.txt paragraph when retired, shown in old logs' hover text (git has the rest)


# Kevin, Oct 12 2026: old logs and analysis must keep working when a role is deleted, and names may be reused.
# Deleting a role means moving its ROLES entry here (tests/role_names.json lists every name ever used, so a test
# fails if one disappears unrecorded). A name retired more than once gets a list in order of `until`.
RETIRED: dict[str, list[RetiredRole]] = {
    "Cardinal": [RetiredRole(RoleInfo(Alignment.GOOD, "Outsider", False,
                                      summary="If they die, a random living Good player is dealt a Divine Attack.",
                                      tested=True),
                             until=51, icon="cardinal.svg", now=("Vanilla Villager", ("Cursed",)),  # trait
                             rules="If you die, a random living Good player (if any) is dealt a Divine Attack at "
                                   "the end of the night: the night you died, or the night after the Day you died. "
                                   "It comes after all of that night's other actions and attacks, so the victim is "
                                   "drawn from the Good players still alive then, and it counts as a death that "
                                   "night.")],
    # Kevin, Oct 13 2026: its two parts are traits now, Notorious (reads Evil) and Sleepwalker (the random visit).
    "Ex-Con": [RetiredRole(RoleInfo(Alignment.GOOD, "Outsider", True,
                                    summary="Visits a random player each night without knowing whom; "
                                    "reads Evil to alignment checks.", tested=True),
                           until=70, icon="ex-con.svg", now=("Vanilla Villager", ("Notorious", "Sleepwalker")),
                           rules="Appears: Evil to alignment checks (R19). Night: every night you visit a random "
                                 "player other than yourself, and you aren't told whom. A role-block stops the visit "
                                 "(R7).")],
    # Kevin, Oct 14 2026: retired as rarely used or uninteresting (notes/design-review-2026-10-14.md).
    "Surveyor": [RetiredRole(RoleInfo(Alignment.GOOD, "Investigative", False, subcategory="Role info",
                         summary="Token: survey a player; learns one random role among them and their two neighbors.",
                         tokens={"survey": 3}, acts_at_night=True, tested=True,
                         notes="moderator records the use with the survey op; code picks the group and draws the role"),
        until=74, icon="surveyor.svg", now=("Vanilla Villager", ()),
        rules=('Tokens: 3 survey tokens. Night: may spend a token to survey one player other than yourself. The '
              'group is that player plus their nearest neighbor on each side in the circle (R11) among the players '
              'alive at the start of the night, skipping yourself and never counting anyone twice (so with only one '
              'or two other players alive, the group is smaller). You are told who was in the group and the exact '
              'role of one of them chosen at random, but not whose it is. Players who die that night can still be '
              'chosen. This is an exact-role check (R19).'))],
    "Juror": [RetiredRole(RoleInfo(Alignment.GOOD, "Investigative", False, subcategory="Vote and talk info",
                      summary="Night: name two players, learn how often they voted the same way all game.",
                      acts_at_night=True, tested=True,
                      notes="moderator records the use with the jury op (Astral); code counts the shared votes "
                      "and tells them"),
        until=74, icon="juror.svg", now=("Vanilla Villager", ()),
        rules=('Night: may name two different players other than yourself (dead players allowed; Astral Visit). You '
              'learn how many times they voted the same way, over every Day so far, counted separately for trial '
              'votes (Guilty/Innocent) and nomination votes (Yes/No), e.g. "the same way in 3 of 4 trial votes and '
              '5 of 9 nomination votes". Only votes both of them cast count, and not votes on the nomination or '
              'trial of either of them. A doubled vote (Ballot Stuffer) counts once. You learn only the totals, not '
              'which votes they agreed on.'))],
    "Scrutineer": [RetiredRole(RoleInfo(Alignment.GOOD, "Investigative", False, subcategory="Vote and talk info",
                           summary="Night: learn how many of a player and two random others voted Guilty in each of "
                           "the Day's trials.",
                           acts_at_night=True, tested=True,
                           notes="moderator records the use with the scrutinize op (Astral); code draws the group, "
                           "counts the Guilty votes and tells them"),
        until=74, icon="scrutineer.svg", now=("Vanilla Villager", ()),
        rules=("Night: may scrutinize one player other than yourself who voted in the Day's trials (Astral Visit). "
              'Code adds two random other players who voted in those trials (never you), and you learn the three '
              'names and, for each trial of the Day just before this Night, how many of the three voted Guilty, '
              'e.g. "2 in the trial of Erin; 0 in the trial of Frank". You don\'t learn which of them voted which '
              'way. A doubled vote (Ballot Stuffer) counts once. If there was no trial that Day, you learn that.'))],
    "Accountant": [RetiredRole(RoleInfo(Alignment.GOOD, "Investigative", False, subcategory="Vote and talk info",
                           summary="Night: audit one player, learn their total token count.",
                           acts_at_night=True,
                           tested=True, notes="moderator records the audit with the count_tokens op; code tells the "
                           "true total at the end of the night, after token changes (Magpie steals); Roleplayers "
                           "show 0"),
        until=74, icon="accountant.svg", now=("Vanilla Villager", ()),
        rules=('Night: may audit one player. Learn how many tokens they have in total at the end of the night, after '
              'any they spent that night and any a Magpie stole (token count, R19). You learn only the total, not '
              'what kind of tokens they are. If their role changed at the end of this night, the role just before '
              'the change counts.'))],
    "Philanthropist": [RetiredRole(RoleInfo(Alignment.GOOD, "Support", False,
                               summary="Token: hand a player one token of their own role's kind.",
                               tokens={"philanthropy": 2}, acts_at_night=True,
                               tested=True, notes="moderator records the gift with the give_token op; "
                               "code adds the token and tells the recipient"),
        until=74, icon="philanthropist.svg", now=("Vanilla Villager", ()),
        rules=('Tokens: 2 philanthropy tokens. Night: may spend a token to hand another player one token of their '
              "own role's kind (e.g. a medic token to a Medic; one kind chosen at random if their role has "
              'several). They are told a Philanthropist handed them a token. If their role has no tokens, they are '
              "told they threw it away because they have no use for it, so it doesn't count toward their tokens "
              '(e.g. for the Accountant). You are not told which happened.'))],
    "Puppeteer": [RetiredRole(RoleInfo(Alignment.EVIL, "Yakuza", True,
                          summary="Token: puppet a player and chat in their place for the next Day.",
                          tokens={"puppet": 1}, acts_at_night=True,
                          tested=True, notes="moderator records the puppet (any player; self does nothing); "
                          "code swaps who chats next day"),
        until=74, icon="puppeteer.svg", now=("Grunt", ()),
        rules=('Tokens: 1 puppet token. Night: may spend a token to puppet any player for the following Day '
              '(puppeting yourself changes nothing). That Day, they are told they are being puppeted, and they '
              "can't chat or see private messages; nobody else is told. You chat publicly and privately in their "
              'place (including seeing their private messages) and can set their claim, which appears in the ledger '
              'as theirs; that is all you can do for them. They still nominate, vote and so on as normal. It lasts '
              'one Day.'))],
    "Clerk": [RetiredRole(RoleInfo(Alignment.EVIL, "Yakuza", True,
                      summary="Token: rig the next Day so anyone successfully nominated is executed.",
                      tokens={"clerk": 1}, acts_at_night=True,
                      tested=True, notes="moderator records the rig; code executes regardless of the vote"),
        until=74, icon="clerk.svg", now=("Grunt", ()),
        rules=("Tokens: 1 clerk token. Night: may spend a token to rig the next Day's votes. On a rigged Day, anyone "
              'successfully nominated is executed. The Guilty/Innocent vote still happens; if a majority votes '
              'Guilty, the rig is not announced, otherwise it is announced publicly.'))],
    "Smuggler": [RetiredRole(RoleInfo(Alignment.EVIL, "Yakuza", True,
                            summary="Token: swap two players for the night, so every action aimed at one lands on "
                            "the other. Immune to role-blocks.",
                            tokens={"swap": 2}, acts_at_night=True, unique=True,
                            notes="code applies the swap to the submitted actions before the Katana tally and the "
                            "moderator, and tells the Smuggler and both swapped players; kept untested (Kevin, "
                            "Oct 10): only one live swap so far"),
        until=74, icon="smuggler.svg", now=("Grunt", ()),
        rules=('Immune to role-blocks. Tokens: 2 swap tokens. Night: may spend a token to swap two different living '
              'players (yourself included) for the night. You visit both of them. Both swapped players are '
              'told they were swapped, but not with whom. (Swaps: every action that night aimed at one of them lands '
              'on the other, and its result names the player its user chose.)'))],
}


def retired_entry(name: str, log_version: int) -> tuple[str, RetiredRole] | None:
    """(label, entry) if `name` in a log of this version is a role since retired, else None. The label is the old
    name while nothing reuses it and each entry is the name's only one, else e.g. "Cardinal (before v51)"."""
    for entry in RETIRED.get(name, []):
        if log_version < entry.until:
            plain = name not in ROLES and len(RETIRED[name]) == 1
            return (name if plain else f"{name} (before v{entry.until})"), entry
    return None


def log_role(name: str, log_version: int) -> str:
    """A role name as a log of this version wrote it, renamed if it meant a role since retired (retired_entry)."""
    found = retired_entry(name, log_version)
    return found[0] if found else name


RETIRED_BY_LABEL: dict[str, RetiredRole] = {}
for _name, _entries in RETIRED.items():
    for _entry in _entries:
        _label = retired_entry(_name, _entry.until - 1)
        assert _label, _name
        RETIRED_BY_LABEL[_label[0]] = _entry


def role_info(name: str) -> RoleInfo | None:
    """The RoleInfo of a current role, or of a retired one by its log_role label; None if neither."""
    return ROLES.get(name) or (RETIRED_BY_LABEL[name].info if name in RETIRED_BY_LABEL else None)


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
