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
    status: dict[str, Any] = field(default_factory=dict)  # free-form flags, e.g. doused, fake_role
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


@dataclass
class Event:
    """Something that happened, and who may see it. visible_to=None means public."""

    day: int
    phase: str
    text: str
    visible_to: frozenset[str] | None = None

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
        return sum(not p.alive and not p.status.get("left") for p in self.players)

    def yakuza(self) -> list[Player]:
        return [p for p in self.alive() if p.info.alignment is Alignment.EVIL]

    def clockwise_from(self, name: str) -> list[Player]:
        """Alive players in circle order, starting at `name` (who must be alive)."""
        alive = self.alive()
        i = next(i for i, p in enumerate(alive) if p.name == name)
        return alive[i:] + alive[:i]

    # --- events ---------------------------------------------------------------------------

    def emit(self, text: str, visible_to: list[str] | set[str] | None = None, kind: str = "event") -> None:
        """kind="notice" marks events that the readable logs skip (they duplicate another event)."""
        vis = frozenset(visible_to) if visible_to is not None else None
        self.events.append(Event(self.day, self.phase, text, vis))
        self.log.write(kind, day=self.day, phase=self.phase, text=text,
                       visible_to=sorted(vis) if vis is not None else "all")

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
            if exe.role == "Executioner" and exe.status.get("target") == name:
                if hanged:
                    self.personal_winners.append(exe.name)
                    self.pending_revenge.append((exe.name, guilty_voters))
                    exe.alive = False  # leaves the game; not a death
                    exe.status["left"] = True
                    self.emit(f"{exe.name} was the Executioner, whose target was {name}. "
                              f"They win and leave the game.")
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
            self.emit(self.death_reveal(name, cause))
        if self.katana_holder == name:
            remaining = self.yakuza()
            self.katana_holder = self.rng.choice(remaining).name if remaining else None
            if self.katana_holder:
                self.emit(f"The Katana passed to {self.katana_holder}.", [y.name for y in remaining])
        # TODO: Cardinal.

    def announce_dawn(self) -> None:
        """Publicly reveal the night's deaths and queued announcements."""
        for name, cause in self.pending_deaths:
            self.emit(self.death_reveal(name, cause))
        self.pending_deaths.clear()
        for text in self.pending_announcements:
            self.emit(text)
        self.pending_announcements.clear()

    def death_reveal(self, name: str, cause: str) -> str:
        p = self.player(name)
        if p.status.get("cleaned"):
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
            p.status["target"] = rng.choice([q.name for q in players if q is not p])
        if p.role == "Roleplayer":
            p.status["fake_role"] = rng.choice(
                [r for r, i in ROLES.items() if i.category == "Investigative"])
    log.write("setup", players=[{"name": p.name, "seat": p.seat, "model": p.model.value, "role": p.role,
                                 "status": p.status} for p in players], katana=game.katana_holder)
    return game


def majority(yes: int, total: int) -> bool:
    return yes * 2 > total  # strictly more than half
