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
from roles.base import acted_tonight, join_names, swap_partner

if TYPE_CHECKING:
    from state import Game, Player


@dataclass(frozen=True)
class TraitInfo:
    alignments: frozenset[Alignment]  # whose true role's alignment can get it (faction-specific for now)
    summary: str  # what its holder is told, after "Your trait: NAME."
    hover: str  # one short line shown when hovering its holder's icon in the HTML log
    power: float  # logit units like role_power.PRIOR: what it adds to the Village's side when drawn (setups.py)
    # A small SVG drawn in the top-right corner of its holder's role icon in the HTML log (log_viewer.py): mostly
    # opaque (the icon shows through a little), in a color no faction uses, so it doesn't read as a faction tint.
    mark: str


TRAITS: dict[str, TraitInfo] = {
    "Martyr": TraitInfo(frozenset({Alignment.GOOD}),
                        "If you are hanged, your death announcement says you were a Martyr and names every player "
                        "whose vote counted as Guilty in your trial (rules R24).",
                        "If hanged, reveals this trait and every Guilty voter (not the role).",
                        power=0.15,
                        mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                              "<circle cx='5' cy='5' r='4.4' fill='#6d28d9' stroke='#fff' stroke-width='1'/>"
                              "<ellipse cx='5' cy='5' rx='2.4' ry='1.3' fill='none' stroke='#fde047' "
                              "stroke-width='1.1'/></svg>")),  # a halo
    "Armed": TraitInfo(frozenset({Alignment.GOOD}),
                       "Once per game, at night, you may fire a hidden gun at a living player: a Basic Attack, in "
                       "addition to your role's own night action (rules R24).",
                       "One hidden-gun shot a game: a Basic Attack at night, besides the role's action.",
                       power=0.25,
                       mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                             "<circle cx='5' cy='5' r='4.4' fill='#0f766e' stroke='#fff' stroke-width='1'/>"
                             "<circle cx='5' cy='5' r='2.3' fill='none' stroke='#fff' stroke-width='0.9'/>"
                             "<path d='M5 1.6V8.4M1.6 5H8.4' stroke='#fff' stroke-width='0.9'/></svg>")),  # crosshairs
}


class TraitLogic:
    """Defaults for every trait hook."""

    # A night action (rules R24): holders who can use it tonight (can_act) are asked for it in the night answer's
    # trait_actions, a list of {trait, target}, besides their role's action; the moderator records it with this
    # trait's ops, which work like a role's (RoleLogic.ops, check_op, apply_op) and are offered when the trait is in
    # the game, with night_note.
    ops: dict[str, tuple[set[str], set[str], str]] = {}
    night_note: str = ""
    code_tells_user: bool = False
    action_task: str = ""  # how the night task asks for this trait's action

    def can_act(self, game: Game, p: Player) -> bool:
        """Whether p, who has this trait, may use its night action tonight."""
        return False

    def check_op(self, game: Game, change: dict) -> str | None:
        return None

    def apply_op(self, game: Game, change: dict) -> None:
        pass

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


ARMED_USED = "armed_used"  # game.role_state: players who have fired their hidden gun (it's one shot a game)


class Armed(TraitLogic):
    ops = {"fire_gun": ({"player", "by"}, set(),
                        "{op:'fire_gun', player, by}: the Armed player `by` fires their hidden gun at `player` "
                        "(trait, R24); code marks their one shot used. Resolve the Basic Attack yourself")}
    night_note = ("Armed (a trait, R24): a player whose trait_actions has trait 'Armed' fires their one hidden-gun "
                  "shot at its target, in addition to their role's action. It is an action and a visit (R6; record "
                  "it, and an alerting Veteran's attack hits the shooter): a role-block stops it along with their "
                  "role's action, and then the shot isn't used. Unless they were role-blocked, use the fire_gun op "
                  "(it marks the shot used, even if the attack fails) and resolve a Basic Attack on the target (R3): "
                  "a kill's cause is 'a hidden gun' and its by is the shooter. Tell the shooter only whether their "
                  "shot killed its target, never the target's role, and tell a surviving target they were attacked.")
    action_task = ("You are Armed (your trait): you may fire your one hidden-gun shot tonight by adding "
                   "{trait: 'Armed', target} to trait_actions, besides your role's own action; leave trait_actions "
                   "empty to keep the shot.")

    def can_act(self, game: Game, p: Player) -> bool:
        return p.name not in game.role_state.get(ARMED_USED, [])

    def check_op(self, game: Game, change: dict) -> str | None:
        by, target = game.player(change["by"]), game.player(change["player"])
        if "Armed" not in by.traits or not acted_tonight(game, by):
            return f"{by.name} is not an Armed player who was alive when the night began"
        if not self.can_act(game, by):
            return f"{by.name} has already fired their hidden gun"
        if not acted_tonight(game, target):
            return f"{target.name} wasn't alive at the start of the night"
        if target is by and not swap_partner(game, by.name):
            return "an Armed player can't shoot themselves"
        return None

    def apply_op(self, game: Game, change: dict) -> None:
        game.role_state.setdefault(ARMED_USED, []).append(change["by"])


LOGIC: dict[str, TraitLogic] = {"Martyr": Martyr(), "Armed": Armed()}
assert set(LOGIC) == set(TRAITS)


def trait_logic(name: str) -> TraitLogic:
    return LOGIC[name]


ACTION_TRAITS = [t for t, lg in LOGIC.items() if lg.ops]  # traits with a night action (players.trait_actions_schema)


def eligible(p: Player, trait: str) -> bool:
    # A player may have several traits, never the same one twice (Kevin, Oct 12 2026).
    return p.info.alignment in TRAITS[trait].alignments and trait not in p.traits


def night_traits(game: Game, p: Player) -> list[str]:
    """p's traits whose night action p may use tonight."""
    return [t for t in p.traits if trait_logic(t).can_act(game, p)]


def briefing(p: Player) -> list[str]:
    return [f"Your trait: {t}. {TRAITS[t].summary}" for t in p.traits]
