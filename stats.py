"""Statistics across game logs: win rates by faction, model and role, how each role's presence moves
the Village's win rate, and per-decision skill (did a vote, nomination or night action help the
player's own faction?).

Usage:
    uv run stats.py                         # every finished live game in logs/
    uv run stats.py logs/a.jsonl logs/b     # chosen logs or folders
    uv run stats.py --decisions-by role     # decision skill per role instead of per model
    uv run stats.py --setup random          # only games with random setups (--roles random:N)
    uv run stats.py --csv out/              # games.csv, players.csv, decisions.csv for your own analysis
    uv run stats.py --mix frontier          # the game index's filters (game_index.py): --model, --min-frontier,
                                            # --mix, --moderator, --role, --winner, --players, --since, --until
    uv run stats.py --min-frontier 0.7 --list   # the games that pass, instead of the stats

Percentages come with a 95% Wilson interval in brackets: with few games the true rate can be anywhere
in it. Games without a "result" record (stopped or crashed) are skipped; mock games only with
--include-mock.

Decisions are scored from the player's faction's point of view, using the true roles:
    nomination        a nomination of a player the faction wants dead (Village: Yakuza or a Neutral that
                      blocks wins; Yakuza: a Village player). Prosecutions don't count (random nominator).
    nomination_vote   Yes on a player the faction wants dead, No otherwise (not the nominator or nominee)
    trial_vote        Guilty on a player the faction wants dead, Innocent otherwise (not the accused)
    deceived_voter    a Yakuza player on trial: one per Village vote, good if it was Innocent
    sheriff_check     the Sheriff checked a player the Village wants dead
    medic_protect     the Medic protected a player who was attacked that night
    vigilante_shot    the Vigilante shot a player the Village wants dead
    katana_target     a Yakuza voted for the Katana target that was attacked, and it was a Village power
                      role (Investigative, Combat or Misc)
A Jester counts as not wanted dead by the Village (hanging it is its win); an Executioner as neither,
so votes on it aren't scored. Neutral players' own decisions aren't scored. Vote records exist from
log version 2 and night_actions from early on; older logs count only toward win rates.
These are measures of choices, not of luck: a good decision can still lose the game.
"""

import argparse
import csv
import math
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

import game_index
from gamelogs import faction_of, log_files, mix_of, result_of, setup_of, short
from gamelogs import players as game_players
from records import read_records
from roles import ROLES, Alignment, logic

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
ATTACKERS = {"Vigilante", "Serial Killer", "Ritualist"}  # night actions that attack their target
POWER_CATEGORIES = {"Investigative", "Combat", "Misc"}
DECISION_ORDER = ["nomination", "nomination_vote", "trial_vote", "deceived_voter", "sheriff_check",
                  "medic_protect", "vigilante_shot", "katana_target"]


def wants_dead(faction: str, role: str) -> bool | None:
    """Whether a player of this faction should want a player with this role dead (hanged or shot);
    None when it's unclear, and then the decision isn't scored."""
    target = faction_of(role)
    if faction == "Yakuza":
        return {"Village": True, "Yakuza": False}.get(target)
    if faction != "Village":
        return None
    if target != "Neutral":
        return target == "Yakuza"
    if role == "Jester":
        return False  # hanging a Jester is its win, and its revenge kills a Guilty voter
    return True if logic(role).blocks_win else None  # blocks the Village's win (Serial Killer, Arsonist)


# --- reading logs ------------------------------------------------------------------------------

def load_game(path: Path) -> dict | None:
    """One finished game's summary, players and scored decisions, or None if it has no result."""
    records, _ = read_records(path)  # a half-written last line (a killed game) is skipped
    setup, result = setup_of(records), result_of(records)
    if setup is None or result is None:  # stopped or crashed, or not a game log (e.g. mock_lessons.jsonl)
        return None
    settings = setup.get("settings") or {}
    game_id = setup.get("game_id") or path.stem
    seated = game_players(records, setup, result)
    players = [{"name": p["name"], "model": short(p["model"]), "role": p["start_role"], "faction": p["faction"],
                "won": p["won"], "alive": p["alive"]} for p in seated]
    winning = result.get("winning_faction")
    if "winning_faction" not in result:
        factions = {p["faction"] for p in players if p["won"]} & {"Village", "Yakuza"}
        winning = next(iter(factions), None)
    by_name = {p["name"]: p for p in players}
    seat_models = [p["model"] for p in seated]
    frontier_share, mix = mix_of(seat_models)
    game = {"game": game_id, "file": path.name, "date": game_id.split("_")[1] if "_" in game_id else "",
            "log_version": setup.get("log_version", 1), "mock": bool(settings.get("mock")),
            "setup": (settings.get("setup") or {}).get("kind", "fixed"), "players": players,
            "n_players": len(players), "days": result.get("days"), "winning_faction": winning,
            "end_reason": result.get("end_reason", "win" if winning else None),
            "cost": round(sum((result.get("cost") or {}).values()), 4), "duration_s": result.get("duration_s"),
            "roles": sorted(p["role"] for p in players), "has_votes": any(r["kind"] == "vote" for r in records),
            # the fields game_index.matches filters on
            "models": seat_models, "frontier_share": frontier_share, "mix": mix,
            "moderator": settings.get("moderator", ""), "winner": winning}
    game["decisions"] = [{"game": game_id, **d, "model": by_name[d["player"]]["model"]}
                         for d in decisions(records, by_name) if d["player"] in by_name]
    return game


def decisions(records: list[dict], players: dict[str, dict]) -> list[dict]:
    """Scored decisions (see the module docstring): player, role, faction, kind, day, target,
    target_role, good."""
    out = []

    def add(player: str, kind: str, day: int, target: str, good: bool, role: str | None = None) -> None:
        p = players[player]
        out.append({"player": player, "role": role or p["role"], "faction": p["faction"], "kind": kind, "day": day,
                    "target": target, "target_role": players[target]["role"], "good": good})

    katana = {r["day"]: (r.get("result") or {}).get("attack") for r in records if r["kind"] == "katana"}
    revotes = {r["day"]: r["revote_targets"] for r in records if r["kind"] == "katana" and r.get("revote_targets")}
    for r in records:
        if r["kind"] == "vote" and r["nominee"] in players:
            nominee, day = r["nominee"], r["day"]
            nominee_role = players[nominee]["role"]
            if r["stage"] == "nomination" and not r.get("prosecuted") and r["nominator"] in players:
                want = wants_dead(players[r["nominator"]]["faction"], nominee_role)
                if want is not None and r["nominator"] != nominee:
                    add(r["nominator"], "nomination", day, nominee, want)
            for voter, vote in r["votes"].items():
                if voter == nominee or voter not in players:
                    continue
                if r["stage"] == "nomination" and voter == r["nominator"]:
                    continue  # votes Yes automatically
                want = wants_dead(players[voter]["faction"], nominee_role)
                if want is not None:
                    add(voter, f"{r['stage']}_vote", day, nominee, vote == want)
                if (r["stage"] == "trial" and players[nominee]["faction"] == "Yakuza"
                        and players[voter]["faction"] == "Village"):
                    add(nominee, "deceived_voter", day, voter, not vote)
        elif r["kind"] == "night_actions":
            day, actions, roles = r["day"], r["actions"], r.get("roles") or {}
            attacked = {katana.get(day)} | {a.get("target") for n, a in actions.items()
                                           if roles.get(n) in ATTACKERS and a.get("act")}
            for name, a in actions.items():
                role, target = roles.get(name), a.get("target")
                if name not in players or not a.get("act") or target not in players or target == name:
                    continue
                want = wants_dead("Village", players[target]["role"])
                if role == "Sheriff" and want is not None:
                    add(name, "sheriff_check", day, target, want, role)
                elif role == "Medic":
                    add(name, "medic_protect", day, target, target in attacked, role)
                elif role == "Vigilante" and want is not None:
                    add(name, "vigilante_shot", day, target, want, role)
            target = katana.get(day)
            if target in players:
                info = ROLES.get(players[target]["role"])
                power = bool(info and info.alignment is Alignment.GOOD and info.category in POWER_CATEGORIES)
                votes = revotes.get(day) or {n: a.get("katana_vote_target") for n, a in actions.items()}
                for name, vote in votes.items():
                    if name in players and vote == target:
                        add(name, "katana_target", day, target, power, roles.get(name))
    return out


# --- numbers and tables ------------------------------------------------------------------------

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def rate(k: int, n: int) -> str:
    """e.g. "45% [23-68] n=11", or "-" with no data."""
    if n == 0:
        return "-"
    lo, hi = wilson(k, n)
    return f"{100 * k / n:.0f}% [{100 * lo:.0f}-{100 * hi:.0f}] n={n}"


def table(header: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(str(x)) for x in col) for col in zip(header, *rows)]
    line = lambda cells: "  ".join(str(c).ljust(w) for c, w in zip(cells, widths)).rstrip()  # noqa: E731
    return "\n".join([line(header), line(["-" * w for w in widths])] + [line(r) for r in rows])


def report(games: list[dict], skipped: dict[str, int], decisions_by: str = "model") -> str:
    skip = ", ".join(f"{n} {why}" for why, n in skipped.items() if n)
    if not games:
        return "No finished games found." + (f" Skipped: {skip}." if skip else "")
    out = []
    versions = sorted({g["log_version"] for g in games})
    dates = sorted(g["date"] for g in games if g["date"])
    out.append(f"{len(games)} games ({dates[0] if dates else '?'} to {dates[-1] if dates else '?'}; log versions "
               f"{versions[0]}-{versions[-1]}; {sum(g['setup'] == 'random' for g in games)} with random setups)"
               + (f". Skipped: {skip}." if skip else "."))
    n = len(games)
    out.append("")
    out.append(table(["Winner", "Games"], [
        [f, rate(sum(g["winning_faction"] == f for g in games), n)] for f in ("Village", "Yakuza")]
        + [["none (Neutrals, stall, day limit)", rate(sum(g["winning_faction"] is None for g in games), n)]]))
    reasons: dict[str, int] = defaultdict(int)
    for g in games:
        reasons[g["end_reason"] or "?"] += 1
    known = lambda key: [g[key] for g in games if g[key] is not None]  # noqa: E731
    avg = lambda xs: sum(xs) / len(xs) if xs else 0  # noqa: E731
    out.append(f"End reasons: {', '.join(f'{k} {v}' for k, v in sorted(reasons.items()))}. Average "
               f"{avg(known('n_players')):.1f} players, {avg(known('days')):.1f} days, ${avg(known('cost')):.2f}"
               + (f", {avg(known('duration_s')) / 60:.0f} min" if known("duration_s") else "") + " per game.")

    players = [p for g in games for p in g["players"]]
    models = sorted({p["model"] for p in players})
    out.append("\nWin rate by model and faction (each player's starting faction)")
    rows = []
    for m in models:
        mine = [p for p in players if p["model"] == m]
        rows.append([m] + [rate(sum(p["won"] for p in mine if p["faction"] == f), sum(p["faction"] == f for p in mine))
                           for f in ("Village", "Yakuza", "Neutral")] + [rate(sum(p["won"] for p in mine), len(mine))])
    out.append(table(["Model", "Village", "Yakuza", "Neutral", "All"], rows))

    out.append("\nWin and survival rate by starting role")
    rows = []
    for role in sorted({p["role"] for p in players}, key=lambda r: (faction_of(r), r)):
        mine = [p for p in players if p["role"] == role]
        rows.append([role, faction_of(role), rate(sum(p["won"] for p in mine), len(mine)),
                     rate(sum(p["alive"] for p in mine), len(mine))])
    out.append(table(["Role", "Faction", "Won", "Survived"], rows))

    out.append("\nRole presence: the Village's win rate in games with and without each role. Only meaningful "
               "across varied setups (--roles random:N); with one fixed setup every game has the same roles.")
    rows = []
    for role in sorted({r for g in games for r in g["roles"]}, key=lambda r: (faction_of(r), r)):
        with_ = [g for g in games if role in g["roles"]]
        without = [g for g in games if role not in g["roles"]]
        if not without:
            continue
        a = sum(g["winning_faction"] == "Village" for g in with_)
        b = sum(g["winning_faction"] == "Village" for g in without)
        rows.append([role, faction_of(role), rate(a, len(with_)), rate(b, len(without)),
                     f"{100 * (a / len(with_) - b / len(without)):+.0f}"])
    out.append(table(["Role", "Faction", "With", "Without", "Diff (points)"], rows) if rows
               else "(every game had the same roles)")

    ds = [d for g in games for d in g["decisions"]]
    out.append(f"\nDecision skill by {decisions_by}: share of decisions that helped the player's faction "
               f"({sum(g['has_votes'] for g in games)} of {n} games have vote records; definitions in stats.py)")
    if not ds:
        out.append("(no scored decisions)")
        return "\n".join(out)
    groups = sorted({d[decisions_by] for d in ds})
    rows = []
    for faction in ("Village", "Yakuza"):
        kinds = [k for k in DECISION_ORDER if any(d["kind"] == k and d["faction"] == faction for d in ds)]
        for kind in kinds + ["all"]:
            cell = []
            for grp in groups:
                mine = [d for d in ds if d[decisions_by] == grp and d["faction"] == faction
                        and (kind == "all" or d["kind"] == kind)]
                cell.append(rate(sum(d["good"] for d in mine), len(mine)))
            if any(c != "-" for c in cell):
                rows.append([f"{faction}: {kind}"] + cell)
    out.append(table(["Decision"] + groups, rows))
    return "\n".join(out)


def write_csv(games: list[dict], folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    game_fields = ["game", "file", "date", "log_version", "mock", "setup", "n_players", "days", "winning_faction",
                   "end_reason", "cost", "duration_s", "roles", "frontier_share", "mix", "moderator"]
    tables = {
        "games.csv": [{**{k: g[k] for k in game_fields}, "roles": ";".join(g["roles"])} for g in games],
        "players.csv": [{"game": g["game"], **p} for g in games for p in g["players"]],
        "decisions.csv": [d for g in games for d in g["decisions"]],
    }
    paths = []
    for name, rows in tables.items():
        path = folder / name
        with path.open("w", newline="", encoding="utf-8", errors="replace") as fh:
            if rows:
                writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        paths.append(path)
    return paths


def load_games(paths: Iterable[Path], include_mock: bool = False, min_version: int = 0,
               setup: str = "any", filters: argparse.Namespace | None = None) -> tuple[list[dict], dict[str, int]]:
    games, skipped = [], {"unfinished": 0, "mock": 0, "filtered out": 0}
    for path in log_files(paths):
        g = load_game(path)
        if g is None:
            skipped["unfinished"] += 1
        elif g["mock"] and not include_mock:
            skipped["mock"] += 1
        elif (g["log_version"] < min_version or setup not in ("any", g["setup"])
              or (filters is not None and not game_index.matches(g, filters))):
            skipped["filtered out"] += 1
        else:
            games.append(g)
    return games, skipped


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", type=Path, default=[LOG_DIR], help="game logs or folders (default logs/)")
    ap.add_argument("--include-mock", action="store_true", help="also count mock games")
    ap.add_argument("--min-version", type=int, default=0, help="only logs with at least this log_version")
    ap.add_argument("--setup", choices=["any", "fixed", "random"], default="any", help="only these setups")
    ap.add_argument("--decisions-by", choices=["model", "role"], default="model")
    ap.add_argument("--csv", type=Path, metavar="DIR", help="also write games.csv, players.csv, decisions.csv")
    ap.add_argument("--list", action="store_true", help="list the games that pass the filters instead of the stats")
    game_index.add_filter_args(ap)
    args = ap.parse_args()
    games, skipped = load_games(args.paths, args.include_mock, args.min_version, args.setup, args)
    if args.list:
        print(table(["game", "players", "frontier", "mix", "winner", "days", "cost"],
                    [[g["game"], str(g["n_players"]), f"{g['frontier_share']:.0%}", g["mix"], g["winner"] or "none",
                      str(g["days"]), f"${g['cost']:.2f}"] for g in games]))
        print(f"\n{len(games)} games; skipped " + ", ".join(f"{n} {k}" for k, n in skipped.items() if n))
        return
    print(report(games, skipped, args.decisions_by))
    if args.csv:
        print("\nWrote " + ", ".join(str(p) for p in write_csv(games, args.csv)))


if __name__ == "__main__":
    main()
