"""Plain-text views of game data shared by the game, the log viewer and the feedback steps, so that game code
(players.py) needn't import the viewer or the tips builder: a night action as a line, and a tips file as players
see it."""


def describe_action(a: dict) -> str:
    if a.get("automatic"):  # drawn by code, e.g. the Ex-Con's random visit (RoleLogic.automatic_action)
        return f"automatic: {describe_action({**a, 'automatic': False})}"
    if not a.get("act") and not a.get("katana_vote_holder"):
        return "no action"
    parts = []
    if a.get("act"):
        for key in ("target", "second_target", "guessed_role"):
            if a.get(key):
                parts.append(f"{key.replace('_', ' ')} {a[key]}")
        if a.get("tokens_to_spend"):
            parts.append(f"{a['tokens_to_spend']} token(s)")
        if a.get("details"):
            parts.append(f'"{a["details"]}"')
    else:
        parts.append("no role action")
    if a.get("katana_vote_holder"):
        parts.append(f"Katana vote: {a['katana_vote_holder']} holds, attacks {a.get('katana_vote_target')}")
    return "; ".join(parts)


def sections(text: str) -> dict[str, str]:
    """Heading -> body for each `## ` section; text before the first one is dropped."""
    out: dict[str, str] = {}
    heading = None
    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            out.setdefault(heading, "")
        elif heading is not None:
            out[heading] += line + "\n"
    return {h: body.strip() for h, body in out.items() if body.strip()}


def player_view(text: str) -> str:
    """What players see of a tips file: every section, without the preamble."""
    return "\n\n".join(f"## {h}\n{body}" for h, body in sections(text).items())


def blank(text: str) -> bool:
    """An answer meaning "nothing": "" or a written-out null (Haiku wrote "null" as feedback 27 times in
    game_20261009_152339_529912, since the shared schema types text fields as plain strings). Stray punctuation
    around it counts too: Luna wrote ":null" as its claim and will in game_20261010_090539_3006, meaning "keep"."""
    return text.strip().strip(".:;,'\"` ").lower() in ("", "null", "none", "n/a")
