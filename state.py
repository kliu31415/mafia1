"""Game state: players, visibility-aware events, deaths and win checks."""

import random
from dataclasses import dataclass, field
from typing import Any

from gamelog import GameLog
from llm import Model
from roles import Alignment, NON_BLOCKING_ROLES, ROLES, RoleInfo


PLAYER_NAMES = ["Alice", "Bob", "Carol", "Dave", "Erin", "Frank", "Grace", "Heidi", "Ivan", "Judy",
                "Mallory", "Niaj", "Olivia", "Peggy", "Rupert", "Sybil"]


@dataclass
class Player:
    name: str
    seat: int
    model: Model
    role: str
    alive: bool = True
    tokens: dict[str, int] = field(default_factory=dict)
    status: dict[str, Any] = field(default_factory=dict)  # keys code reads are in Status; the moderator adds others
    last_will: str = ""
    notepad: str = ""  # private notes the player keeps across turns
    speaking_budget: float = 0.0

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


# Event categories. Every emit() names one, and the log viewer colors and labels events by it
# (never by parsing their text), so event wording can change freely.
CHAT = "chat"  # public chat; fields: speaker, message
PM = "pm"  # private message; fields: speaker, to, message
YAKUZA_CHAT = "yak"  # fields: speaker, message
NOMINATION = "nom"
VOTE = "vote"  # vote results, trials, verdicts
DEATH = "death"  # deaths, executions, players leaving the game
RESULT = "result"  # moderator's private result; fields: message
ANNOUNCEMENT = "announcement"  # moderator's public announcement; fields: message
PHASE = "phase"  # "Day N begins." / "Night N begins."
SYSTEM = "system"  # anything else


class Status:
    """Player.status keys that code reads. The moderator may also set its own keys (e.g. doused)."""

    LEFT = "left"  # left the game (a winning Executioner); not a death
    CLEANED = "cleaned"  # Mortician: the death reveal hides role and will
    TARGET = "target"  # Executioner's target
    FAKE_ROLE = "fake_role"  # the role a Roleplayer believes they have


@dataclass
class Event:
    """Something that happened, and who may see it. visible_to=None means public."""

    day: int
    phase: str
    text: str
    visible_to: frozenset[str] | None = None
    cat: str = SYSTEM
    fields: dict[str, Any] = field(default_factory=dict)

    def visible(self, name: str) -> bool:
        return self.visible_to is None or name in self.visible_to


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
    pending_revenge: list[tuple[str, list[str]]] = field(default_factory=list)  # (source, Guilty voters)
    pending_cardinal: int = 0  # Cardinal deaths whose curse strikes at the next dawn
    prosecutions: list[str] = field(default_factory=list)  # players put on trial when the next day starts
    rigged_day: int | None = None  # day whose trials a Clerk has rigged
    puppets_next: dict[str, str] = field(default_factory=dict)  # puppet -> Puppeteer, for the next day
    puppets: dict[str, str] = field(default_factory=dict)  # puppet -> Puppeteer, today
    death_record: list[str] = field(default_factory=list)  # public summary of each death, for the ledger
    vote_record: list[str] = field(default_factory=list)  # public summary of each nomination and trial

    def chat_controller(self, name: str) -> str:
        """Who reads and writes `name`'s chat today (the Puppeteer, if `name` is puppeted)."""
        return self.puppets.get(name, name)

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
        """Alive players in circle order, starting at `name` (who must be alive)."""
        alive = self.alive()
        i = next(i for i, p in enumerate(alive) if p.name == name)
        return alive[i:] + alive[:i]

    # --- events ---------------------------------------------------------------------------

    def emit(self, text: str, visible_to: list[str] | set[str] | None = None, kind: str = "event",
             cat: str = SYSTEM, **fields: Any) -> None:
        """cat is the event's category (CHAT etc. above), with that category's fields.
        kind="notice" marks events that the readable logs skip (they duplicate another event)."""
        vis = frozenset(visible_to) if visible_to is not None else None
        self.events.append(Event(self.day, self.phase, text, vis, cat, fields))
        self.log.write(kind, day=self.day, phase=self.phase, text=text,
                       visible_to=sorted(vis) if vis is not None else "all", cat=cat, **fields)

    def history_for(self, name: str) -> str:
        lines = []
        for e in self.events:
            if e.visible(name):
                lines.append(f"[Day {e.day} {e.phase}] {e.text}")
        return "\n".join(lines) if lines else "(nothing yet)"

    # --- state changes ----------------------------------------------------------------------

    def kill(self, name: str, cause: str, public: bool = True,
             guilty_voters: list[str] | None = None) -> None:
        """guilty_voters is set only for an execution by hanging."""
        p = self.player(name)
        if not p.alive:
            return
        p.alive = False
        hanged = guilty_voters is not None
        if hanged and p.role == "Jester":
            self.personal_winners.append(name)
            self.pending_revenge.append((name, guilty_voters))
        for exe in self.alive():
            if exe.role == "Executioner" and exe.status.get(Status.TARGET) == name:
                if hanged:
                    self.personal_winners.append(exe.name)
                    self.pending_revenge.append((exe.name, guilty_voters))
                    exe.alive = False  # leaves the game; not a death
                    exe.status[Status.LEFT] = True
                    self.emit(f"{exe.name} was the Executioner, whose target was {name}. "
                              f"They win and leave the game.", cat=DEATH)
                    self.death_record.append(f"Day {self.day}: {exe.name} (Executioner) won and left the game")
                else:
                    # Our reading of "if you die of other means": the target dying otherwise.
                    exe.role = "Jester"
                    self.emit("Your target died other than by hanging. You are now a Jester.", [exe.name])
        self.phases_without_death = 0
        self.log.write("death", player=name, role=p.role, cause=cause, day=self.day, phase=self.phase)
        if not public:
            pass  # caller (e.g. moderator after a Mortician clean) announces it differently
        elif self.phase == "night":
            # Revealed at dawn, so a will forged later the same night still applies.
            self.pending_deaths.append((name, cause))
        else:
            self.reveal_death(name, cause)
        if self.phase != "night":  # a holder who dies at night passes it on after the night's results
            self.pass_katana()
        if p.role == "Cardinal":
            self.pending_cardinal += 1

    def pass_katana(self) -> None:
        """If the Katana holder is dead, pass the Katana to a random living Yakuza."""
        if self.katana_holder and not self.player(self.katana_holder).alive:
            remaining = self.yakuza()
            self.katana_holder = self.rng.choice(remaining).name if remaining else None
            if self.katana_holder:
                self.emit(f"The Katana passed to {self.katana_holder}.", [y.name for y in remaining])

    def resolve_cardinal(self) -> None:
        """Cardinal: a Divine Attack on a random Good player at the beginning of the day after they die."""
        for _ in range(self.pending_cardinal):
            good = [q.name for q in self.alive() if q.info.alignment is Alignment.GOOD]
            if good:
                victim = self.rng.choice(good)
                self.log.write("cardinal", victim=victim)
                self.kill(victim, "Cardinal's curse")
        self.pending_cardinal = 0

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
        what = "role cleaned by a Mortician" if p.status.get(Status.CLEANED) else f"{p.role}, {cause}"
        self.death_record.append(f"Day {self.day} {self.phase}: {name} ({what})")

    def public_ledger(self) -> str:
        """A compact summary of public facts, shown to every player each turn."""
        alive = ", ".join(self.alive_names())
        deaths = "\n".join(f"- {d}" for d in self.death_record) or "- none yet"
        votes = "\n".join(f"- {v}" for v in self.vote_record) or "- none yet"
        return (f"Alive, in seat order: {alive}\nDeaths and departures:\n{deaths}\n"
                f"Nominations and trials:\n{votes}")

    def death_reveal(self, name: str, cause: str) -> str:
        p = self.player(name)
        if p.status.get(Status.CLEANED):
            return f"{name} died. Their role and last will were cleaned by a Mortician."
        reveal = f"{name} died ({cause}). Their role was {p.role}."
        if p.last_will:
            reveal += f" Last will: {p.last_will!r}"
        return reveal

    def resolve_revenge(self) -> None:
        """Jester / Executioner revenge: a Divine Attack on a random Guilty voter, the night after."""
        for source, voters in self.pending_revenge:
            targets = [v for v in voters if self.player(v).alive]
            if targets:
                victim = self.rng.choice(targets)
                self.log.write("revenge", source=source, victim=victim)
                self.kill(victim, f"{self.player(source).role}'s revenge")
        self.pending_revenge.clear()

    def check_winner(self) -> list[str] | None:
        """Called at the start of each day. Returns the winning player names, or None.
        Jester / Executioner wins are personal: they don't end the game, but are added at the end."""
        alive = self.alive()
        blocking = {p.faction for p in alive if p.role not in NON_BLOCKING_ROLES}
        if len(blocking) <= 1:
            faction = next(iter(blocking), None)
            return [p.name for p in self.players if faction and p.faction == faction] + self.personal_winners
        return None

    def public_state(self) -> dict:
        return {
            "day": self.day,
            "phase": self.phase,
            "players": [{"name": p.name, "seat": p.seat, "alive": p.alive,
                         "revealed_role": None if p.alive else p.role} for p in self.players],
        }

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


def setup_game(roles: list[str], models: list[Model], rng: random.Random, log: GameLog) -> Game:
    if len(models) > len(roles):
        raise ValueError(f"{len(roles)} roles but {len(models)} models")
    models = [models[i % len(models)] for i in range(len(roles))]  # cycle models over the seats
    names = PLAYER_NAMES[:len(roles)]
    shuffled = roles[:]
    rng.shuffle(shuffled)
    seat_models = models[:]
    rng.shuffle(seat_models)
    players = [Player(n, i, m, r, tokens=dict(ROLES[r].tokens))
               for i, (n, m, r) in enumerate(zip(names, seat_models, shuffled))]
    game = Game(players, rng, log)
    yakuza = game.yakuza()
    if yakuza:
        game.katana_holder = rng.choice(yakuza).name
    for p in players:
        if p.role == "Executioner":
            p.status[Status.TARGET] = rng.choice([q.name for q in players if q is not p])
        if p.role == "Roleplayer":
            p.status[Status.FAKE_ROLE] = rng.choice(
                [r for r, i in ROLES.items() if i.category == "Investigative"])
    log.write("setup", players=[{"name": p.name, "seat": p.seat, "model": p.model.value, "role": p.role,
                                 "status": p.status} for p in players], katana=game.katana_holder)
    return game


def majority(yes: int, total: int) -> bool:
    return yes * 2 > total  # strictly more than half
