"""Rule settings: game options that change a rule from rules_1.txt, and the note each one adds after the rules
text so every prompt (players, moderator, night judge, tips) plays by them.

    flips             what a death reveals (rules R12): "none" (cause and will only), "alignment" (Good, Evil or
                      Neutral too) or "role"
    trial_votes       "secret" (rules R4: only the Guilty and Innocent totals) or "public" (every vote is revealed)
    nomination_votes  "secret" (rules R4: only the nominator and the Yes count) or "public" (every vote is revealed)

rules_1.txt describes the game with the defaults (DEFAULTS: no role or alignment on death, secret votes), which hide
as much as possible (Kevin, Oct 10 2026: less mechanical deduction, more social), so the defaults add no note; the
other choices add one. Logs from before these settings existed played with LEGACY (role flips, public votes), and
were played under the rules text of their git commit, which described LEGACY. A player whose win ends their part in
the game (a hanged Jester, an Executioner who leaves) is revealed under every setting: the win announcement names
their role.
"""

SETTINGS: dict[str, tuple[str, ...]] = {
    "flips": ("none", "alignment", "role"),
    "trial_votes": ("secret", "public"),
    "nomination_votes": ("secret", "public"),
}
DEFAULTS = {name: choices[0] for name, choices in SETTINGS.items()}
LEGACY = {"flips": "role", "trial_votes": "public", "nomination_votes": "public"}  # rules_1.txt before Oct 10 2026

_NOTES = {
    ("flips", "alignment"): "R12: when someone dies, their alignment (Good, Evil or Neutral) is revealed too, but not "
                            "their role. It is their true alignment: frames and disguises (e.g. Notorious, or the "
                            "Katana holder's) don't change it. A Mortician's clean hides the alignment as well as the "
                            "will.",
    ("flips", "role"): "R12: when someone dies, their role is revealed too (which also shows their alignment). A "
                       "Mortician's clean hides the role as well as the will.",
    ("trial_votes", "public"): "R4: trial votes are public. Once all votes are in, every player's Guilty or Innocent "
                               "vote is revealed, not only the totals (a Ballot Stuffer's extra vote is still counted "
                               "in the totals without saying whose it is).",
    ("nomination_votes", "public"): "R4: nomination votes are public. Once all votes are in, every player's Yes or No "
                                    "vote is revealed, not only the number of Yes votes.",
}


def full(settings: dict | None) -> dict[str, str]:
    """Every rule setting, from a log's or config's settings: a missing one is LEGACY's (older logs)."""
    settings = settings or {}
    return {name: settings.get(name, LEGACY[name]) for name in SETTINGS}


def rules_notes(settings: dict[str, str]) -> str:
    """The text added after rules_1.txt for these settings ("" for the defaults, which rules_1.txt describes)."""
    notes = [_NOTES[k, v] for k, v in settings.items() if (k, v) in _NOTES]
    if not notes:
        return ""
    return ("\n\n---\n\nGame settings for this game. They replace the parts of the rules named below; everything "
            "else in the rules stays as written. The rules are written for the default settings: where a detail "
            "elsewhere doesn't fit these (e.g. a role says nobody learns a vote that is public here), these settings "
            "win.\n" + "\n".join(f"- {n}" for n in notes))


def describe(settings: dict[str, str]) -> str:
    """A short description, e.g. for the tips model: 'deaths reveal nothing; secret trial votes; ...'."""
    flips = {"role": "deaths reveal the role", "alignment": "deaths reveal only the alignment",
             "none": "deaths reveal neither role nor alignment"}[settings["flips"]]
    return (f"{flips}; {settings['trial_votes']} trial votes; {settings['nomination_votes']} nomination votes "
            "(the nominator is always named)")


def moderator_note(settings: dict[str, str]) -> str:
    """The moderator's reminder of what these settings hide ("" when they hide nothing, e.g. LEGACY)."""
    flips = {"none": "a dead player's role or alignment", "alignment": "a dead player's role"}.get(settings["flips"])
    hidden = [flips] if flips else []
    if "secret" in (settings["trial_votes"], settings["nomination_votes"]):
        hidden.append("how any player voted" if settings["trial_votes"] == settings["nomination_votes"] else
                      f"how any player voted in {'trials' if settings['trial_votes'] == 'secret' else 'nominations'}")
    if not hidden:
        return ""
    return (" This game hides information (rules R4 and R12, and any game settings after the rules): in "
            "everything you write (announcements, private results, notes), never reveal "
            f"{' or '.join(hidden)}, even after the game has moved on. A private result still says what the rules "
            "say its recipient learns (e.g. an investigator's result on a living player).")
