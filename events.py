"""Event categories. Every Game.emit() names one, and the log viewer colors and labels events by it
(never by parsing their text), so event wording can change freely."""

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
