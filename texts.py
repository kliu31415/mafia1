"""Plain-text views of game data shared by the game, the log viewer and the feedback steps, so that game code
(players.py) needn't import the viewer or the tips builder: a night action as a line, and a tips file as players
see it."""


def moved(a: dict, key: str) -> str:
    """The action's target in `key`, with where a swap (rules R23) moved it: "Olivia (swapped to Erin)". Players
    read the after-game replay as their choices otherwise and reported the moved ones as wrong (Night 3 of
    game_20261011_225511_1253)."""
    chosen = a.get(f"chosen_{key}")
    return f"{chosen} (swapped to {a[key]})" if chosen and chosen != a[key] else str(a[key])


def describe_action(a: dict) -> str:
    if a.get("automatic"):  # drawn by code: the Ex-Con's random visit, in logs before v70 (roles.RETIRED)
        return f"automatic: {describe_action({**a, 'automatic': False})}"
    shots = [f"{t['trait']} on {moved(t, 'target')}" for t in a.get("trait_actions") or []]  # rules R24
    if not a.get("act") and not a.get("katana_vote_holder") and not shots:
        return "no action"
    parts = []
    if "act" not in a:
        pass  # a role with no night action, asked only for a trait's
    elif a.get("act"):
        for key, label in (("target", "target"), ("second_target", "second target"), ("guessed_role", "named role")):
            if a.get(key):
                parts.append(f"{label} {moved(a, key)}")
        if a.get("tokens_to_spend"):  # what they chose; a role-block spends none (R9)
            parts.append(f"chose to spend {a['tokens_to_spend']} token(s)")
        if a.get("details"):
            parts.append(f'"{a["details"]}"')
    else:
        parts.append("no role action")
    if a.get("katana_vote_holder"):
        target = moved(a, "katana_vote_target") if a.get("katana_vote_target") else None
        parts.append(f"Katana vote: {a['katana_vote_holder']} holds, attacks {target}")
    parts += [f"trait action: {s}" for s in shots]
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
