"""Traits (rules R24): an extra ability some players have on top of their role, e.g. Martyr. The player knows their
own trait; nobody else is told, investigations never see traits, and whether a game has any is secret.

A trait is a TraitInfo entry in TRAITS (who can get it, the line its holder is told, its power for setups.py,
refit from game results by role_power.py) plus a TraitLogic subclass for what code carries out, using the same hooks
as roles (roles/base.py) where they apply. A trait stays with its player when their role changes (an Executioner
becoming a Jester)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from events import DEATH, VOTE
from roles import ROLES, Alignment
from roles.base import DISGUISES, REVENGE_CAUSE, acted_tonight, join_names, record_attack, swap_partner

if TYPE_CHECKING:
    from state import Game, Player


@dataclass(frozen=True)
class TraitInfo:
    alignments: frozenset[Alignment]  # whose true role's alignment can get it; may be any (Grudge)
    summary: str  # what its holder is told, after "Your trait: NAME."
    hover: str  # one short line shown when hovering its holder's icon in the HTML log
    # Logit units like role_power.PRIOR: how much it helps its holder's own side (negative: it hurts them), so it
    # keeps its meaning if the alignments it can go to change (Kevin, Oct 12 2026). setups.py counts it towards the
    # Village by the holder's alignment (village_power). It's the prior: role_power.py refits it from game results.
    power: float
    # A small SVG drawn in the top-right corner of its holder's role icon in the HTML log (log_viewer.py): mostly
    # opaque (the icon shows through a little), in a color no faction uses, so it doesn't read as a faction tint.
    mark: str
    power_for: dict[Alignment, float] | None = None  # power for some alignments, where it differs from `power`
    hidden: bool = False  # its holder isn't told (rules R24 says which); `summary` then only goes to the rules
    fits_role: Callable[[str], bool] | None = None  # which roles can get it, besides `alignments` (None: any)
    unique: bool = False  # at most one player in a game holds it (rules R24 says which)


# Roles whose rules paragraph says they can't be role-blocked (a test checks), so a role-block trait never fits them.
BLOCK_IMMUNE = frozenset({"Veteran", "Party Animal", "Pharmacist", "Smuggler"})
DROWSY_ODDS = 0.5  # rules R24 states it (a test checks)
PARANOID_ODDS = 0.25  # rules R24 states it (a test checks)
PARANOID_KATANA = 2 / 3  # how often a Paranoid's fake attack is the Katana's, when not one of PARANOID_ATTACKERS
# Roles a fake attack can name besides the Katana: ones that attack a chosen player at night and may appear more than
# once, so a second attack by one is never provably false (Kevin, Oct 13 2026). Only those in the game's script.
PARANOID_ATTACKERS = ("Vigilante", "Serial Killer")

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
    "Kindred": TraitInfo(frozenset({Alignment.GOOD}),
                         "After each trial vote you cast, you privately learn up to two random other players whose "
                         "votes counted the same way as the vote you cast (rules R24).",
                         "After each trial, learns two random players who voted the same way.",
                         power=0.15,
                         mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                               "<circle cx='5' cy='5' r='4.4' fill='#9d174d' stroke='#fff' stroke-width='1'/>"
                               "<circle cx='3.9' cy='5' r='1.7' fill='none' stroke='#fff' stroke-width='0.9'/>"
                               "<circle cx='6.1' cy='5' r='1.7' fill='none' stroke='#fff' "
                               "stroke-width='0.9'/></svg>")),  # two linked rings
    # Village only (Kevin, Oct 13 2026): a Guilty vote risks the holder's life, and surviving one tells them the hanged
    # player wasn't Village. Compared with the vote as cast, like Kindred, so a Fixer's hidden reversal can't kill
    # (or spare) them; never with Zealot, whose votes always count as Guilty (EXCLUSIVE).
    "Remorseful": TraitInfo(frozenset({Alignment.GOOD}),
                            "If you vote Guilty in a trial and that player is hanged and was Village, you die at once "
                            "of remorse (rules R24).",
                            "Dies of remorse after voting Guilty on a hanged Villager.",
                            power=-0.1,
                            mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                                  "<circle cx='5' cy='5' r='4.4' fill='#475569' stroke='#fff' stroke-width='1'/>"
                                  "<path d='M5 2.4Q6.8 5 6.8 6A1.8 1.8 0 0 1 3.2 6Q3.2 5 5 2.4Z' fill='#fff'/>"
                                  "</svg>")),  # a tear
    "Faultline": TraitInfo(frozenset({Alignment.GOOD}),
                           "After each trial vote you cast, you privately learn one random other player whose vote "
                           "counted as Guilty and one whose vote counted as Innocent (rules R24).",
                           "After each trial, learns one random Guilty voter and one random Innocent voter.",
                           power=0.15,
                           mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                                 "<circle cx='5' cy='5' r='4.4' fill='#9a3412' stroke='#fff' stroke-width='1'/>"
                                 "<path d='M4.4 1.4L5.8 3.8L4.2 5.6L5.9 8.6' fill='none' stroke='#fff' "
                                 "stroke-width='1.1'/></svg>")),  # a crack
    # Harmful to its holder's side, like Cursed: alignment checks can't clear them (Kevin, Oct 12 2026).
    "Notorious": TraitInfo(frozenset({Alignment.GOOD}),
                           "Alignment checks see you as Evil, though you are Village (rules R19, R24).",
                           "Reads Evil to alignment checks.",
                           power=-0.1,
                           mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                                 "<circle cx='5' cy='5' r='4.4' fill='#111827' stroke='#fff' stroke-width='1'/>"
                                 "<path d='M2.4 4.4Q5 2.6 7.6 4.4Q5 6.2 2.4 4.4Z' fill='#fff'/>"
                                 "<circle cx='5' cy='4.4' r='0.9' fill='#111827'/></svg>")),  # an eye
    # Any faction (Kevin, Oct 12 2026). More use to a Yakuza: the Village hangs Yakuza far more than its own, and those
    # Guilty voters are mostly Village.
    "Grudge": TraitInfo(frozenset(Alignment),
                        "If you are hanged, one random player whose vote counted as Guilty in your trial is dealt a "
                        "Standard Attack the next night (rules R24).",
                        "If hanged, a random Guilty voter is dealt a Standard Attack the next night.",
                        power=0.1, power_for={Alignment.EVIL: 0.3},
                        mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                              "<circle cx='5' cy='5' r='4.4' fill='#7f1d1d' stroke='#fff' stroke-width='1'/>"
                              "<path d='M2.6 3.4L4.4 4.4M7.4 3.4L5.6 4.4M3.2 7.2Q5 5.6 6.8 7.2' fill='none' "
                              "stroke='#fff' stroke-width='0.9'/></svg>")),  # a scowl
    # Any faction (Kevin, Oct 12 2026): a loud Yakuza and a loud Villager look the same.
    "Loud": TraitInfo(frozenset(Alignment),
                      "You earn 1.5 times the usual speaking budget each round, and can hold 1.5 times as much "
                      "(rules R22, R24).",
                      "Earns 1.5x speaking budget per round, with a 1.5x cap.",
                      power=0.1,
                      mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                            "<circle cx='5' cy='5' r='4.4' fill='#b45309' stroke='#fff' stroke-width='1'/>"
                            "<path d='M2.4 4H3.8L5.8 2.6V7.4L3.8 6H2.4Z' fill='#fff'/>"
                            "<path d='M6.9 3.6Q7.8 5 6.9 6.4' fill='none' stroke='#fff' "
                            "stroke-width='0.8'/></svg>")),  # a speaker
    # Any faction (Kevin, Oct 12 2026): short messages stay cheap, long ones don't; harmful to its holder's side.
    "Curt": TraitInfo(frozenset(Alignment),
                      "The length part of your message prices is doubled; each message's base fee and nominations "
                      "cost the usual amount (rules R22, R24).",
                      "Pays double for message length (not the base fee).",
                      power=-0.1,
                      mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                            "<circle cx='5' cy='5' r='4.4' fill='#475569' stroke='#fff' stroke-width='1'/>"
                            "<path d='M2.8 5H7.2' stroke='#fff' stroke-width='1.3'/></svg>")),  # a closed mouth
    # Any faction (Kevin, Oct 12 2026): secret deals. Players who hear private messages (Wiretap, Eavesdropper)
    # still hear it, marked hidden; only the public "A sent B a private message" line is dropped.
    "Confidant": TraitInfo(frozenset(Alignment),
                           "Once per game, on one of your own Day turns, you may send one private message hidden: "
                           "nobody else is told it was sent (rules R24).",
                           "One hidden private message a game: nobody else is told it was sent.",
                           power=0.1,
                           mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                                 "<circle cx='5' cy='5' r='4.4' fill='#155e75' stroke='#fff' stroke-width='1'/>"
                                 "<rect x='2.5' y='3.3' width='5' height='3.4' fill='none' stroke='#fff' "
                                 "stroke-width='0.8'/><path d='M2.5 3.3L5 5.2L7.5 3.3' fill='none' stroke='#fff' "
                                 "stroke-width='0.8'/></svg>")),  # a sealed envelope
    # Any faction, never both on one player (Kevin, Oct 13 2026; EXCLUSIVE). The holder still votes, so nothing about
    # who was asked shows, and knows the vote won't count: "it wasn't my vote" is a claim anyone can make.
    "Zealot": TraitInfo(frozenset(Alignment),
                        "Every Guilty/Innocent trial vote you cast counts as Guilty, whatever you vote, including in "
                        "your own trial; your nomination votes are unchanged (rules R24).",
                        "Trial votes always count as Guilty, whatever they vote.",
                        power=-0.1, power_for={Alignment.EVIL: -0.15},
                        mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                              "<circle cx='5' cy='5' r='4.4' fill='#86198f' stroke='#fff' stroke-width='1'/>"
                              "<rect x='2.6' y='2.6' width='3.6' height='1.8' fill='#fff' "
                              "transform='rotate(-45 4.4 3.5)'/>"
                              "<path d='M4.6 4.4L7.4 7.2' stroke='#fff' stroke-width='1'/></svg>")),  # a gavel
    "Merciful": TraitInfo(frozenset(Alignment),
                          "Every Guilty/Innocent trial vote you cast counts as Innocent, whatever you vote; your "
                          "nomination votes are unchanged (rules R24).",
                          "Trial votes always count as Innocent, whatever they vote.",
                          power=-0.1, power_for={Alignment.EVIL: -0.15},
                          mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                                "<circle cx='5' cy='5' r='4.4' fill='#4338ca' stroke='#fff' stroke-width='1'/>"
                                "<path d='M5 7.4L2.7 5.1Q1.9 4 2.8 3.2Q3.9 2.5 5 3.7Q6.1 2.5 7.2 3.2Q8.1 4 7.3 5.1Z' "
                                "fill='#fff'/></svg>")),  # a heart
    # Any faction (Kevin, Oct 13 2026), a role with a night action that can be role-blocked. Hidden: the holder gets
    # the usual "you were role-blocked" and may hunt a blocker who doesn't exist.
    "Drowsy": TraitInfo(frozenset(Alignment),
                        "On each night, with probability 1/2, you are role-blocked (R9) with no blocker. You aren't "
                        "told you have this trait (rules R24).",
                        "Hidden: role-blocked on a random half of nights, with no blocker.",
                        power=-0.15, hidden=True,
                        fits_role=lambda r: ROLES[r].acts_at_night and r not in BLOCK_IMMUNE,
                        mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                              "<circle cx='5' cy='5' r='4.4' fill='#334155' stroke='#fff' stroke-width='1'/>"
                              "<path d='M6.4 2.4A2.8 2.8 0 1 0 7.6 6.4A2.2 2.2 0 0 1 6.4 2.4Z' "
                              "fill='#fde68a'/></svg>")),  # a crescent moon
    # Yakuza only (Kevin, Oct 13 2026): a disposable Katana, so a night can have two Katana attacks, which also keeps
    # Paranoid's fake Katana attacks plausible.
    "Spare Blade": TraitInfo(frozenset({Alignment.EVIL}),
                             "Once per game, at night, you may make one extra Katana attack on another living player, "
                             "whoever holds the Katana and besides its own attack (rules R8, R24).",
                             "One extra Katana attack a game, at night.",
                             power=0.35,
                             mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                                   "<circle cx='5' cy='5' r='4.4' fill='#57534e' stroke='#fff' stroke-width='1'/>"
                                   "<path d='M2.8 7.6L7.2 2.4M2.8 2.4L7.2 7.6' stroke='#fff' "
                                   "stroke-width='1.1'/></svg>")),  # crossed blades
    # Village only, hidden (Kevin, Oct 13 2026): the moderator words the fake like a real defended attack, so the holder
    # can't tell. An extra Katana attack (Spare Blade) can exist, so a fake Katana attack is never provably false.
    "Paranoid": TraitInfo(frozenset({Alignment.GOOD}),
                          "On each night, with probability 1/4, you are told you were attacked and survived, though "
                          "nobody attacked you. You aren't told you have this trait (rules R24).",
                          "Hidden: told of a fake attack they survived on a random quarter of nights.",
                          power=-0.1, hidden=True,
                          mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                                "<circle cx='5' cy='5' r='4.4' fill='#0f172a' stroke='#fff' stroke-width='1'/>"
                                "<path d='M5 2.4V5.8' stroke='#fde047' stroke-width='1.3'/>"
                                "<circle cx='5' cy='7.3' r='0.75' fill='#fde047'/></svg>")),  # an exclamation mark
    # Any faction, only roles that start with tokens (Kevin, Oct 13 2026): never a Roleplayer (its role has none).
    "Stocked": TraitInfo(frozenset(Alignment),
                         "You start with one more of each kind of token your role starts with (rules R24).",
                         "Starts with one extra token of each kind its role has.",
                         power=0.15,
                         fits_role=lambda r: bool(ROLES[r].tokens),
                         mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                               "<circle cx='5' cy='5' r='4.4' fill='#a16207' stroke='#fff' stroke-width='1'/>"
                               "<path d='M5 2.6V7.4M2.6 5H7.4' stroke='#fff' stroke-width='1.3'/></svg>")),  # a plus
    # Any faction, told (Kevin, Oct 13 2026): one trait for the Yakuza disguise and the Village lookalike; the power
    # differs by faction. Always a Village disguise: anything else would be useless or self-incriminating.
    "Disguised": TraitInfo(frozenset(Alignment),
                           "Exact-role checks (R18) see you as the Village role named below instead of your own; "
                           "alignment checks still see your true alignment (rules R19, R24).",
                           "Exact-role checks see a Village role drawn at setup instead of theirs.",
                           power=-0.1, power_for={Alignment.EVIL: 0.3},
                           mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                                 "<circle cx='5' cy='5' r='4.4' fill='#5b21b6' stroke='#fff' stroke-width='1'/>"
                                 "<path d='M2.2 4.2Q5 3.2 7.8 4.2Q7.6 6.4 5.6 6.2L5 5.6L4.4 6.2Q2.4 6.4 2.2 4.2Z' "
                                 "fill='#fff'/></svg>")),  # a mask
    # Village and Yakuza (Kevin, Oct 13 2026: random pairs; Neutrals left out, since a Serial Killer bonded to anyone
    # could never win). Dealt as one trait; on_dealt bonds a random partner, who gets it too.
    "Bonded": TraitInfo(frozenset({Alignment.GOOD, Alignment.EVIL}),
                        "You are bonded to the player named below, of any faction (you aren't told theirs), and they "
                        "to you. If either of you dies, the other dies of heartbreak at once (rules R24).",
                        "Bonded to one other player: if either dies, the other dies of heartbreak.",
                        power=0.0,
                        mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                              "<circle cx='5' cy='5' r='4.4' fill='#be185d' stroke='#fff' stroke-width='1'/>"
                              "<path d='M2.4 5H7.6M3.6 3.6L2.4 5L3.6 6.4M6.4 3.6L7.6 5L6.4 6.4' fill='none' "
                              "stroke='#fff' stroke-width='0.9'/></svg>")),  # a two-way link
    # Village and Yakuza (Kevin, Oct 13 2026): Neutrals' wins already need survival or contradict it (the Jester).
    # Only the holder's own win changes, not the faction's.
    "Selfish": TraitInfo(frozenset({Alignment.GOOD, Alignment.EVIL}),
                         "You win only if your faction wins and you are alive at the end; your faction's win doesn't "
                         "change (rules R1, R24).",
                         "Shares the faction's win only if alive at the end.",
                         power=-0.1,
                         mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                               "<circle cx='5' cy='5' r='4.4' fill='#ca8a04' stroke='#fff' stroke-width='1'/>"
                               "<circle cx='5' cy='5' r='2.2' fill='none' stroke='#fff' stroke-width='1'/>"
                               "<circle cx='5' cy='5' r='0.7' fill='#fff'/></svg>")),  # a coin
    # Selfish's mirror (Kevin, Oct 13 2026; his idea, named Selfless): same factions, never both on one player.
    "Selfless": TraitInfo(frozenset({Alignment.GOOD, Alignment.EVIL}),
                          "You win only if your faction wins and you are dead at the end; your faction's win doesn't "
                          "change (rules R1, R24).",
                          "Shares the faction's win only if dead at the end.",
                          power=-0.15, power_for={Alignment.EVIL: 0.1},
                          mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                                "<circle cx='5' cy='5' r='4.4' fill='#0d9488' stroke='#fff' stroke-width='1'/>"
                                "<path d='M5 7.4L2.6 5A1.3 1.3 0 0 1 5 3.6A1.3 1.3 0 0 1 7.4 5Z' fill='#fff'/>"
                                "</svg>")),  # a heart
    # Yakuza only, unique (Kevin, Oct 13 2026): in who wins, a one-person faction inside the Yakuza; for everything
    # else (night chat, the Katana, checks, when the game ends) a Yakuza.
    "Usurper": TraitInfo(frozenset({Alignment.EVIL}),
                         "You win only if the Yakuza win while you are the only Yakuza alive, and then you take the "
                         "win alone: the other Yakuza lose. Your teammates aren't told (rules R1, R24).",
                         "Wins only as the last Yakuza alive, and then alone.",
                         power=-0.3, unique=True,
                         mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                               "<circle cx='5' cy='5' r='4.4' fill='#a16207' stroke='#fff' stroke-width='1'/>"
                               "<path d='M2.6 6.6V3.6L3.9 4.9L5 3L6.1 4.9L7.4 3.6V6.6Z' fill='#fff'/>"
                               "</svg>")),  # a crown
    # Any faction, hidden (Kevin, Oct 13 2026): Paranoid's mirror, so "was I attacked?" is unreliable both ways.
    # Yakuza only, hidden (Kevin, Oct 13 2026): the attack is demoted to level None (R3), which never kills, rather
    # than a special "does nothing" rule; the kill op refuses a Katana kill by a Shaky player (kill_error).
    "Shaky": TraitInfo(frozenset({Alignment.EVIL}),
                       "Every Katana attack you make (the Katana's own while you hold it, or a Spare Blade attack) is "
                       "level None, so it never kills. You aren't told you have this trait (rules R3, R24).",
                       "Hidden: their Katana attacks are level None and never kill.",
                       power=-0.3, hidden=True,
                       mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                             "<circle cx='5' cy='5' r='4.4' fill='#78350f' stroke='#fff' stroke-width='1'/>"
                             "<path d='M2.4 6.2L3.7 3.8L5 6.2L6.3 3.8L7.6 6.2' fill='none' stroke='#fff' "
                             "stroke-width='0.9'/></svg>")),  # a trembling line
    # Village only, unique (Kevin, Oct 13 2026): plays as a Yakuza ally from every player's view, but stays Village in
    # code, so no Yakuza chat, Katana or faction code ever sees them. The Census Taker still counts them as Good.
    "Turncoat": TraitInfo(frozenset({Alignment.GOOD}),
                          "You win only if the Yakuza win, and alignment checks see you as Evil, though your role is "
                          "Village. You don't know who the Yakuza are, and they aren't told about you. The game's end "
                          "ignores you: it ends when the other living players are all Village or all Yakuza (rules R1, "
                          "R19, R24).",
                          "Wins only with the Yakuza; reads Evil to alignment checks; ignored when the game's end "
                          "is checked.",
                          power=-0.4, unique=True,
                          mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                                "<circle cx='5' cy='5' r='4.4' fill='#7f1d1d' stroke='#fff' stroke-width='1'/>"
                                "<path d='M3 3.6H6.6L5.6 2.6M7 6.4H3.4L4.4 7.4' fill='none' stroke='#fff' "
                                "stroke-width='0.9'/></svg>")),  # arrows turning back
    # Any faction, told (Kevin, Oct 13 2026): the Ex-Con's random visit as a trait (with Notorious, the old Ex-Con).
    # Muddies Trackers and Lookouts, which helps the Yakuza a little and costs a Villager a little.
    "Sleepwalker": TraitInfo(frozenset(Alignment),
                             "Each night you visit one random other living player, besides any action of your own. "
                             "You aren't told whom; it does nothing but visit, and a role-block stops it (rules R6, "
                             "R24).",
                             "Visits a random player each night without knowing whom.",
                             power=-0.05, power_for={Alignment.EVIL: 0.05},
                             mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                                   "<circle cx='5' cy='5' r='4.4' fill='#4338ca' stroke='#fff' stroke-width='1'/>"
                                   "<path d='M2.8 3.2H5L2.8 6.4H5M5.6 2.6H7.2L5.6 4.8H7.2' fill='none' stroke='#fff' "
                                   "stroke-width='0.8'/></svg>")),  # z z
    "Oblivious": TraitInfo(frozenset(Alignment),
                           "You are never told about an attack you survive. You aren't told you have this trait "
                           "(rules R24).",
                           "Hidden: never told about attacks they survive.",
                           power=-0.1, power_for={Alignment.EVIL: -0.05}, hidden=True,
                           mark=("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' opacity='0.8'>"
                                 "<circle cx='5' cy='5' r='4.4' fill='#374151' stroke='#fff' stroke-width='1'/>"
                                 "<path d='M2.4 4.6Q5 6.6 7.6 4.6' fill='none' stroke='#fff' stroke-width='1'/>"
                                 "</svg>")),  # a closed eye
}
# Traits no player may hold together (rules R24).
EXCLUSIVE = [frozenset({"Zealot", "Merciful"}), frozenset({"Paranoid", "Oblivious"}),
             frozenset({"Selfish", "Selfless"}), frozenset({"Usurper", "Selfish"}), frozenset({"Usurper", "Selfless"}),
             frozenset({"Remorseful", "Zealot"}), frozenset({"Turncoat", "Notorious"}),
             frozenset({"Turncoat", "Selfish"}), frozenset({"Turncoat", "Selfless"})]


class TraitLogic:
    """Defaults for every trait hook."""

    # A night action (rules R24): holders who can use it tonight (can_act) are asked for it in the night answer's
    # trait_actions, a list of {trait, target}, besides their role's action; the moderator records it with this
    # trait's ops, which work like a role's (RoleLogic.ops, check_op, apply_op) and are offered when the trait is in
    # the game, with night_note.
    ops: dict[str, tuple[set[str], set[str], str]] = {}
    night_note: str = ""
    budget_factor = 1.0  # multiplies the speaking budget earned each round and its cap (rules R22; Loud)
    length_factor = 1.0  # multiplies the length part of message prices (rules R22; Curt)
    fixed_trial_vote: bool | None = None  # how the holder's trial votes count, whatever they cast (True: Guilty)
    # The holder shares their faction's win only if alive (True: Selfish) or dead (False: Selfless) at the end (rules
    # R1, R24).
    win_needs_alive: bool | None = None
    takes_win = False  # the holder wins only as the last of their faction alive, and then alone (rules R1, R24)
    # The faction the holder wins with instead of their own (Turncoat); the game's end ignores them (rules R1, R24).
    wins_with: str | None = None

    def random_visit(self, game: Game, p: Player) -> str | None:
        """A target code draws for the living holder's automatic visit tonight (Sleepwalker; rules R24), or None.
        night.py adds it to their trait_actions, marked automatic; the holder isn't told whom."""
        return None

    def can_hide_pm(self, game: Game, p: Player) -> bool:
        """Whether p may send a hidden private message this turn (Confidant): day.chat_turn offers hidden_pm."""
        return False

    def hid_pm(self, game: Game, p: Player, to: str) -> None:
        """p sent a hidden private message to `to` with this trait."""
    code_tells_user: bool = False
    action_task: str = ""  # how the night task asks for this trait's action

    def can_act(self, game: Game, p: Player) -> bool:
        """Whether p, who has this trait, may use its night action tonight."""
        return False

    def check_op(self, game: Game, change: dict) -> str | None:
        return None

    def apply_op(self, game: Game, change: dict) -> str | None:
        return None

    def on_dealt(self, game: Game, p: Player) -> None:
        """p was just dealt this trait, at setup (after the roles' setup hooks)."""

    def detail(self, game: Game, p: Player) -> str:
        """What p's briefing adds after this trait's summary (e.g. a Disguised player's disguise)."""
        return ""

    def on_death(self, game: Game, p: Player, guilty_voters: list[str] | None) -> None:
        """After p's death is announced (or queued, at night). guilty_voters is set only for a hanging."""

    night_end_order: int = 0  # like RoleLogic.night_end_order: at_night_end hooks of roles and traits run by it

    def at_night_end(self, game: Game) -> None:
        """End of each night, with the roles' at_night_end hooks. Called whether or not anyone has the trait."""

    def tonight_note(self, game: Game) -> str:
        """A note for the moderator about this night only (night.role_notes), e.g. whom a Grudge strikes; code may
        draw what it needs here, since it's called once a night, as the night's resolution begins."""
        return ""

    def after_trial_vote(self, game: Game, nominee: str, cast: dict[str, bool], guilty: list[str]) -> None:
        """Right after a trial's votes are counted, before the verdict. cast: each voter's vote as cast (True is
        Guilty); guilty: the voters whose vote counted as Guilty (after a Fixer's reversal)."""

    def kill_error(self, game: Game, change: dict) -> str | None:
        """Why the moderator's kill op can't apply as given (it's refused, with this reason), or None."""
        return None

    def after_hanging(self, game: Game, hanged: Player, cast: dict[str, bool]) -> None:
        """Right after a trial's verdict hanged `hanged` (a Clerk's rig too). cast: each voter's vote as cast."""


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
HEARTBREAK_CAUSE = "heartbreak"  # a Bonded player's death when their partner dies: no attack by anyone
REMORSE_CAUSE = "remorse"  # a Remorseful player's death after a Guilty vote hanged a Villager: no attack by anyone


class Avenger(TraitLogic):
    night_note = ("Avenger (a trait, R24): when you kill an Avenger at night, code deals a Divine Attack to every "
                  "player in that kill's `by` (alive when the night began) and kills them (cause 'Avenger'), so list "
                  "in `by` every player whose attack would have killed them (R12). Don't resolve it yourself; you "
                  "don't tell() those deaths either.")

    def on_death(self, game: Game, p: Player, guilty_voters: list[str] | None) -> None:
        if game.phase != "night" or not p.death:  # rules R24: only a night death; a hanging isn't an attack
            return
        # Code-made deaths (a Jester's revenge, a Cursed player's curse, another Avenger's, heartbreak) aren't the
        # user's own attack, so they don't set it off. A killer who died earlier in tonight's resolution is still hit
        # (rules R10: the night is simultaneous; R12: the cause joins their death), whatever order the moderator's ops
        # came in.
        cause = p.death["cause"]
        if cause in (CURSE_CAUSE, AVENGER_CAUSE, HEARTBREAK_CAUSE, REMORSE_CAUSE) or cause.endswith(REVENGE_CAUSE):
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


class OneShotAction(TraitLogic):
    """A once-a-game night action on another living player, asked for in trait_actions and recorded with this trait's
    op (Armed, Spare Blade): code checks its user and target and marks it used; the moderator resolves its effect."""
    trait, used_key = "", ""  # the trait's name; the game.role_state key listing players who have used it
    holder, used, no_self = "", "", ""  # wording for check_op's errors

    def can_act(self, game: Game, p: Player) -> bool:
        return p.name not in game.role_state.get(self.used_key, [])

    def check_op(self, game: Game, change: dict) -> str | None:
        by, target = game.player(change["by"]), game.player(change["player"])
        if self.trait not in by.traits or not acted_tonight(game, by):
            return f"{by.name} is not {self.holder} who was alive when the night began"
        if not self.can_act(game, by):
            return f"{by.name} {self.used}"
        if not acted_tonight(game, target):
            return f"{target.name} wasn't alive at the start of the night"
        if target is by and not swap_partner(game, by.name):
            return self.no_self
        return None

    def apply_op(self, game: Game, change: dict) -> None:
        game.role_state.setdefault(self.used_key, []).append(change["by"])


class Armed(OneShotAction):
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
    trait, used_key = "Armed", ARMED_USED
    holder, used, no_self = ("an Armed player", "has already fired their hidden gun",
                             "an Armed player can't shoot themselves")


class Kindred(TraitLogic):
    def after_trial_vote(self, game: Game, nominee: str, cast: dict[str, bool], guilty: list[str]) -> None:
        # Compared with the holder's vote as cast, so a Fixer's hidden reversal of it isn't revealed (Fixer: "nobody
        # is told"); the others' votes are as counted, like the Auditor's. rules R24
        for name, vote in cast.items():
            if "Kindred" not in game.player(name).traits:
                continue
            same = [n for n in cast if n != name and (n in guilty) == vote]
            picked = sorted(game.rng.sample(same, min(2, len(same))), key=list(cast).index)
            way = "Guilty" if vote else "Innocent"
            text = (f"nobody else's vote counted as {way}" if not picked else
                    f"{join_names(picked)}'s votes counted as {way}" if len(picked) == 2 else
                    f"only {picked[0]}'s vote counted as {way}")
            game.log.write("kindred", day=game.day, player=name, nominee=nominee, named=picked)
            game.emit(f"(Only you see this) Kindred: in the trial of {nominee}, you voted {way}, and {text}"
                      + (" too." if picked else "."), [name], cat=VOTE)


class Remorseful(TraitLogic):
    def after_hanging(self, game: Game, hanged: Player, cast: dict[str, bool]) -> None:
        # rules R24: true alignments (a Notorious player is Village; a Neutral never counts). At once, like heartbreak;
        # not an attack by anyone, so nothing that reacts to attacks counts it.
        if hanged.info.alignment is not Alignment.GOOD:
            return
        for name, vote in cast.items():
            p = game.player(name)
            if vote and p.alive and "Remorseful" in p.traits and p.info.alignment is Alignment.GOOD:
                game.log.write("remorse", player=name, hanged=hanged.name, day=game.day)
                game.kill(name, REMORSE_CAUSE, by=hanged.name)


class Faultline(TraitLogic):
    def after_trial_vote(self, game: Game, nominee: str, cast: dict[str, bool], guilty: list[str]) -> None:
        # Others' votes as counted, like the Auditor's; the holder's own vote plays no part. rules R24
        for name in cast:
            if "Faultline" not in game.player(name).traits:
                continue
            sides = {way: [n for n in cast if n != name and (n in guilty) == way] for way in (True, False)}
            picked = {way: game.rng.choice(sides[way]) if sides[way] else None for way in (True, False)}
            game.log.write("faultline", day=game.day, player=name, nominee=nominee, guilty=picked[True],
                           innocent=picked[False])
            if picked[True] and picked[False]:
                text = (f"{picked[True]}'s vote counted as Guilty and {picked[False]}'s as Innocent (each picked at "
                        "random from that side).")
            else:
                text = f"every other vote counted as {'Guilty' if picked[True] else 'Innocent'}."
            game.emit(f"(Only you see this) Faultline: in the trial of {nominee}, {text}", [name], cat=VOTE)


LOUD_FACTOR, CURT_FACTOR = 1.5, 2.0  # rules R24 states both numbers (a test checks)


class Loud(TraitLogic):
    budget_factor = LOUD_FACTOR


class Curt(TraitLogic):
    length_factor = CURT_FACTOR


CONFIDANT_USED = "confidant_used"  # game.role_state: Confidants who have sent their one hidden private message


class Confidant(TraitLogic):
    def can_hide_pm(self, game: Game, p: Player) -> bool:
        return p.name not in game.role_state.get(CONFIDANT_USED, [])

    def hid_pm(self, game: Game, p: Player, to: str) -> None:
        game.role_state.setdefault(CONFIDANT_USED, []).append(p.name)
        game.log.write("confidant", player=p.name, to=to, day=game.day)


GRUDGES = "grudges"  # game.role_state: [holder, Guilty voters] for each Grudge holder hanged since the last night
GRUDGE_CAUSE = "a grudge"


class Grudge(TraitLogic):
    def on_death(self, game: Game, p: Player, guilty_voters: list[str] | None) -> None:
        if guilty_voters is not None:  # rules R24: only a hanging; the votes as counted (a Fixer may reverse one)
            game.role_state.setdefault(GRUDGES, []).append([p.name, list(dict.fromkeys(guilty_voters))])

    def tonight_note(self, game: Game) -> str:
        # Code draws the victim, like a Jester's revenge, from the Guilty voters alive as the night begins (R10); a
        # swap doesn't move it (R23). The moderator resolves the attack, since Defense and protection apply.
        lines = []
        for holder, voters in game.role_state.pop(GRUDGES, []):
            if targets := [v for v in voters if game.player(v).alive]:
                victim = game.rng.choice(targets)
                game.log.write("grudge", player=holder, victim=victim, day=game.day)
                lines.append(f"{holder}, hanged today, had the Grudge trait (R24): {victim} is dealt a Standard Attack "
                             "tonight, an Astral Visit (not a visit) that no role-block stops; code drew them. Resolve "
                             "it with the night's other attacks against their Defense (R3; protection applies). If it "
                             f"kills, cause '{GRUDGE_CAUSE}', by {holder}; if it fails, tell {victim} they were "
                             f"attacked by {GRUDGE_CAUSE}. Never say that {holder} had the trait.")
        return "\n- ".join(lines)


class Notorious(TraitLogic):
    night_note = ("Notorious (a trait; see each player's traits): every alignment check reads a Notorious player as "
                  "Evil (Sheriff: Evil; Seer: Evil), like a framed player (R19). The Census Taker's count still sees "
                  "their true alignment. Don't tell anyone a player is Notorious.")


class Zealot(TraitLogic):
    fixed_trial_vote = True


class Merciful(TraitLogic):
    fixed_trial_vote = False


SPARE_BLADE_USED = "spare_blade_used"  # game.role_state: Spare Blade holders who have used their extra Katana attack


class SpareBlade(OneShotAction):
    # Like Armed's shot (Kevin, Oct 13 2026: the simpler of the two designs), with the Katana's attack and cause.
    ops = {"spare_blade": ({"player", "by"}, set(),
                           "{op:'spare_blade', player, by}: the Spare Blade holder `by` makes their one extra Katana "
                           "attack on `player` (trait, R24); code marks it used. Resolve the Standard Attack yourself")}
    night_note = ("Spare Blade (a trait, R24): a Yakuza whose trait_actions has trait 'Spare Blade' makes one extra "
                  "Katana attack on its target, besides the Katana's own attack and whoever holds the Katana: "
                  "Standard (R8), an action and a visit by them (record it), and it counts as an attack everywhere "
                  "one does. A role-block stops it, and then it isn't used. Unless they were role-blocked, use the "
                  "spare_blade op (it marks it used, even if the attack fails) and resolve the attack: a kill's cause "
                  "is 'Katana', katana=true, by the user; a survivor is told they were attacked with the Katana, as "
                  "for the Katana's own attack. Tell the user only whether it killed. Never mention the trait to "
                  "anyone else.")
    action_task = ("You have the Spare Blade trait: you may make your one extra Katana attack tonight by adding "
                   "{trait: 'Spare Blade', target} to trait_actions, besides the Katana's own attack; leave "
                   "trait_actions empty to keep it.")
    trait, used_key = "Spare Blade", SPARE_BLADE_USED
    holder, used, no_self = ("a Spare Blade holder", "has already used their Spare Blade",
                             "a Spare Blade holder can't attack themselves")


class Stocked(TraitLogic):
    def on_dealt(self, game: Game, p: Player) -> None:
        for kind in p.tokens:  # rules R24: one more of each kind the role starts with
            p.tokens[kind] += 1


class Disguised(TraitLogic):
    def on_dealt(self, game: Game, p: Player) -> None:
        # A Village role on the game's script, never the holder's own nor the Roleplayer (whose checks show
        # "Roleplayer"); the game's RNG, so a seed deals the same disguise. Code-told checks read it through
        # roles.base.seen_role.
        from scripts import script_roles
        roles = [r for r in script_roles(game)
                 if ROLES[r].alignment is Alignment.GOOD and r not in (p.role, "Roleplayer")]
        if roles:
            disguise = game.role_state.setdefault(DISGUISES, {})[p.name] = game.rng.choice(roles)
            game.log.write("disguise", player=p.name, role=disguise)

    def detail(self, game: Game, p: Player) -> str:
        return f"Your disguise: {game.role_state.get(DISGUISES, {}).get(p.name, p.role)}."

    def tonight_note(self, game: Game) -> str:
        if not (disguises := game.role_state.get(DISGUISES)):
            return ""
        seen = "; ".join(f"{n} as {r}" for n, r in disguises.items())
        return ("Disguised (a trait, R24): every exact-role check (R18: e.g. an Oracle's or Ritualist's guess, a "
                f"Mortician's clean) sees these players as these Village roles, alive or dead: {seen}. Alignment "
                "checks still see their true alignment. Never reveal a true role behind a disguise.")


BONDS = "bonds"  # game.role_state: player -> the player they're bonded to (both ways)


class Bonded(TraitLogic):
    def on_dealt(self, game: Game, p: Player) -> None:
        # A random partner the trait fits who isn't bonded yet, among those with the fewest traits; the partner gets
        # the trait too.
        bonds = game.role_state.setdefault(BONDS, {})
        free = [q for q in game.players if q is not p and q.name not in bonds and eligible(q, "Bonded")]
        if not free:
            p.traits.remove("Bonded")
            game.log.error("setup_error", f"no player could be bonded to {p.name}, so the Bonded trait was left out")
            return
        fewest = min(len(q.traits) for q in free)  # drawn setups give a player at most setups.TRAITS_EACH
        partner = game.rng.choice([q for q in free if len(q.traits) == fewest])
        partner.traits.append("Bonded")
        bonds[p.name], bonds[partner.name] = partner.name, p.name
        game.log.write("bond", players=[p.name, partner.name])

    def detail(self, game: Game, p: Player) -> str:
        return f"You are bonded to {game.role_state.get(BONDS, {}).get(p.name)}."

    def on_death(self, game: Game, p: Player, guilty_voters: list[str] | None) -> None:
        # rules R24: at once, so the partner's death is revealed with it (at dawn for a night death, R10: a partner
        # who dies at night still acted). Not an attack by anyone: it sets off nothing that reacts to one.
        partner = game.role_state.get(BONDS, {}).get(p.name)
        if partner and game.player(partner).alive:
            game.log.write("heartbreak", player=partner, bonded=p.name, day=game.day)
            game.kill(partner, HEARTBREAK_CAUSE, by=p.name)


class Selfish(TraitLogic):
    win_needs_alive = True


class Selfless(TraitLogic):
    win_needs_alive = False


class Usurper(TraitLogic):
    takes_win = True


class Sleepwalker(TraitLogic):
    night_note = ("Sleepwalker (a trait, R24): code draws each Sleepwalker's random visit; it is in their "
                  "trait_actions as {trait: 'Sleepwalker', target, automatic: true}. It is a visit (R6): record it "
                  "with record_visits, and anything that sees or reacts to visits (Tracker, Lookout, Veteran, traps) "
                  "counts it. It does nothing else. A role-block stops it (no visit). Never tell the Sleepwalker whom "
                  "they visited.")

    def random_visit(self, game: Game, p: Player) -> str | None:
        others = [q.name for q in game.alive() if q is not p]
        return game.rng.choice(others) if others else None


class Turncoat(TraitLogic):
    wins_with = "Yakuza"
    night_note = ("Turncoat (a trait; see each player's traits): every alignment check reads a Turncoat as Evil "
                  "(Sheriff: Evil; Seer: Evil), like Notorious (R19). The Census Taker's count still sees their true "
                  "alignment (Good). Don't tell anyone a player is a Turncoat.")


def usurper(game: Game, faction: str) -> Player | None:
    """The faction's only living player, if they hold a trait that takes the win (Usurper), or None."""
    alive = [p for p in game.alive() if p.faction == faction]
    return alive[0] if len(alive) == 1 and any(trait_logic(t).takes_win for t in alive[0].traits) else None


def win_side(p: Player) -> str:
    """The faction p wins with (rules R1, R24): their own, unless a trait (Turncoat) names another."""
    return next((w for t in p.traits if (w := trait_logic(t).wins_with)), p.faction)


def ignored_at_end(p: Player) -> bool:
    """Whether the game's end ignores p, like a role that never blocks wins (Turncoat; rules R1, R24)."""
    return win_side(p) != p.faction


def win_blockers(game: Game, p: Player) -> list[str]:
    """The traits that keep p from sharing their faction's win (rules R1, R24): Selfish if p died or left, Selfless if
    p is alive, Usurper unless p is the faction's only living player."""
    return [t for t in p.traits if trait_logic(t).win_needs_alive not in (None, p.alive)
            or trait_logic(t).takes_win and usurper(game, p.faction) is not p]


def shares_win(game: Game, p: Player) -> bool:
    return not win_blockers(game, p)


class Oblivious(TraitLogic):
    def tonight_note(self, game: Game) -> str:
        if not (names := [p.name for p in game.alive() if "Oblivious" in p.traits]):
            return ""
        return (f"Oblivious (a hidden trait, R24): never tell {join_names(names)} about an attack they survive "
                "tonight (code tells a death as usual). Everything else about the attack is unchanged: protectors "
                "still learn they stopped it, the attacker still learns it failed. Never mention the trait.")


class Drowsy(TraitLogic):
    night_note = ("Drowsy (a trait, R24): code draws each night whether a Drowsy player is role-blocked; the line "
                  "below says what it drew tonight. Never roll or decide it yourself.")

    def tonight_note(self, game: Game) -> str:
        # Code draws each living holder's night (rules R24) with the game's RNG, so a seed replays it; the moderator
        # applies it like any role-block (R9).
        lines = []
        for p in game.alive():
            if "Drowsy" in p.traits and game.rng.random() < DROWSY_ODDS:
                game.log.write("drowsy", player=p.name, day=game.day)
                lines.append(f"{p.name} has the hidden Drowsy trait (R24) and is role-blocked tonight; code drew it. "
                             "Handle it exactly like a role-block (R9) with no blocker: their actions, automatic "
                             "effects and trait actions have no effect and spend no tokens, they make no visit, and "
                             "they are told they were role-blocked, as usual. Never mention the trait or say why.")
            elif "Drowsy" in p.traits:
                lines.append(f"{p.name} (Drowsy) is not role-blocked by the trait tonight; code drew it.")
        return "\n- ".join(lines)


class Paranoid(TraitLogic):
    # In game_20261013_045457_890072 the moderator, seeing the trait in the state, rolled for a Drowsy holder itself
    # on a night code hadn't drawn (and killed a player through it): say who isn't affected tonight too.
    night_note = ("Paranoid (a trait, R24): code draws each night whether a Paranoid player gets a fake attack; the "
                  "line below says what it drew tonight. Never roll or decide it yourself.")

    def tonight_note(self, game: Game) -> str:
        # Code draws the night and the cause with the game's RNG (a seed replays them); the moderator writes the
        # message, so it reads like its real ones (Kevin, Oct 13 2026: indistinguishable from a real attack).
        from scripts import script_roles
        lines, drawn = [], []
        for p in game.alive():
            if "Paranoid" not in p.traits or game.rng.random() >= PARANOID_ODDS:
                continue
            roles = [r for r in PARANOID_ATTACKERS if r in script_roles(game) and not ROLES[r].unique]
            cause = "the Katana" if not roles or game.rng.random() < PARANOID_KATANA else game.rng.choice(roles)
            game.log.write("paranoid", player=p.name, cause=cause, day=game.day)
            drawn.append(p.name)
            lines.append(f"{p.name} has the hidden Paranoid trait (R24); code drew a fake attack for tonight: unless "
                         f"{p.name} is really attacked tonight, tell them they were attacked by {cause} and "
                         "survived, worded exactly as you would tell a real defended attack (R3). It isn't an attack: "
                         "no visit, no kill, no protector or Bloodhound counts it, nobody else is told. Never mention "
                         "the trait or that it was fake.")
        spared = [p.name for p in game.alive() if "Paranoid" in p.traits and p.name not in drawn]
        if spared:
            lines.append(f"No fake attack tonight for {join_names(spared)} (Paranoid; code drew it): tell them of "
                         "attacks only as usual.")
        return "\n- ".join(lines)


class Shaky(TraitLogic):
    night_note = ("Shaky (a hidden trait, R24): every Katana attack a Shaky Yakuza makes (the Katana's own while they "
                  "hold it, or their Spare Blade attack) is level None (R3), so it never kills. Resolve it as an "
                  "attack that failed against Defense: it is still an action, an attack and a visit; the target is "
                  "told they were attacked with the Katana as usual, and a protector on the target is told their "
                  "protection stopped it (R17). The line below says who carries the Katana tonight. Never mention "
                  "the trait.")

    def tonight_note(self, game: Game) -> str:
        shaky = [p.name for p in game.alive() if "Shaky" in p.traits]
        if not shaky:
            return ""
        holder = game.katana_holder
        line = (f"Tonight the Katana is carried by {holder}, who is Shaky: the Katana's own attack tonight is level "
                "None and can't kill." if holder in shaky else
                f"Tonight the Katana is carried by {holder}, who isn't Shaky: resolve its attack as usual."
                if holder else "")
        return " ".join(filter(None, [line, f"Shaky (hidden): {join_names(shaky)}; a Spare Blade attack by any of "
                                            "them is level None too."]))

    def kill_error(self, game: Game, change: dict) -> str | None:
        # rules R3, R24: a level-None attack never kills. The Katana's attackers in the kill: the Yakuza named in
        # `by`, else the Katana's holder.
        if not (change.get("katana") or "katana" in str(change.get("cause", "")).lower()):  # the flag, or the cause
            return None
        by = change.get("by") or []
        users = [game.player(n) for n in ([by] if isinstance(by, str) else by)
                 if game.player(n).info.alignment is Alignment.EVIL]
        if not users and game.katana_holder:
            users = [game.player(game.katana_holder)]
        if users and all("Shaky" in u.traits for u in users):
            return (f"{join_names([u.name for u in users])} has the hidden Shaky trait (R24): their Katana attacks are "
                    "level None and never kill (R3). Leave the target alive and tell them they were attacked, as for "
                    "a failed attack; if another attack killed them, set katana=false and leave the Shaky player out "
                    "of by")
        return None


def kill_error(game: Game, change: dict) -> str | None:
    """Why a kill op can't apply as given (TraitLogic.kill_error), or None."""
    return next((e for t in LOGIC.values() if (e := t.kill_error(game, change))), None)


LOGIC: dict[str, TraitLogic] = {"Martyr": Martyr(), "Armed": Armed(), "Avenger": Avenger(), "Cursed": Cursed(),
                                "Kindred": Kindred(), "Remorseful": Remorseful(), "Faultline": Faultline(),
                                "Notorious": Notorious(),
                                "Grudge": Grudge(), "Loud": Loud(), "Curt": Curt(),
                                "Confidant": Confidant(), "Zealot": Zealot(), "Merciful": Merciful(),
                                "Drowsy": Drowsy(), "Spare Blade": SpareBlade(),
                                "Paranoid": Paranoid(), "Stocked": Stocked(),
                                "Disguised": Disguised(), "Bonded": Bonded(), "Selfish": Selfish(),
                                "Selfless": Selfless(), "Usurper": Usurper(), "Oblivious": Oblivious(),
                                "Shaky": Shaky(), "Turncoat": Turncoat(),
                                "Sleepwalker": Sleepwalker()}
assert set(LOGIC) == set(TRAITS)


def trait_logic(name: str) -> TraitLogic:
    return LOGIC[name]


ACTION_TRAITS = [t for t, lg in LOGIC.items() if lg.ops]  # traits with a night action (players.trait_actions_schema)


def eligible(p: Player, trait: str) -> bool:
    # A player may have several traits, never the same one twice (Kevin, Oct 12 2026), nor two that exclude each other.
    return fits(trait, p.role) and not bundle_error([*p.traits, trait])


def fits(trait: str, role: str) -> bool:
    """Whether a player of this role can get the trait (its alignments, and fits_role)."""
    info = TRAITS[trait]
    return ROLES[role].alignment in info.alignments and (info.fits_role is None or info.fits_role(role))


def bundle_error(bundle: list[str]) -> str | None:
    """Why one player can't hold all these traits together (rules R24), or None."""
    if len(set(bundle)) < len(bundle):
        return "a player holds a trait at most once"
    if clash := next((e for e in EXCLUSIVE if e <= set(bundle)), None):
        return f"no player holds both {' and '.join(sorted(clash))}"
    return None


def fixed_trial_vote(p: Player) -> tuple[str, bool] | None:
    """The trait that fixes how p's trial votes count (Zealot, Merciful) and how they count, or None."""
    for t in p.traits:
        if (vote := trait_logic(t).fixed_trial_vote) is not None:
            return t, vote
    return None


FACTIONS = {"Village": Alignment.GOOD, "Yakuza": Alignment.EVIL, "Neutral": Alignment.NEUTRAL}


def parse_item(item: str) -> tuple[list[str], Alignment | None]:
    """A --traits item or a drawn one: "Martyr", "Martyr+Armed" (one player gets both) or "Grudge@Yakuza" (dealt to
    a Yakuza player). Raises ValueError for an unknown faction."""
    names, _, faction = item.partition("@")
    if faction and faction not in FACTIONS:
        raise ValueError(f"unknown faction {faction!r} in {item!r} (known: {', '.join(FACTIONS)})")
    return names.split("+"), FACTIONS.get(faction)


def power_key(trait: str, alignment: Alignment) -> str:
    """The name a trait's power has for a holder of this alignment (role_power fits one power per key): the trait's
    own name, or "Grudge@Yakuza" where power_for gives that alignment its own power."""
    if alignment in (TRAITS[trait].power_for or {}):
        return f"{trait}@{next(f for f, a in FACTIONS.items() if a is alignment)}"
    return trait


def hand_powers() -> dict[str, float]:
    """Each power_key's hand-set power (TraitInfo.power and power_for): role_power's priors for traits."""
    out: dict[str, float] = {}
    for t, info in TRAITS.items():
        out[t] = info.power
        for a, power in (info.power_for or {}).items():
            out[power_key(t, a)] = power
    return out


def village_sign(alignment: Alignment) -> int:
    """How a trait's power counts towards the Village: +1 for a Village holder, -1 for a Yakuza (it helps the
    holder's side), 0 for a Neutral (who plays for itself)."""
    return {Alignment.GOOD: 1, Alignment.EVIL: -1}.get(alignment, 0)


def village_power(trait: str, alignment: Alignment, powers: dict[str, float] | None = None) -> float:
    """What a trait held by a player of this alignment adds to the Village's side (role_power.score, which
    setups.draw_traits balances with): its power (from `powers`, role_power's fit, by power_key, else hand-set) for a
    Village holder, minus it for a Yakuza; a Neutral plays for itself, so 0."""
    key = power_key(trait, alignment)
    power = (powers or {}).get(key, hand_powers()[key])
    return village_sign(alignment) * power


def night_traits(game: Game, p: Player) -> list[str]:
    """p's traits whose night action p may use tonight."""
    return [t for t in p.traits if trait_logic(t).can_act(game, p)]


def briefing(game: Game, p: Player) -> list[str]:
    return [f"Your trait: {t}. {TRAITS[t].summary}" + (f" {d}" if (d := trait_logic(t).detail(game, p)) else "")
            for t in p.traits if not TRAITS[t].hidden]
