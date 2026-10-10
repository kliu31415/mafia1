"""Game state: players, visibility-aware events, deaths and win checks."""

import json
import random
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from gamelog import LOG_VERSION, GameLog
from llm import Model, ModelSpec
from events import ANNOUNCEMENT, DEATH, RESULT, SYSTEM
from roles import LOGIC, Alignment, ROLES, RoleInfo, Status, logic


PLAYER_NAMES = ["Alice", "Bob", "Carol", "Dave", "Erin", "Frank", "Grace", "Heidi", "Ivan", "Judy",
                "Mallory", "Niaj", "Olivia", "Peggy", "Rupert", "Sybil"]



def phase_label(day: int, phase: str) -> str:
    """"Day 2" or "Night 2" (the night after Day 2), the way the rules and announcements name phases; players
    argued over labels when history lines said "Day 2 night"."""
    return f"{'Night' if phase == 'night' else 'Day'} {day}"

@dataclass
class Player:
    name: str
    seat: int
    model: Model
    role: str
    effort: str | None = None  # reasoning effort; None means the client's default
    alive: bool = True
    tokens: dict[str, int] = field(default_factory=dict)
    status: dict[str, Any] = field(default_factory=dict)  # keys code reads are in Status; the moderator adds others
    last_will: str = ""
    notepad: str = ""  # private notes the player keeps across turns
    tips: str = ""  # a tips file from past games, shown in the system prompt (tips.py; --tips)
    speaking_budget: float = 0.0
    start_role: str = ""  # the role at setup (an Executioner can become a Jester)
    death: dict | None = None  # day, phase and cause, once dead

    def __post_init__(self) -> None:
        self.start_role = self.start_role or self.role

    @property
    def info(self) -> RoleInfo:
        return ROLES[self.role]

    @property
    def faction(self) -> str:
        match self.info.alignment:
            case Alignment.GOOD:
                return "Village"
            case Alignment.EVIL:
                return "Yakuza"
            case _:
                return f"Neutral:{self.name}"


@dataclass
class Event:
    """Something that happened, and who may see it. visible_to=None means public."""

    day: int
    phase: str
    text: str
    visible_to: frozenset[str] | None = None
    cat: str = SYSTEM
    fields: dict[str, Any] = field(default_factory=dict)
    notice: bool = False  # emitted with kind="notice": it duplicates another event for those who can't see that one

    def visible(self, name: str) -> bool:
        return self.visible_to is None or name in self.visible_to


def death_cause(cause: str) -> str:
    """The public cause of death as worded in a reveal: a bare killer's role or weapon ("Katana", "Vigilante",
    "Jester's revenge") becomes "killed by Katana"; a cause that is already a phrase ("executed by hanging",
    "killed by the Vigilante") is kept."""
    cause = cause.strip() or "killed"
    if re.match(r"(killed|executed|shot|burned|burnt|poisoned|attacked|died|hanged|murdered|struck)\b", cause, re.I):
        return cause
    return f"killed by {cause}"


@dataclass
class Game:
    players: list[Player]  # in circle (seat) order
    rng: random.Random
    log: GameLog
    day: int = 1
    phase: str = "day"
    events: list[Event] = field(default_factory=list)
    katana_holder: str | None = None
    phases_without_death: int = 0  # day and night phases since the last death
    winners: list[str] | None = None
    pending_announcements: list[str] = field(default_factory=list)
    pending_deaths: list[tuple[str, str]] = field(default_factory=list)  # (name, cause), revealed at dawn
    personal_winners: list[str] = field(default_factory=list)  # Jester / Executioner
    sole_winner: str | None = None  # a player whose win ends the game at once, everyone else losing (Vulture)
    pending_revenge: list[tuple[str, list[str]]] = field(default_factory=list)  # (source, Guilty voters)
    role_state: dict[str, Any] = field(default_factory=dict)  # per-game state of role hooks (roles/*.py)
    prosecutions: list[str] = field(default_factory=list)  # players put on trial when the next day starts
    rigged_day: int | None = None  # day whose trials a Clerk has rigged
    puppets_next: dict[str, str] = field(default_factory=dict)  # puppet -> Puppeteer, for the next day
    puppets: dict[str, str] = field(default_factory=dict)  # puppet -> Puppeteer, today
    death_record: list[str] = field(default_factory=list)  # public summary of each death, for the ledger
    vote_record: list[str] = field(default_factory=list)  # public summary of each nomination and trial
    pm_record: dict[int, dict[str, int]] = field(default_factory=dict)  # day -> {"A -> B": private messages}
    night_actions: dict[int, dict[str, dict]] = field(default_factory=dict)  # night -> submitted actions
    # night -> the visits made, as [visitor, target] pairs (duplicates kept), from the moderator's record_visits
    night_visits: dict[int, list[list[str]]] = field(default_factory=dict)
    claim_record: dict[str, list[tuple[int, str]]] = field(default_factory=dict)  # player -> (day, claim)
    # What a death reveals (rules R12): "role", "alignment" (Good, Evil or Neutral) or "none"; a game setting, --flips
    flips: str = "role"

    def __getstate__(self) -> dict[str, Any]:
        # Pickled for checkpoints (checkpoint.py) without the log's open files; resuming reattaches a log.
        return {k: v for k, v in self.__dict__.items() if k != "log"}

    def chat_controller(self, name: str) -> str:
        """Who reads and writes `name`'s chat today (the Puppeteer, if `name` is puppeted)."""
        return self.puppets.get(name, name)

    def pm_listeners(self, speaker: str, to: str) -> list[str]:
        """Living players who also read this private message's contents (Wiretap, Eavesdropper). A
        puppeted listener can't see private messages today, like any puppet."""
        return [p.name for p in self.alive()
                if p.name not in self.puppets and logic(p.role).hears_pm(self, p, speaker, to)]

    # --- lookups --------------------------------------------------------------------------

    def player(self, name: str) -> Player:
        for p in self.players:
            if p.name == name:
                return p
        raise KeyError(name)

    def alive(self) -> list[Player]:
        return [p for p in self.players if p.alive]

    def alive_names(self) -> list[str]:
        return [p.name for p in self.alive()]

    def death_count(self) -> int:
        return sum(not p.alive and not p.status.get(Status.LEFT) for p in self.players)

    def yakuza(self) -> list[Player]:
        return [p for p in self.alive() if p.info.alignment is Alignment.EVIL]

    def clockwise_from(self, name: str) -> list[Player]:
        """Alive players in circle order (rules R11), starting at `name` (who must be alive)."""
        alive = self.alive()
        i = next(i for i, p in enumerate(alive) if p.name == name)
        return alive[i:] + alive[:i]

    # --- events ---------------------------------------------------------------------------

    def emit(self, text: str, visible_to: list[str] | set[str] | None = None, kind: str = "event",
             cat: str = SYSTEM, **fields: Any) -> None:
        """cat is the event's category (CHAT etc. above), with that category's fields.
        kind="notice" marks events that the readable logs skip (they duplicate another event)."""
        vis = frozenset(visible_to) if visible_to is not None else None
        self.events.append(Event(self.day, self.phase, text, vis, cat, fields, kind == "notice"))
        self.log.write(kind, day=self.day, phase=self.phase, text=text,
                       visible_to=sorted(vis) if vis is not None else "all", cat=cat, **fields)

    def tell(self, names: list[str], text: str) -> None:
        """A private moderator result (the moderator's tell(), or one that code works out for a role)."""
        self.emit(f"Moderator (private): {text}", names, cat=RESULT, message=text)

    def history_for(self, name: str) -> str:
        earlier, current = self.history_split(name)
        return "\n".join(earlier + current) or "(nothing yet)"

    def history_split(self, name: str) -> tuple[list[str], list[str]]:
        """What `name` has seen, as lines from earlier phases and lines from the current one. Earlier
        phases don't change, so prompts can cache them (llm.cache_block)."""
        lines = [(e.day, e.phase, f"[{phase_label(e.day, e.phase)}] {e.text}" + (
            " [written by your Puppeteer, not you]" if e.fields.get("puppeteer") and e.fields.get("speaker") == name
            else "")) for e in self.events if e.visible(name)]
        start = len(lines)
        while start and lines[start - 1][:2] == (self.day, self.phase):
            start -= 1
        return [x[2] for x in lines[:start]], [x[2] for x in lines[start:]]

    # --- state changes ----------------------------------------------------------------------

    def kill(self, name: str, cause: str, public: bool = True, guilty_voters: list[str] | None = None,
             by: str | list[str] | None = None, katana: bool = False) -> None:
        """Rules R12. guilty_voters is set only for an execution by hanging. `by` is the killer, if a
        player, and katana marks the Katana attack; they're logged for analysis (deaths by role),
        while `cause` is the public wording."""
        p = self.player(name)
        if not p.alive:
            return
        p.alive = False
        self.phases_without_death = 0
        # Several attacks may each have been fatal (R12): killers lists them all, killer is the first.
        killers = [by] if isinstance(by, str) else list(by or [])
        killer_roles = [self.player(k).role for k in killers]
        killer, killer_role = (killers[0], killer_roles[0]) if killers else (None, None)
        p.death = {"day": self.day, "phase": self.phase, "cause": cause, "killer": killer, "killer_role": killer_role,
                   "killers": killers, "killer_roles": killer_roles, "katana": katana}
        self.log.write("death", player=name, role=p.role, cause=cause, day=self.day, phase=self.phase,
                       killer=killer, killer_role=killer_role, killers=killers, killer_roles=killer_roles,
                       katana=katana)
        if not public:
            pass  # caller (e.g. moderator after a Mortician clean) announces it differently
        elif self.phase == "night":
            # Revealed at dawn, so a will forged later the same night still applies.
            self.pending_deaths.append((name, cause))
        else:
            self.reveal_death(name, cause)
        # After the reveal, so what a death sets off (an Executioner's win, ...) is announced after it.
        logic(p.role).on_death(self, p, guilty_voters)
        for q in self.alive():
            logic(q.role).on_other_death(self, q, p, guilty_voters)
        if self.phase != "night":  # a holder who dies at night passes it on after the night's results
            self.pass_katana()

    def pass_katana(self) -> None:
        """If the Katana holder is dead, pass the Katana to a random living Yakuza (rules R8)."""
        if self.katana_holder and not self.player(self.katana_holder).alive:
            remaining = self.yakuza()
            self.katana_holder = self.rng.choice(remaining).name if remaining else None
            if self.katana_holder:
                self.emit(f"The Katana passed to {self.katana_holder}.", [y.name for y in remaining])

    def run_night_end_hooks(self) -> None:
        """Role effects at the end of the night (e.g. the Cardinal's curse)."""
        for role_logic in LOGIC.values():
            role_logic.at_night_end(self)

    def run_dawn_hooks(self) -> None:
        """Role effects at the start of the day (e.g. Ballot Stuffer votes taking effect)."""
        for role_logic in LOGIC.values():
            role_logic.at_dawn(self)

    def announce_dawn(self) -> None:
        """Publicly reveal the night's deaths and queued announcements."""
        for name, cause in self.pending_deaths:
            self.reveal_death(name, cause)
        self.pending_deaths.clear()
        for text in self.pending_announcements:
            self.emit(f"Moderator: {text}", cat=ANNOUNCEMENT, message=text)
        self.pending_announcements.clear()

    def reveal_death(self, name: str, cause: str) -> None:
        self.emit(self.death_reveal(name, cause), cat=DEATH)
        p = self.player(name)
        what = (f"role cleaned by a Mortician, {cause}" if p.status.get(Status.CLEANED)
                else f"{self.revealed_identity(p)}, {cause}")
        when = p.death or {"day": self.day, "phase": self.phase}  # when they died, not when it's revealed
        self.death_record.append(f"{'Night' if when['phase'] == 'night' else 'Day'} {when['day']}: {name} ({what})")

    def public_ledger(self) -> str:
        """A compact summary of public facts, shown to every player each turn."""
        alive = ", ".join(self.alive_names())
        deaths = "\n".join(f"- {d}" for d in self.death_record) or "- none yet"
        votes = "\n".join(f"- {v}" for v in self.vote_record) or "- none yet"
        pms = "\n".join(f"- Day {day}: " + ", ".join(f"{pair} ({n})" for pair, n in counts.items())
                        for day, counts in self.pm_record.items()) or "- none yet"
        claims = "\n".join(
            f"- {name}{'' if self.player(name).alive else ' (dead)'}: Day {history[-1][0]}: {history[-1][1]}"
            + (f" (earlier: {'; '.join(f'Day {d}: {c}' for d, c in history[:-1])})" if len(history) > 1 else "")
            for name, history in self.claim_record.items()) or "- none yet"
        return (f"Alive, in seat order: {alive}\nDeaths and departures:\n{deaths}\n"
                f"Nominations and trials:\n{votes}\n"
                f"Claims (what players say about their own role and results; unverified, they may lie):\n{claims}\n"
                f"Private messages sent, per day (sender -> recipient (count)):\n{pms}")

    def revealed_identity(self, p: Player) -> str:
        """What a death shows of the player (rules R12): their role, with --flips alignment only their true
        alignment (Good, Evil or Neutral; never a frame or disguise), with --flips none nothing."""
        return {"alignment": p.info.alignment.value, "none": "unrevealed"}.get(self.flips, p.role)

    def death_reveal(self, name: str, cause: str) -> str:
        p = self.player(name)
        cause = death_cause(cause)
        if p.status.get(Status.CLEANED):
            hidden = {"alignment": "alignment and last will were", "none": "last will was"}.get(
                self.flips, "role and last will were")
            return f"{name} died ({cause}). Their {hidden} cleaned by a Mortician."  # rules R12
        reveal = {"alignment": f"{name} died ({cause}). Their alignment was {self.revealed_identity(p)}.",
                  "none": f"{name} died ({cause}). Their role isn't revealed."}.get(
                      self.flips, f"{name} died ({cause}). Their role was {p.role}.")
        if p.last_will:
            reveal += f" Their last will: \"{p.last_will}\""
        return reveal

    def resolve_revenge(self, alive_at_start: set[str] | None = None) -> None:
        """Jester / Executioner revenge: a Divine Attack on a random Guilty voter, the night after, drawn from
        those alive when the night began (Kevin, Oct 10: one killed by another attack that night can still be
        drawn, and then nobody else dies)."""
        for source, voters in self.pending_revenge:
            targets = [v for v in voters if (v in alive_at_start if alive_at_start is not None
                                             else self.player(v).alive)]
            if targets:
                victim = self.rng.choice(targets)
                self.log.write("revenge", source=source, victim=victim)
                self.kill(victim, f"{self.player(source).role}'s revenge", by=source)
        self.pending_revenge.clear()

    def check_winner(self) -> list[str] | None:
        """Rules R1. Called at the start of each day. Returns the winning player names, or None.
        Jester / Executioner wins are personal: they don't end the game, but are added at the end."""
        if self.sole_winner:  # Jester / Executioner wins already earned still count (R1)
            return [self.sole_winner] + self.personal_winners
        alive = self.alive()
        blocking = {p.faction for p in alive if logic(p.role).blocks_win}
        if len(blocking) <= 1:
            faction = next(iter(blocking), None)
            return [p.name for p in self.players if faction and p.faction == faction] + self.personal_winners
        return None

    def winners_line(self) -> str:
        """"Winners: ..." for game text. Winners who died or left (an Executioner, R1) are marked, so they don't
        read as survivors; leaving isn't dying."""
        def mark(n: str) -> str:
            p = self.player(n)
            return n if p.alive else f"{n} (left)" if p.status.get(Status.LEFT) else f"{n} (dead)"
        line = f"Winners: {', '.join(map(mark, self.winners or [])) or 'nobody'}."
        return line + " Dead players still win with their side." if "(dead)" in line else line

    def state_summary(self) -> str:
        """full_state() as readable lines, for the moderator (it asked for one after
        game_20261009_084630_739772): seat order, Katana holder, tokens, statuses and next-Day effects."""
        def who(p: Player) -> str:
            extras = [f"tokens {', '.join(f'{k} {v}' for k, v in p.tokens.items())}" if p.tokens else "",
                      f"status {json.dumps(p.status)}" if p.status else "",
                      "holds the Katana" if p.name == self.katana_holder else ""]
            return f"{p.name} ({p.role}, {p.faction})" + "".join(f"; {x}" for x in extras if x)
        lines = [f"Day {self.day}, {self.phase}. Katana holder: {self.katana_holder or 'none'}.",
                 "Living players in seat order:"]
        lines += [f"- seat {p.seat + 1}: {who(p)}" for p in self.alive()]
        dead = [p for p in self.players if not p.alive]
        if dead:
            lines.append("Dead: " + "; ".join(
                f"{who(p)}, died day {p.death['day']} {p.death['phase']}" if p.death else who(p) for p in dead))
        effects = ([f"Clerk's rig on day {self.rigged_day}"]
                   if self.rigged_day and self.rigged_day >= self.day else []) \
            + [f"{n} is prosecuted next day" for n in self.prosecutions] \
            + [f"{a} puppets {b} next day" for b, a in self.puppets_next.items()] \
            + [f"{a} puppets {b} today" for b, a in self.puppets.items()]
        lines.append("Pending day effects: " + ("; ".join(effects) or "none"))
        return "\n".join(lines)

    def full_state(self) -> dict:
        """Everything, for the moderator."""
        return {
            "day": self.day,
            "phase": self.phase,
            "katana_holder": self.katana_holder,
            "players": [{
                "name": p.name, "seat": p.seat, "alive": p.alive, "role": p.role, "faction": p.faction,
                "base_defense": p.info.defense, "sheriff_appears_evil": p.info.sheriff_evil,
                "tokens": p.tokens, "status": p.status, "last_will": p.last_will,
            } for p in self.players],
        }


def setup_game(roles: list[str], models: Sequence[Model | ModelSpec], rng: random.Random, log: GameLog,
               meta: dict | None = None) -> Game:
    """meta: extra fields for the setup record, e.g. the code version and settings (see mafia.py)."""
    if len(roles) > len(PLAYER_NAMES):
        raise ValueError(f"{len(roles)} roles but only {len(PLAYER_NAMES)} player names")
    if len(models) > len(roles):
        raise ValueError(f"{len(roles)} roles but {len(models)} models")
    if repeated := sorted({r for r in roles if ROLES[r].unique and roles.count(r) > 1}):
        raise ValueError(f"at most one player may have each of these roles: {', '.join(repeated)}")
    models = [models[i % len(models)] for i in range(len(roles))]  # cycle models over the seats
    names = PLAYER_NAMES[:len(roles)]
    shuffled = roles[:]
    rng.shuffle(shuffled)
    seat_models = [m if isinstance(m, ModelSpec) else ModelSpec(m) for m in models]
    rng.shuffle(seat_models)
    players = [Player(n, i, m.model, r, effort=m.effort, tokens=dict(ROLES[r].tokens))
               for i, (n, m, r) in enumerate(zip(names, seat_models, shuffled))]
    game = Game(players, rng, log)
    yakuza = game.yakuza()
    if yakuza:
        game.katana_holder = rng.choice(yakuza).name
    for p in players:
        logic(p.role).setup(game, p)
    log.write("setup", players=[{"name": p.name, "seat": p.seat, "model": p.model.value, "effort": p.effort,
                                 "role": p.role,
                                 "status": p.status} for p in players], katana=game.katana_holder,
              log_version=LOG_VERSION, **(meta or {}))
    return game


def majority(yes: int, total: int) -> bool:
    return yes * 2 > total  # strictly more than half (rules R4, R8)
