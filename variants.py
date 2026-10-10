"""Rule settings: game options that change a rule from rules_1.txt, and the note each one adds after the rules
text so every prompt (players, moderator, night judge, tips) plays by them.

    flips             what a death reveals (rules R12): "role", "alignment" (Good, Evil or Neutral) or "none"
    trial_votes       "public" (rules R4: every Guilty/Innocent vote is revealed) or "secret" (only the totals)
    nomination_votes  "public" (rules R4: every Yes/No vote is revealed) or "secret" (only the nominator and the
                      Yes count)

The defaults hide as much as possible (Kevin, Oct 10 2026: less mechanical deduction, more social). Logs from
before these settings existed played with LEGACY (rules_1.txt as written). A player whose win ends their part in
the game (a hanged Jester, an Executioner who leaves) is still revealed: the win announcement names their role.
"""

SETTINGS: dict[str, tuple[str, ...]] = {
    "flips": ("none", "alignment", "role"),
    "trial_votes": ("secret", "public"),
    "nomination_votes": ("secret", "public"),
}
DEFAULTS = {name: choices[0] for name, choices in SETTINGS.items()}
LEGACY = {"flips": "role", "trial_votes": "public", "nomination_votes": "public"}  # rules_1.txt as written

_NOTES = {
    ("flips", "alignment"): "R12: when someone dies, only their alignment (Good, Evil or Neutral) is revealed, not "
                            "their role. It is their true alignment: frames and disguises (e.g. the Ex-Con's, or the "
                            "Katana holder's) don't change it. Their cause of death and last will are still "
                            "revealed, and a Mortician's clean hides the alignment and the will.",
    ("flips", "none"): "R12: when someone dies, neither their role nor their alignment is revealed. Only their cause "
                       "of death and last will are, and a Mortician's clean hides the will.",
    ("trial_votes", "secret"): "R4: trial votes are secret. Only the Guilty and Innocent totals are announced, never "
                               "who voted which way (wherever the rules say votes are revealed, e.g. for the "
                               "Ballot Stuffer, only the totals are). Each voter is privately reminded of their own "
                               "vote.",
    ("nomination_votes", "secret"): "R4: nomination votes are secret. The nominator is named, but only the number "
                                    "of Yes votes is announced, never who voted Yes or No. Each voter is privately "
                                    "reminded of their own vote.",
}


def full(settings: dict | None) -> dict[str, str]:
    """Every rule setting, from a log's or config's settings: a missing one is LEGACY's (older logs)."""
    settings = settings or {}
    return {name: settings.get(name, LEGACY[name]) for name in SETTINGS}


def rules_notes(settings: dict[str, str]) -> str:
    """The text added after rules_1.txt for these settings ("" for rules_1.txt as written)."""
    notes = [_NOTES[k, v] for k, v in settings.items() if (k, v) in _NOTES]
    if not notes:
        return ""
    return ("\n\n---\n\nGame settings for this game. They replace the parts of the rules named below; everything "
            "else in the rules stays as written. A player whose win ends their part in the game (a hanged Jester, an "
            "Executioner who leaves) is still revealed.\n" + "\n".join(f"- {n}" for n in notes))


def describe(settings: dict[str, str]) -> str:
    """A short description, e.g. for the tips model: 'deaths reveal nothing; secret trial votes; ...'."""
    flips = {"role": "deaths reveal the role", "alignment": "deaths reveal only the alignment",
             "none": "deaths reveal neither role nor alignment"}[settings["flips"]]
    return (f"{flips}; {settings['trial_votes']} trial votes; {settings['nomination_votes']} nomination votes "
            "(the nominator is always named)")


def moderator_note(settings: dict[str, str]) -> str:
    """The moderator's reminder of what these settings hide ("" for rules_1.txt as written)."""
    flips = {"none": "a dead player's role or alignment", "alignment": "a dead player's role"}.get(settings["flips"])
    hidden = [flips] if flips else []
    if "secret" in (settings["trial_votes"], settings["nomination_votes"]):
        hidden.append("how any player voted" if settings["trial_votes"] == settings["nomination_votes"] else
                      f"how any player voted in {'trials' if settings['trial_votes'] == 'secret' else 'nominations'}")
    if not hidden:
        return ""
    return (" This game's settings (after the rules) hide more than the rules as written: in everything you write "
            f"(announcements, private results, notes), never reveal {' or '.join(hidden)}, even after the game "
            "has moved on. A private result still says what the rules say its recipient learns (e.g. an "
            "investigator's result on a living player).")
