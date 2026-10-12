"""The hooks a role can implement, and the registry core code looks roles up in.

Core code (state.py, players.py, day.py, night.py) calls these hooks at fixed points without naming
any role, so a role's code-handled effects live in one file under roles/. Roles without a file get
the defaults, which do nothing; the LLM moderator resolves their abilities from the rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from state import Game, Player


class Alignment(str, Enum):
    GOOD = "Good"  # the Village faction
    EVIL = "Evil"  # the Yakuza faction
    NEUTRAL = "Neutral"  # each Neutral player is their own faction


class Status:
    """Player.status keys that code reads. The moderator may also set its own keys (e.g. doused)."""

    LEFT = "left"  # left the game (a winning Executioner); not a death
    CLEANED = "cleaned"  # Mortician: the death reveal hides role and will
    TARGET = "target"  # Executioner's target
    FAKE_ROLE = "fake_role"  # the role a Roleplayer believes they have
    DOUSED = "doused"  # Arsonist: set by the moderator on a doused player, cleared by an ignite
    MARKED = "marked"  # Chronicler: on the marked player, the first Chronicler to mark them
    TRAPPED_BY = "trapped_by"  # Trapper: on the trapped player, the Trapper's name until the trap is used or replaced
    SET_AT_SETUP = (TARGET, FAKE_ROLE)  # role hooks read these directly, so the moderator can't change them


@dataclass(frozen=True)
class RecordedAction:
    """A night action the moderator records with one apply_changes op and code then carries out
    (RoleLogic.carry_out). @register builds the role's op, its checks and its night note from this."""

    op: str  # the op's name
    does: str  # what the op does, after "the <role> `by`", for the tool description: e.g. "surveys player"
    then: str  # what code does next, for the night note: e.g. "code tells them one random role in the group"
    token: str = ""  # the token kind each use spends; "" for an every-night action
    # "other": another player alive at the start of the night; "any": themselves too; "dead": a player who died
    # before the night began (not one who left); "": none
    target: str = "other"
    visit: bool = False  # the night note says the action visits its target (rules R6)
    note: str = ""  # anything else the moderator must know, appended to the night note


@dataclass(frozen=True)
class DayAction:
    """What a role may do on its own Day speaking turns (not trial turns, not while puppeted; rules R25), offered by
    RoleLogic.day_action, taken by RoleLogic.carry_out_day_action and carried out in RoleLogic.after_day_turn or
    RoleLogic.at_day_end."""

    fields: dict[str, dict]  # extra answer fields, named as in players.SHARED_FIELDS so the shared schema stays fixed
    text: str  # what the turn's task tells the player about them


ATTACK_LEVELS = ("None", "Basic", "Standard", "Strong", "Divine")  # rules R3, lowest first


def attack_kills(attack: str, defense: str) -> bool:
    """Rules R3: an Attack kills iff its level is strictly higher than the target's Defense."""
    return ATTACK_LEVELS.index(attack) > ATTACK_LEVELS.index(defense)


class RoleLogic:
    """Defaults for every hook. Subclass it in roles/<role>.py and decorate with @register.
    Per-game state a role needs goes in game.role_state, keyed by something role-specific."""

    role: str = ""  # set by @register
    # A night action recorded with an op and carried out by code (see RecordedAction); the role implements
    # carry_out, and target_error for any check beyond the standard ones.
    action: RecordedAction | None = None
    # The night action's target and second_target may name any player, dead ones included (Juror); otherwise they
    # are living players (or, for a RecordedAction with target "dead", players who died before the night).
    targets_anyone: bool = False
    blocks_win: bool = True  # False for Neutrals the win check ignores (rules: "if we ignore Jesters...")
    # False for roles whose results code delivers (live PMs, random samples), which the moderator can't fake
    # for a Roleplayer who believes they have the role.
    roleplayer_can_fake: bool = True
    # Reminder for the moderator's night resolution, for effects with no submitted action or that
    # need a special op. Included when anyone in the game has (or had) the role.
    night_note: str = ""
    # Code gives this role's user the result of their night action (or, by the rules, nothing), so a
    # moderator tell() to them on a night they acted is held once with a note (the moderator resends it
    # if it's about something else, e.g. an attack). Night checks caught redundant and leaking tells.
    code_tells_user: bool = False
    # Order of at_night_end among roles, lowest first: effects that change tokens (Magpie) before results that read
    # them (Accountant).
    night_end_order: int = 0
    # Extra apply_changes ops for the moderator, offered only when someone in the game has the role:
    # op -> (required fields, optional fields, description shown in the tool). apply_op carries them out.
    ops: dict[str, tuple[set[str], set[str], str]] = {}

    def fits_setup(self, roles: list[str]) -> bool:
        """Whether random setups (setups.py) may include this role among these roles (the Magpie needs enough
        token holders). Hand-picked role lists aren't checked."""
        return True

    def setup(self, game: Game, p: Player) -> None:
        """After seats and the Katana are assigned. Use game.rng for anything random."""

    def shown_role(self, p: Player) -> str:
        """The role the player is told they have."""
        return f"{p.role} ({p.info.alignment.value})"

    def acts_at_night(self, p: Player) -> bool:
        """Whether the player is asked for a night action (Yakuza always are, for the Katana vote)."""
        return p.info.acts_at_night

    def automatic_action(self, game: Game, p: Player) -> dict | None:
        """A night action code draws for a living player each night without asking them (e.g. the Ex-Con's random
        visit), in night_action_schema's shape. It goes in the night's actions for the moderator, the logs and the
        reveal, marked "automatic"; the player's own night history leaves it out."""
        return None

    def briefing(self, game: Game, p: Player) -> list[str]:
        """Extra sentences for the player's role briefing (shown in every prompt)."""
        return []

    def on_death(self, game: Game, p: Player, guilty_voters: list[str] | None) -> None:
        """This player just died. guilty_voters is set only for an execution by hanging."""

    def reveals_on_death(self, game: Game, dead: Player) -> str | None:
        """Why this death's announcement also shows the dead player's role (e.g. "They had been marked by a
        Chronicler"), or None. Called once per registered role. A Mortician's clean still hides the role, and
        the announcement says so."""
        return None

    def on_other_death(self, game: Game, me: Player, dead: Player, guilty_voters: list[str] | None) -> None:
        """Another player just died; called for every living player of this role."""

    def hears_pm(self, game: Game, me: Player, speaker: str, to: str) -> bool:
        """Whether this living, unpuppeted player also reads the contents of a Day private message from
        `speaker` to `to` (Wiretap, Eavesdropper)."""
        return False

    def day_action(self, game: Game, p: Player) -> DayAction | None:
        """What this living player may do on this Day speaking turn (rules R25), or None."""
        return None

    def carry_out_day_action(self, game: Game, p: Player, answer: dict) -> None:
        """Takes the day_action fields of this player's turn answer (any may be null: nothing to do). Its effect
        waits for a later turn (after_day_turn), so its timing doesn't show whose turn it was (rules R25)."""

    def after_day_turn(self, game: Game, p: Player) -> None:
        """A Day speaking turn of `p` (with any trial it started) just ended: day actions due now take effect (rules
        R25). Called once per role among the game's players, in name order; the game ends here if one faction is
        left."""

    def at_day_end(self, game: Game) -> None:
        """The Day is ending (and the game isn't over): day actions still waiting take effect (rules R25)."""

    def reverses_trial_vote(self, game: Game, voter: Player) -> bool:
        """Whether this role's effect counts `voter`'s Guilty/Innocent vote today as the opposite (Fixer). Called once
        per registered role, whether or not anyone has it."""
        return False

    def sees_trial_votes(self, game: Game, me: Player) -> bool:
        """Whether this living player is privately told how everyone voted in each secret trial (Informant)."""
        return False

    def trial_vote_weight(self, game: Game, p: Player) -> int:
        """How many votes this player's Guilty/Innocent vote counts as today (Ballot Stuffer)."""
        return 1

    def check_op(self, game: Game, change: dict) -> str | None:
        """Why one of this role's ops can't be carried out (the whole batch is then refused, so nothing is
        half-applied), or None if it can. Fields are already checked against `ops`. For a RecordedAction: its
        user has the role and was alive when the night began (R10) with a token to spend, and its target was
        alive then too, then target_error."""
        assert self.action, f"{self.role} has ops but no RecordedAction: override check_op and apply_op"
        by = game.player(change["by"])
        if error := token_user_error(game, by.name, self.role, self.action.token or None):
            return error
        target = game.player(change["player"]) if self.action.target else None
        if target and self.action.target == "dead":
            if target.name not in dead_before_tonight(game):
                return f"{target.name} hadn't died before the night began"
        elif target and not acted_tonight(game, target):
            return f"{target.name} wasn't alive at the start of the night"
        if target is by and self.action.target == "other" and not swap_partner(game, by.name):
            return f"{'an' if self.role[0] in 'AEIOU' else 'a'} {self.role} can't target themselves"
        return self.target_error(game, by, target)

    def apply_op(self, game: Game, change: dict) -> str | None:
        """Carry out one of this role's ops. Fields are already checked against `ops`, and player
        names against the game. For a RecordedAction: spends the token, then carry_out. May return a result the
        moderator needs to go on (shown in apply_changes' answer), e.g. which attack a Kitsune's charm swallowed."""
        assert self.action, f"{self.role} has ops but no RecordedAction: override check_op and apply_op"
        by = game.player(change["by"])
        if self.action.token:
            spend_token(game, by.name, self.action.token)
        self.carry_out(game, by, game.player(change["player"]) if self.action.target else None)
        return None

    def target_error(self, game: Game, by: Player, target: Player | None) -> str | None:
        """A RecordedAction's role-specific check (e.g. a Puppeteer can't puppet a Yakuza): why it can't be
        carried out, or None."""
        return None

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        """A RecordedAction's effect, once checked and its token spent. Tell a private result with game.tell."""
        raise NotImplementedError(self.role)

    def before_resolution(self, game: Game, actions: dict[str, dict]) -> None:
        """After the night's actions are in (and any Katana revote), before the Katana tally and the moderator's
        resolution: may change `actions` in place (Smuggler swaps). Called once per registered role."""

    def at_night_end(self, game: Game) -> None:
        """End of each night, after the moderator's resolution and any revenge, before the dawn reveal and the
        win check. Called once per registered role, whether or not anyone has it."""

    def at_dawn(self, game: Game) -> None:
        """Start of each day, after the night's deaths are revealed. Called once per registered role,
        whether or not anyone has it, so it can act after its player has died."""


LOGIC: dict[str, RoleLogic] = {}
DEFAULT = RoleLogic()


def acted_tonight(game: Game, p: Player) -> bool:
    """Whether p was alive when the night began: still alive, or killed earlier in tonight's resolution. Night
    actions are simultaneous (rules R10), so ops for a player killed tonight still apply, whatever order the
    moderator sends them in, and an effect set for the next Day survives its user's death unless it needs them to
    act that Day (R21)."""
    return p.alive or (p.death is not None and p.death["day"] == game.day and p.death["phase"] == "night") \
        or game.role_state.get(LEFT_AT, {}).get(p.name) == [game.day, "night"]


def attacks_error(game: Game, attacks: object, visit: bool = False) -> str | None:
    """What's wrong with an op's list of tonight's attacks on a player, each {by, attack (its level), cause (how its
    kill would be announced)}, plus a `visit` flag when asked for (Kitsune, Trapper)."""
    fields = "{by, attack, cause, visit}" if visit else "{by, attack, cause}"
    if not isinstance(attacks, list) or not all(isinstance(a, dict) for a in attacks):
        return f"attacks must be a list of {fields}"
    names = {q.name for q in game.players}
    for a in attacks:
        if a.get("by") not in names:
            return f"each attack needs `by`, a player's name (got {a.get('by')!r})"
        if a.get("attack") not in ATTACK_LEVELS[1:]:
            return f"each attack's level must be one of {list(ATTACK_LEVELS[1:])} (got {a.get('attack')!r})"
        if not isinstance(a.get("cause"), str) or not a["cause"].strip():
            return "each attack needs a cause: how its kill would be announced, e.g. 'Katana'"
        if visit and not isinstance(a.get("visit"), bool):
            return "each attack needs visit: true if it was a visit by its attacker, false if Astral or no visit"
    return None


STOPPED = "stopped_attacks"  # game.role_state: {"night": day, target: [(by, cause), ...]}, attacks stopped tonight
CATCHABLE = ATTACK_LEVELS[1:4]  # Basic, Standard, Strong: Divine Attacks ignore protections that stop one attack


def stop_one_attack(game: Game, target: str, attacks: list[dict]) -> dict | None:
    """Picks at random the one non-Divine attack in `attacks` that a protection stopping a single attack (a fox charm,
    a trap) stops on `target`, never one another such protection already stopped there tonight, whatever the order
    or lists the moderator sends."""
    store = game.role_state.get(STOPPED)
    if not store or store.get("night") != game.day:
        store = game.role_state[STOPPED] = {"night": game.day}
    done = store.setdefault(target, [])
    left = [a for a in attacks if a["attack"] in CATCHABLE and [a["by"], a["cause"].strip().lower()] not in done]
    if not left:
        return None
    stopped = game.rng.choice(left)
    done.append([stopped["by"], stopped["cause"].strip().lower()])
    return stopped


CODE_ATTACKS = "code_attacks"  # game.role_state: night -> attackers of attacks code made that night (record_attack)


def record_attack(game: Game, attacker: str) -> None:
    """An attack that code carries out at night (a Cursed player's curse, traits.py), for results that count attacks
    (the Bloodhound's), alongside the ones the moderator lists."""
    game.role_state.setdefault(CODE_ATTACKS, {}).setdefault(game.day, []).append(attacker)


LEFT_AT = "left_at"  # game.role_state: player -> [day, phase] they left the game


def leave_game(game: Game, me: Player, won: bool = True) -> None:
    """me wins (or loses) and leaves the game: not a death, and the caller announces it. Leaving at night still
    counts as alive when the night began (acted_tonight), so tonight's visit results keep them (rules R10)."""
    me.alive = False
    me.status[Status.LEFT] = True
    game.role_state.setdefault(LEFT_AT, {})[me.name] = [game.day, game.phase]
    game.log.write("left", player=me.name, day=game.day, phase=game.phase)
    when = f"{'Night' if game.phase == 'night' else 'Day'} {game.day}"
    game.death_record.append(f"{when}: {me.name} ({me.role}) {'won' if won else 'lost'} and left the game")
    for q in game.alive():  # leaving counts as a death for anyone targeting this one (an Executioner, ...)
        logic(q.role).on_other_death(game, q, me, None)


def true_tokens(p: Player) -> dict[str, int]:
    """The tokens p's true role has left (rules R19, token counts). A Roleplayer's tokens are its fake role's, so it
    has none."""
    from roles import ROLES
    return {k: n for k, n in p.tokens.items() if k in ROLES[p.role].tokens and n > 0}


def dead_before_tonight(game: Game) -> list[str]:
    """Players who died before the night began (not those who left, nor those killed tonight): what a "dead" target
    (RecordedAction.target) may be."""
    return [p.name for p in game.players
            if not p.alive and not p.status.get(Status.LEFT) and not acted_tonight(game, p)]


def swaps_tonight(game: Game) -> list[tuple[str, str, str]]:
    """Tonight's swaps (rules R23) as (swapper, x, y), in the order they were made."""
    return [(by, x, y) for by, x, y in game.role_state.get("swaps", {}).get(game.day, [])]


def swap_partner(game: Game, name: str) -> str | None:
    """Who `name` was swapped with tonight (rules R23), or None. An action that landed on a swapped player was aimed
    at their partner, so its result names the partner; and an action may land on its own user that way, even one
    whose role can't target themselves."""
    for _, x, y in swaps_tonight(game):
        if name in (x, y):
            return y if name == x else x
    return None


def as_chosen(game: Game, target: str, names: list[str]) -> list[str]:
    """Names in a result about `target`, as its user chose them: when a swap moved the action onto `target`, the
    swapped pair trade names (each where the other would be) and the list goes back to seat order, so the result
    doesn't show the swap (rules R23). Roles and alignments drawn from the group stay the real players'."""
    partner = swap_partner(game, target)
    if partner is None:
        return names
    shown = {target: partner, partner: target}
    return [p.name for p in game.players if p.name in {shown.get(n, n) for n in names}]


def chosen_name(game: Game, target: str) -> str:
    """The player a result about `target` names: whoever its user chose, i.e. `target`'s swap partner when a swap
    moved the action (rules R23). A private result that names its target uses this, never the target's own name."""
    return swap_partner(game, target) or target


def token_user_error(game: Game, by_name: str, role: str, kind: str | None = None) -> str | None:
    """check_op for a role op: None if `by` has `role`, was alive when the night began (acted_tonight) and,
    for an op that spends a `kind` token, has one."""
    by = game.player(by_name)
    if by.role != role or not acted_tonight(game, by):
        return f"{by.name} is not a {role} who was alive when the night began"
    if kind and by.tokens.get(kind, 0) < 1:
        return f"{by.name} has no {kind} token left"
    return None


def spend_token(game: Game, by_name: str, kind: str) -> int:
    """apply_op's half of token_user_error: spends one `kind` token and returns how many are left."""
    by = game.player(by_name)
    by.tokens[kind] -= 1
    return by.tokens[kind]


def tokens_left_text(p: Player, kind: str) -> str:
    """e.g. "2 survey tokens left"."""
    n = p.tokens.get(kind, 0)
    return f"{n} {kind} token{'' if n == 1 else 's'} left"


def join_names(names: list[str]) -> str:
    """e.g. "Alice, Bob and Carol"."""
    return ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else "".join(names)


def neighbor_group(game: Game, user: str, target: str) -> list[str]:
    """The target and their nearest neighbor on each side (rules R11), among players alive at the start of the
    night other than `user`, without repeats: [left, target, right], shorter in small games (Surveyor, Diviner)."""
    circle = [p.name for p in game.players if acted_tonight(game, p) and p.name != user]
    i = circle.index(target)
    return list(dict.fromkeys([circle[i - 1], target, circle[(i + 1) % len(circle)]]))


def visit_groups(game: Game) -> list[list[str]] | None:
    """Tonight's visit groups (Cartographer): the connected parts of the undirected graph whose nodes are the
    players alive at the start of the night and whose edges are the moderator's record_visits pairs (self-visits
    link no one), each in seat order, largest first, then by first seat. None if no visits were recorded."""
    visits = game.night_visits.get(game.day)
    if visits is None:
        return None
    nodes = [p.name for p in game.players if acted_tonight(game, p)]
    root = {n: n for n in nodes}

    def find(n: str) -> str:
        while root[n] != n:
            n = root[n]
        return n
    for a, b in visits:
        if a in root and b in root:
            root[find(a)] = find(b)
    groups: dict[str, list[str]] = {}
    for n in nodes:
        groups.setdefault(find(n), []).append(n)
    return sorted(groups.values(), key=lambda g: (-len(g), nodes.index(g[0])))


def recorded_action_parts(role: str, cls: type[RoleLogic]) -> None:
    """Fills in a RecordedAction role's op and (unless it sets its own) night note."""
    a = cls.action
    if a is None:
        return
    cls.ops = {a.op: ({"player", "by"} if a.target else {"by"}, set(),
                      f"{{op:'{a.op}', {'player, ' if a.target else ''}by}}: the {role} `by` {a.does}"
                      + (" (spends a token)" if a.token else ""))}
    if not cls.night_note:
        article = "An" if role[0] in "AEIOU" else "A"
        cls.night_note = (f"{article} {role} who {'spent a token' if a.token else 'acted'} (and wasn't role-blocked): "
                          f"use the {a.op} op{', which spends the token' if a.token else ''}; {a.then}."
                          + (f" Don't tell() the {role} anything about it." if cls.code_tells_user else "")
                          + (" It is a visit to the target only." if a.visit else "")
                          + (f" {a.note}" if a.note else ""))


def register(role: str):
    def wrap(cls: type[RoleLogic]) -> type[RoleLogic]:
        cls.role = role
        recorded_action_parts(role, cls)
        LOGIC[role] = cls()
        return cls
    return wrap


def logic(role: str) -> RoleLogic:
    return LOGIC.get(role, DEFAULT)


def code_hooks(role_logic: RoleLogic) -> list[str]:
    """Which hooks a role's file implements (for --list-roles), plus its ops and win-check flag."""
    hooks = [name for name, attr in vars(RoleLogic).items()
             if callable(attr) and not name.startswith("_") and name != "apply_op"
             and getattr(type(role_logic), name) is not attr]
    hooks += [f"op {op}" for op in role_logic.ops]
    if not role_logic.blocks_win:
        hooks.append("never blocks a win")
    return hooks
