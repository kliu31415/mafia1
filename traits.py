"""Traits (rules R24): an extra ability some players have on top of their role, e.g. Martyr. The player knows their
own trait; nobody else is told, investigations never see traits, and whether a game has any is secret.

A trait is a TraitInfo entry in TRAITS (who can get it, the line its holder is told, its power for setups.py)
plus a TraitLogic subclass for what code carries out, using the same hooks as roles (roles/base.py) where they
apply. A trait stays with its player when their role changes (an Executioner becoming a Jester)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from events import DEATH
from roles import Alignment
from roles.base import join_names

if TYPE_CHECKING:
    from state import Game, Player


@dataclass(frozen=True)
class TraitInfo:
    alignments: frozenset[Alignment]  # whose true role's alignment can get it (faction-specific for now)
    summary: str  # what its holder is told, after "Your trait: NAME."
    power: float  # logit units like role_power.PRIOR: what it adds to the Village's side when drawn (setups.py)


TRAITS: dict[str, TraitInfo] = {
    "Martyr": TraitInfo(frozenset({Alignment.GOOD}),
                        "If you are hanged, your death announcement says you were a Martyr and names every player "
                        "whose vote counted as Guilty in your trial (rules R24).",
                        power=0.15),
}


class TraitLogic:
    """Defaults for every trait hook."""

    def on_death(self, game: Game, p: Player, guilty_voters: list[str] | None) -> None:
        """After p's death is announced (or queued, at night). guilty_voters is set only for a hanging."""


class Martyr(TraitLogic):
    def on_death(self, game: Game, p: Player, guilty_voters: list[str] | None) -> None:
        if guilty_voters is None:  # rules R24: only a hanging reveals a Martyr
            return
        # The votes as counted (a Fixer may reverse one); a doubled vote (Ballot Stuffer) names its voter once.
        game.emit(f"{p.name} was a Martyr (a trait, R24). Guilty votes in their trial: "
                  f"{join_names(list(dict.fromkeys(guilty_voters))) or 'none'}.", cat=DEATH)
        game.log.write("martyr", player=p.name, guilty=guilty_voters, day=game.day)


LOGIC: dict[str, TraitLogic] = {"Martyr": Martyr()}
assert set(LOGIC) == set(TRAITS)


def trait_logic(name: str) -> TraitLogic:
    return LOGIC[name]


def eligible(p: Player, trait: str) -> bool:
    return p.info.alignment in TRAITS[trait].alignments and not p.traits  # at most one trait each


def briefing(p: Player) -> list[str]:
    return [f"Your trait: {t}. {TRAITS[t].summary}" for t in p.traits]
