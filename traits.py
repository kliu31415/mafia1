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
from roles.base import REVENGE_CAUSE, acted_tonight, join_names, record_attack, swap_partner

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
    # Was the Cardinal role until log version 51 (roles.RETIRED); harmful to its holder's side.
    "Cursed": TraitInfo(frozenset({Alignment.GOOD}),
                        "If you die, a random living Good player is dealt a Divine Attack at the end of the night "
                        "(rules R24).",
                        "If they die, a random living Good player is dealt a Divine Attack at the end of the night.",
                        power=-0.1,
                        mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                              "<circle cx='5' cy='5' r='4.4' fill='#3f3f46' stroke='#fff' stroke-width='1'/>"
                              "<circle cx='5' cy='4.4' r='2' fill='#e4e4e7'/>"
                              "<rect x='3.9' y='5.6' width='2.2' height='1.6' fill='#e4e4e7'/>"
                              "<circle cx='4.3' cy='4.3' r='0.5' fill='#3f3f46'/>"
                              "<circle cx='5.7' cy='4.3' r='0.5' fill='#3f3f46'/></svg>")),  # a skull
    "Avenger": TraitInfo(frozenset({Alignment.GOOD}),
                         "If you are killed at night, every player whose attack killed you is dealt a Divine Attack "
                         "and dies too (rules R24).",
                         "If killed at night, every player whose attack killed them dies too (a Divine Attack).",
                         power=0.4,
                         mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                               "<circle cx='5' cy='5' r='4.4' fill='#1e3a8a' stroke='#fff' stroke-width='1'/>"
                               "<path d='M5.8 1.8L3.2 5.4H5L4.2 8.2L6.8 4.6H5Z' fill='#fde047'/></svg>")),  # a bolt
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

    def apply_op(self, game: Game, change: dict) -> str | None:
        return None

    def on_death(self, game: Game, p: Player, guilty_voters: list[str] | None) -> None:
        """After p's death is announced (or queued, at night). guilty_voters is set only for a hanging."""

    night_end_order: int = 0  # like RoleLogic.night_end_order: at_night_end hooks of roles and traits run by it

    def at_night_end(self, game: Game) -> None:
        """End of each night, with the roles' at_night_end hooks. Called whether or not anyone has the trait."""


class Martyr(TraitLogic):
    def on_death(self, game: Game, p: Player, guilty_voters: list[str] | None) -> None:
        if guilty_voters is None:  # rules R24: only a hanging reveals a Martyr
            return
        # The votes as counted (a Fixer may reverse one); a doubled vote (Ballot Stuffer) names its voter once.
        voters = join_names(list(dict.fromkeys(guilty_voters))) or "none"
        game.emit(f"{p.name} was a Martyr (a trait, R24). Guilty votes in their trial: {voters}.", cat=DEATH)
        game.death_record.append(f"Day {game.day}: {p.name} was a Martyr; Guilty votes: {voters}")  # the ledger
        game.log.write("martyr", player=p.name, guilty=guilty_voters, day=game.day)


AVENGER_CAUSE, CURSE_CAUSE = "Avenger", "a curse"  # the causes of attacks code makes (also REVENGE_CAUSE)


class Avenger(TraitLogic):
    night_note = ("Avenger (a trait, R24): when you kill an Avenger at night, code deals a Divine Attack to every "
                  "player in that kill's `by` (alive when the night began) and kills them (cause 'Avenger'), so list "
                  "in `by` every player whose attack would have killed them (R12). Don't resolve it yourself; you "
                  "don't tell() those deaths either.")

    def on_death(self, game: Game, p: Player, guilty_voters: list[str] | None) -> None:
        if game.phase != "night" or not p.death:  # rules R24: only a night death; a hanging isn't an attack
            return
        # Code-made attacks (a Jester's revenge, a Cursed player's curse, another Avenger's) aren't the user's own
        # attack, so they don't set it off. A killer who died earlier in tonight's resolution is still hit (rules
        # R10: the night is simultaneous; R12: the cause joins their death), whatever order the moderator's ops came in.
        cause = p.death["cause"]
        if cause in (CURSE_CAUSE, AVENGER_CAUSE) or cause.endswith(REVENGE_CAUSE):
            return
        for name in dict.fromkeys(p.death["killers"]):
            if acted_tonight(game, game.player(name)) and name != p.name:
                record_attack(game, p.name)  # for the Bloodhound's counts
                game.log.write("avenger", player=p.name, killed=name, day=game.day)
                game.kill(name, AVENGER_CAUSE, by=p.name)


# The old Cardinal role's key (roles.RETIRED), so a checkpoint saved with a curse pending carries it over.
CURSES = "cardinal_curses"  # game.role_state: Cursed players who died, whose curse strikes at the end of the night


class Cursed(TraitLogic):
    # The moderator drew and killed a curse victim itself during the night in game_20261009_212707_751277,
    # and code then dealt the real curse at dawn: two victims.
    night_note = ("Cursed (a trait, R24): for a Cursed player who died today or dies tonight, code deals a Divine "
                  "Attack on a random Good player after your resolution, at the end of the night. Don't draw or kill "
                  "a victim yourself.")

    def on_death(self, game: Game, p: Player, guilty_voters: list[str] | None) -> None:
        game.role_state.setdefault(CURSES, []).append(p.name)

    def at_night_end(self, game: Game) -> None:
        # Kevin, Oct 10: the curse ends the night rather than starting the Day, so it plainly counts as a night
        # death (stall rule R14, wills R13). A Cursed player the curse kills curses in turn, the same night.
        while curses := game.role_state.pop(CURSES, []):
            for cursed in curses:
                good = [q.name for q in game.alive() if q.info.alignment is Alignment.GOOD]
                if good:
                    victim = game.rng.choice(good)
                    game.log.write("curse", victim=victim, cursed=cursed)
                    game.kill(victim, CURSE_CAUSE, by=cursed)  # by: for deaths-by-role analysis
                    record_attack(game, cursed)  # a Divine Attack


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


LOGIC: dict[str, TraitLogic] = {"Martyr": Martyr(), "Armed": Armed(), "Avenger": Avenger(), "Cursed": Cursed()}
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
