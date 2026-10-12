"""Reading finished (or stopped) games from their JSONL logs, for the tools that analyze many games (stats.py,
game_index.py, tips.py, log_viewer.py): which files in a folder are game logs, the setup and result records,
and each player as one dict whatever the log's LOG_VERSION. Shims for older log versions live here and
nowhere else, so a tool reading logs never needs its own."""

from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from llm import Model, model_tier
from roles import Alignment, log_role, role_info

NOT_GAMES = {"mock_lessons.jsonl"}  # matches mock_*.jsonl but holds mock games' lessons, not a game
SHORT = {m.value: m.short for m in Model}
MIX_SHARE = 2 / 3  # a game is "frontier" (or "mid", "cheap") when at least this share of its seats are


# --- which files are game logs -------------------------------------------------------------------

def folder_logs(folder: Path, include_mock: bool = True) -> list[Path]:
    """The folder's game logs (game_*.jsonl, and mock_*.jsonl unless include_mock is False), sorted by name.
    A missing folder has none."""
    patterns = ["game_*.jsonl", *(["mock_*.jsonl"] if include_mock else [])]
    return sorted(f for pat in patterns for f in folder.glob(pat) if f.name not in NOT_GAMES)


def log_files(paths: Iterable[Path], include_mock: bool = True) -> list[Path]:
    """Game logs from folders (folder_logs) and .jsonl files named directly; anything else stops the program."""
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            out += folder_logs(p, include_mock)
        elif p.suffix == ".jsonl" and p.exists():
            out.append(p)
        else:
            raise SystemExit(f"{p} is not a folder or a .jsonl game log")
    return out


# --- records ---------------------------------------------------------------------------------------

def first(records: list[dict], kind: str) -> dict | None:
    return next((r for r in records if r.get("kind") == kind), None)


def last(records: list[dict], kind: str) -> dict | None:
    return next((r for r in reversed(records) if r.get("kind") == kind), None)


def setup_of(records: list[dict]) -> dict | None:
    """The "setup" record; None means the file isn't a game log."""
    return first(records, "setup")


def result_of(records: list[dict]) -> dict | None:
    """The "result" record; None means the game stopped or crashed before it ended."""
    return last(records, "result")


def fallback_counts(records: list[dict]) -> Counter:
    """Player -> how many of their turns fell back to the default answer."""
    fallbacks = Counter(r.get("player") for r in records if r.get("kind") == "player_fallback")
    if not fallbacks:  # older logs had no player_fallback record: a failed second (last) attempt was one
        fallbacks = Counter(r.get("player") for r in records
                            if r.get("kind") == "player_error" and r.get("attempt") == 1)
    return fallbacks


def effort_fallback_counts(records: list[dict]) -> Counter:
    """Player -> how many of their answers were cut off at max_tokens and retried one effort step lower
    (log version 35 on; older logs show it only as player_call's effort)."""
    return Counter(r.get("player") for r in records if r.get("kind") == "effort_fallback")


def players(records: list[dict], setup: dict | None = None, result: dict | None = None) -> list[dict]:
    """Each player of the game in seat order: name, seat, model (full id), start_role, final_role (None
    while the game hasn't ended), faction (of the start role, by faction_of), won, alive, died (a "death"
    record names them: unlike alive, a player who left the game, e.g. an Executioner who won, didn't die)
    tips (played with a tips sheet), traits (traits.py; [] before log version 48), unreliable (their calls kept
    failing, players.count_fallback; False before log version 63)
    and via (how the model's calls ran: api, claude_code or mock; logs before
    version 47 are api, or mock in mock games). setup and result default to the log's own records."""
    setup = setup or setup_of(records) or {}
    result = result or result_of(records) or {}
    seats = {p.get("name"): p for p in setup.get("players") or []}
    version = setup.get("log_version", 1)
    described = setup.get("role_info") or {}  # log version 51 on: the roles as this game had them
    deaths = {r.get("player") for r in records if r.get("kind") == "death"}
    tips_record = first(records, "tips") or {}
    settings = setup.get("settings") or {}
    default_via = "mock" if settings.get("mock") else "api"

    def player(i: int, name: str, model: str | None, start_role: str | None, final_role: str | None,
               won: bool, alive: bool | None, tips: bool, via: str | None = None, unreliable: bool = False) -> dict:
        seat = seats.get(name) or {}
        start = log_role(start_role or seat.get("role") or final_role or "?", version)
        final = log_role(final_role, version) if final_role else None
        faction = faction_of(start, described)
        return {"name": name, "seat": seat.get("seat", i), "model": model or seat.get("model") or "?",
                "start_role": start, "final_role": final, "faction": faction, "won": won,
                "alive": name not in deaths if alive is None else alive, "died": name in deaths, "tips": tips,
                "traits": seat.get("traits") or [],  # log version 48 (traits.py)
                "unreliable": unreliable,
                "via": via or seat.get("via") or (  # the first --claude-code games (version 46) have only the setting
                    "claude_code" if settings.get("claude_code") and (model or seat.get("model") or "").startswith(
                        "anthropic/") else default_via)}

    if "players" in result:
        return [player(i, p["name"], p.get("model"), p.get("start_role"), p.get("final_role"), bool(p.get("won")),
                       p.get("alive"), bool(p.get("tips")), p.get("via"),  # a result without "tips": nobody had tips
                       bool(p.get("unreliable")))
                for i, p in enumerate(result["players"])]
    tips_players = tips_record.get("players") or []
    if "roles" in result:  # log versions before 3: the result has roles, models and winners by name
        winners = set(result.get("winners") or [])
        return [player(i, n, (result.get("models") or {}).get(n), None, role, n in winners, None, n in tips_players)
                for i, (n, role) in enumerate(result["roles"].items())]
    return [player(i, n, None, None, None, False, None, n in tips_players) for i, n in enumerate(seats)]


# --- roles and models --------------------------------------------------------------------------------

def faction_of(role: str, described: dict[str, dict] | None = None) -> str:
    """Village, Yakuza or Neutral, by the role's alignment. A role this code doesn't know (renamed or
    removed since the log was written) counts as Neutral, so stats.py doesn't score decisions about it."""
    if described and role in described:  # the log's own description (setup role_info, log version 51 on)
        return {"Good": "Village", "Evil": "Yakuza"}.get(described[role]["alignment"], "Neutral")
    info = role_info(role)  # a retired role by its log_role label too
    alignment = info.alignment if info else None
    return {Alignment.GOOD: "Village", Alignment.EVIL: "Yakuza"}.get(alignment, "Neutral")  # type: ignore[arg-type]


def short(model: str) -> str:
    """A model's short name (e.g. haiku-5.5), or the last part of an id llm.py doesn't know."""
    return SHORT.get(model, model.split("/")[-1])


def model_id(name: str) -> str:
    """A model's full id from its short name or id; anything else is returned as given."""
    return next((m.value for m in Model if name in (m.value, m.short)), name)


def mix_of(seat_models: list[str]) -> tuple[float, str]:
    """(share of seats played by frontier models, the game's mix label: a tier, or "mixed")."""
    if not seat_models:
        return 0.0, "mixed"
    tiers = Counter(model_tier(m) for m in seat_models)
    share = tiers["frontier"] / len(seat_models)
    top, n = tiers.most_common(1)[0]
    return round(share, 3), top if n / len(seat_models) >= MIX_SHARE else "mixed"
