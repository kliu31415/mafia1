"""An index of every game in logs/: one filterable, sortable table with a row per game, linking to
its HTML log. Filters cover the models seated (and how many seats went to frontier models, by TIERS in
llm.py), the moderator, roles, winner, player count, date, errors and tips.

    uv run game_index.py build            # writes logs/index.html (games and pulls also rebuild it)
    uv run game_index.py serve            # http://localhost:8765, rescans logs/ on every page load

Each game's summary is cached in logs/index_cache.json by file size and modification time, so a rebuild
reads only new or changed logs. Both files are machine-local: sync_logs.py never sends them.
stats.py takes the same filters (filter_args, matches) so its tables can be restricted to the games
the index shows.
"""

import argparse
import html
import json
import os
import threading
import urllib.parse
import webbrowser
from collections import Counter
from collections.abc import Iterable
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from gamelogs import folder_logs, mix_of, model_id, result_of, setup_of, short
from gamelogs import players as game_players
from llm import TIERS, model_tier
from records import read_records

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
INDEX = "index.html"
CACHE = "index_cache.json"
CACHE_VERSION = 3  # bump when summarize()'s fields change, so cached summaries are rebuilt
TIER_ORDER = ["frontier", "mid", "cheap", "unknown"]


def summarize(path: Path) -> dict | None:
    """One game's row: who played, how it ended and what it cost; None if it isn't a game log."""
    records, _ = read_records(path)
    setup = setup_of(records)
    if setup is None:
        return None
    result = result_of(records) or {}
    settings = setup.get("settings") or {}
    seats = game_players(records, setup, result)
    seat_models = [p["model"] for p in seats]
    share, mix = mix_of(seat_models)
    game_id = setup.get("game_id") or path.stem
    try:
        started = datetime.fromtimestamp(setup["t"], timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (KeyError, TypeError, ValueError, OSError):
        started = ""
    errors = Counter(r["kind"] for r in records if r.get("alert"))
    winners = set(result.get("winners") or [])
    winner = result.get("winning_faction") or ("" if result else "unfinished")
    if winner.startswith("Neutral:"):  # a Neutral's faction is named after its player: show its role instead
        role = {p["name"]: p["final_role"] or p["start_role"] for p in seats}.get(winner.removeprefix("Neutral:"))
        winner = f"Neutral:{role}" if role else winner
    return {
        "game": game_id, "started": started, "date": started[:10].replace("-", ""),
        "mock": bool(settings.get("mock")), "finished": bool(result),
        "end_reason": result.get("end_reason") or ("win" if result else "unfinished"),
        "winner": winner,
        "winners": sorted(winners),
        "days": result.get("days") or max((r.get("day") or 0 for r in records if "day" in r), default=0),
        "cost": round(sum((result.get("cost") or {}).values()), 2) if result else None,
        "duration_min": round(result["duration_s"] / 60) if result.get("duration_s") else None,
        "n_players": len(seats), "models": seat_models, "frontier_share": share, "mix": mix,
        "moderator": settings.get("moderator", ""), "setup": (settings.get("setup") or {}).get("kind", "fixed"),
        "players": [{"name": p["name"], "model": p["model"], "via": p["via"], "role": p["start_role"], "won": p["won"],
                     "alive": not p["died"]} for p in seats],
        "roles": sorted(p["start_role"] for p in seats), "errors": sum(errors.values()),
        "error_kinds": dict(errors), "tips": sum(p["tips"] for p in seats), "log_version": setup.get("log_version", 1),
        "git_commit": (setup.get("git_commit") or "")[:7], "seed": settings.get("seed"),
    }


def load_summaries(log_dir: Path = LOG_DIR, include_mock: bool = False) -> list[dict]:
    """Every game's summary, newest first, reading only logs that changed since the cache was written."""
    cache_path = log_dir / CACHE
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        if cache.get("version") != CACHE_VERSION:
            cache = {}
    except (OSError, ValueError):
        cache = {}
    entries = cache.get("games", {})
    out, fresh = [], {}
    for path in folder_logs(log_dir, include_mock):
        st = path.stat()
        key = f"{st.st_size}:{st.st_mtime_ns}"
        entry = entries.get(path.name)
        if not entry or entry.get("key") != key:
            entry = {"key": key, "summary": summarize(path)}
        fresh[path.name] = entry
        if entry["summary"]:
            out.append({**entry["summary"], "links": links(log_dir, path)})
    if fresh != entries:
        try:
            tmp = cache_path.with_name(CACHE + ".tmp")
            tmp.write_text(json.dumps({"version": CACHE_VERSION, "games": fresh}), encoding="utf-8")
            os.replace(tmp, cache_path)
        except OSError:
            pass  # only a cache: the next build reads the logs again
    return sorted(out, key=lambda g: g["game"].split("_", 1)[-1], reverse=True)


def links(log_dir: Path, path: Path) -> dict[str, str]:
    """The game's files next to the index, by label (relative links, so the folder can move)."""
    stem = path.stem
    files = {"log": f"{stem}.html", "txt": f"{stem}.txt", "feedback": f"{stem}_feedback.md", "jsonl": path.name}
    return {k: v for k, v in files.items() if (log_dir / v).exists()}


# --- filters shared with stats.py ------------------------------------------------------------------

def player_range(text: str) -> tuple[int, int]:
    lo, _, hi = text.partition("-")
    return int(lo), int(hi or lo)


def add_filter_args(ap: argparse.ArgumentParser) -> None:
    g = ap.add_argument_group("game filters (the same as the index page's)")
    g.add_argument("--model", action="append", default=[], metavar="MODEL",
                   help="only games that seat this model (short name or id; repeat to require several)")
    g.add_argument("--min-frontier", type=float, metavar="SHARE",
                   help="only games where at least this share of seats (0-1) are frontier models (TIERS in llm.py)")
    g.add_argument("--mix", choices=[*TIER_ORDER[:3], "mixed"], help="only games with this mix of model tiers")
    g.add_argument("--moderator", help="only games with this moderator model")
    g.add_argument("--role", action="append", default=[], help="only games with this role (repeatable)")
    g.add_argument("--winner", help="only games this faction won (Village, Yakuza, ...; 'none' for no winner)")
    g.add_argument("--players", type=player_range, metavar="N or A-B", help="only games with this many players")
    g.add_argument("--since", metavar="YYYY-MM-DD", help="only games started on or after this day")
    g.add_argument("--until", metavar="YYYY-MM-DD", help="only games started on or before this day")


def matches(g: dict, args: argparse.Namespace) -> bool:
    """Whether a game (a summary, or a stats.py game with the same fields) passes the filters in args."""
    day = lambda s: s.replace("-", "")  # noqa: E731
    seated = set(g["models"])
    checks = [
        all(model_id(m) in seated for m in args.model),
        args.min_frontier is None or g["frontier_share"] >= args.min_frontier,
        args.mix is None or g["mix"] == args.mix,
        args.moderator is None or g.get("moderator") == model_id(args.moderator),
        all(r in g["roles"] for r in args.role),
        args.winner is None or (g.get("winner") or "none").lower() == args.winner.lower(),
        args.players is None or args.players[0] <= g["n_players"] <= args.players[1],
        args.since is None or g["date"] >= day(args.since),
        args.until is None or g["date"] <= day(args.until),
    ]
    return all(checks)


# --- the page ---------------------------------------------------------------------------------------

def render(games: list[dict], built: str, live: bool = False) -> str:
    tiers = {m: model_tier(m) for g in games for m in g["models"] + [g["moderator"]]}
    meta = {"short": {m: short(m) for m in tiers}, "tiers": tiers, "built": built, "live": live,
            "tier_table": {short(m): t for m, t in TIERS.items()}}
    data = json.dumps({"games": games, "meta": meta}).replace("</", "<\\/")
    return PAGE.replace("/*DATA*/null", data).replace("{{title}}", html.escape(f"Games ({len(games)})"))


def build(log_dir: Path = LOG_DIR, include_mock: bool = False) -> Path:
    """Writes log_dir/index.html; returns its path."""
    games = load_summaries(log_dir, include_mock)
    out = log_dir / INDEX
    tmp = out.with_name(INDEX + ".tmp")
    tmp.write_text(render(games, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")), encoding="utf-8")
    os.replace(tmp, out)
    return out


# What a game's HTML page is built from besides its log: when any of it changes, `serve` re-renders a page as it's
# opened, so old games show the current viewer, icons and role descriptions (Kevin, Oct 12 2026).
VIEWER_SOURCES = ["log_viewer.py", "gamelogs.py", "texts.py", "traits.py", "roles/__init__.py", "rules_1.txt",
                  "roles/icons/*.svg", "roles/icons/retired/*.svg"]
RENDER_LOCK = threading.Lock()  # one render at a time, so two clicks don't write the same page together


def viewer_mtime() -> float:
    here = Path(__file__).parent
    return max(p.stat().st_mtime for pattern in VIEWER_SOURCES for p in here.glob(pattern))


def stale_log(log_dir: Path, url_path: str) -> Path | None:
    """The log of a game page that's older than it or than the viewer code (so it needs re-rendering), else None."""
    name = urllib.parse.unquote(url_path).lstrip("/")
    if not name.endswith(".html") or "/" in name or "\\" in name or name == INDEX:
        return None
    page, log = log_dir / name, (log_dir / name).with_suffix(".jsonl")
    if not log.exists():
        return None
    built = page.stat().st_mtime if page.exists() else 0.0
    return log if built < max(log.stat().st_mtime, viewer_mtime()) else None


BUILDING: set[Path] = set()  # logs whose page a background thread is re-rendering
FAILED: dict[Path, float] = {}  # log -> its mtime when its re-render failed (not retried until it changes)
STATE_LOCK = threading.Lock()


def fresh_log_page(log_dir: Path, url_path: str) -> None:
    """Re-renders a game's HTML page if it's older than its log or the viewer code (about a second per 10 MB of log,
    once per change). A failed render leaves the old page and isn't retried until the log changes."""
    with RENDER_LOCK:
        if not (log := stale_log(log_dir, url_path)):
            return
        try:
            import log_viewer
            log_viewer.render_html(log)
        except Exception as e:  # serve keeps going; the old page (if any) is sent
            FAILED[log] = log.stat().st_mtime
            print(f"ALERT render_error: couldn't re-render {log.with_suffix('.html').name}: {type(e).__name__}: {e}")


def rebuilding(log_dir: Path, url_path: str) -> bool:
    """For `serve`: whether this game page is being re-rendered in the background, so a placeholder goes out instead
    (REBUILDING_PAGE, which reloads itself). Starts the re-render if it isn't running."""
    log = stale_log(log_dir, url_path)
    if not log or FAILED.get(log) == log.stat().st_mtime:
        return False
    with STATE_LOCK:
        if log not in BUILDING:
            BUILDING.add(log)

            def run() -> None:
                try:
                    fresh_log_page(log_dir, url_path)
                finally:
                    with STATE_LOCK:
                        BUILDING.discard(log)
            threading.Thread(target=run, daemon=True).start()
    return True


# Sent while a game page is re-rendered (Kevin, Oct 12 2026: show that it's building); it reloads every second.
REBUILDING_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="1">
<title>Rebuilding...</title><style>body{font:16px system-ui,sans-serif;margin:3em;color:#222;background:#fff}
@media (prefers-color-scheme:dark){body{color:#ddd;background:#1b1b1b}}</style></head><body>
<p><b>Rebuilding this game's page...</b></p><p>Its log or the log viewer changed since the page was last built. This
page reloads by itself when it's ready (about a second per 10 MB of log).</p></body></html>"""


def serve(log_dir: Path, port: int, include_mock: bool, open_browser: bool) -> None:
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(log_dir), **kw)

        def do_GET(self) -> None:
            if self.path.split("?")[0] not in ("/", f"/{INDEX}"):
                if rebuilding(log_dir, self.path.split("?")[0]):
                    self.send_page(REBUILDING_PAGE.encode())
                else:
                    super().do_GET()
                return
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            self.send_page(render(load_summaries(log_dir, include_mock), now, live=True).encode())

        def send_page(self, page: bytes) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, format: str, *args) -> None:
            pass  # quiet: every log file the browser opens would print a line

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)  # this machine only
    url = f"http://localhost:{port}/"
    print(f"Serving the game index of {log_dir} at {url} (Ctrl+C stops it)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def main(argv: Iterable[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="write logs/index.html")
    s = sub.add_parser("serve", help="serve an always-current index on localhost")
    for p in (b, s):
        p.add_argument("--logs", type=Path, default=LOG_DIR, help="the log folder (default logs/)")
        p.add_argument("--include-mock", action="store_true", help="also list mock games")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-open", action="store_true", help="don't open a browser tab")
    args = ap.parse_args(list(argv) if argv is not None else None)
    if args.command == "build":
        out = build(args.logs, args.include_mock)
        print(f"Wrote {out}")
    else:
        serve(args.logs, args.port, args.include_mock, not args.no_open)


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{title}}</title>
<style>
:root { --bg:#fff; --fg:#1d1d1f; --muted:#6e6e73; --line:#e5e5ea; --row:#f7f7f9; --chip:#f0f0f3;
  --frontier:#7a3fd1; --mid:#1f6fd1; --cheap:#6e6e73; --unknown:#b0b0b8;
  --Village:#2e8b3e; --Yakuza:#c43a3a; --Neutral:#b07a10; --err:#c43a3a; }
@media (prefers-color-scheme: dark) { :root { --bg:#141416; --fg:#ececf0; --muted:#9a9aa2; --line:#2c2c30;
  --row:#1b1b1e; --chip:#26262a; --frontier:#b48af0; --mid:#6aa8f0; --cheap:#9a9aa2; --unknown:#5a5a62;
  --Village:#5cc46c; --Yakuza:#f07070; --Neutral:#e0b040; --err:#f07070; } }
body { background:var(--bg); color:var(--fg); font:14px/1.45 system-ui, sans-serif; margin:0; padding:16px; }
h1 { font-size:18px; margin:0 0 4px; } .muted { color:var(--muted); }
.filters { display:flex; flex-wrap:wrap; gap:10px 16px; align-items:center; padding:10px 0; position:sticky; top:0;
  background:var(--bg); border-bottom:1px solid var(--line); z-index:2; }
.filters label { display:flex; gap:6px; align-items:center; } input, select, button { font:inherit; color:inherit;
  background:var(--bg); border:1px solid var(--line); border-radius:6px; padding:3px 6px; }
input[type=search] { width:220px; } input[type=number] { width:56px; } button { cursor:pointer; }
.models { display:flex; flex-wrap:wrap; gap:4px; }
.models label { background:var(--chip); border-radius:12px; padding:1px 8px; cursor:pointer; user-select:none; }
.models input { display:none; } .models label:has(input:checked) { outline:2px solid var(--fg); }
.wrap { overflow-x:auto; } table { border-collapse:collapse; width:100%; margin-top:8px; }
th, td { padding:5px 8px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; white-space:nowrap; }
th { cursor:pointer; user-select:none; position:sticky; } th.sorted::after { content:" ▾"; } th.sorted.asc::after { content:" ▴"; }
tr:hover td { background:var(--row); } td.num { text-align:right; font-variant-numeric:tabular-nums; }
.chip { display:inline-block; border-radius:10px; padding:0 7px; margin:1px 2px 1px 0; font-size:12.5px;
  background:var(--chip); }
.chip::before { content:""; display:inline-block; width:7px; height:7px; border-radius:50%; background:var(--t);
  margin-right:5px; vertical-align:1px; }
.t-frontier { --t:var(--frontier); } .t-mid { --t:var(--mid); } .t-cheap { --t:var(--cheap); } .t-unknown { --t:var(--unknown); }
.bar { display:inline-block; width:46px; height:7px; background:var(--chip); border-radius:4px; vertical-align:middle;
  margin-right:6px; overflow:hidden; } .bar i { display:block; height:100%; background:var(--frontier); }
.win-Village { color:var(--Village); font-weight:600; } .win-Yakuza { color:var(--Yakuza); font-weight:600; }
.win-other { color:var(--Neutral); font-weight:600; } .err { color:var(--err); font-weight:600; }
td.roles summary { cursor:pointer; color:var(--muted); } td.roles div { white-space:normal; width:260px; font-size:12.5px; }
td.models { white-space:normal; min-width:240px; }
a { color:var(--mid); } body > details { margin-top:14px; } .legend span { margin-right:12px; }
</style></head><body>
<h1>Games</h1>
<div class="muted" id="sub"></div>
<div class="filters">
  <label><input type="search" id="q" placeholder="Search game, role, model, player"></label>
  <label>Mix <select id="mix"><option value="">any</option><option>frontier</option><option>mid</option>
    <option>cheap</option><option>mixed</option></select></label>
  <label>Frontier seats ≥ <input type="number" id="minf" min="0" max="100" step="10" value="0">%</label>
  <label>Winner <select id="winner"><option value="">any</option></select></label>
  <label>Players <input type="number" id="pmin" min="1" placeholder="min">–<input type="number" id="pmax" min="1" placeholder="max"></label>
  <label>From <input type="date" id="since"></label><label>to <input type="date" id="until"></label>
  <label><input type="checkbox" id="unfinished"> unfinished</label>
  <label><input type="checkbox" id="errs"> with errors</label>
  <label><input type="checkbox" id="tipsonly"> with tips</label>
  <button id="reset">Reset</button>
  <div class="models" id="models" title="Only games that seat every model picked here"></div>
</div>
<div class="wrap"><table><thead><tr id="head"></tr></thead><tbody id="rows"></tbody></table></div>
<details><summary class="muted">Model tiers (TIERS in llm.py)</summary><div class="legend" id="legend"></div></details>
<script>
const DATA = /*DATA*/null;
const M = DATA.meta, G = DATA.games, $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const sh = m => M.short[m] || m, tier = m => M.tiers[m] || "unknown";
const ORDER = ["frontier", "mid", "cheap", "unknown"];
const COLS = [
  ["Game", g => g.started, g => links(g)],
  ["Players", g => g.n_players, g => g.n_players, "num"],
  ["Models", g => g.frontier_share, g => modelChips(g.models), "models"],
  ["Frontier", g => g.frontier_share, g => `<span class="bar"><i style="width:${g.frontier_share*100}%"></i></span>${Math.round(g.frontier_share*100)}%`],
  ["Mix", g => g.mix, g => `<span class="chip t-${g.mix === "mixed" ? "unknown" : g.mix}">${g.mix}</span>`],
  ["Moderator", g => sh(g.moderator), g => g.moderator ? modelChips([g.moderator]) : ""],
  ["Winner", g => g.winner, g => winner(g)],
  ["Days", g => g.days, g => g.days, "num"],
  ["Cost", g => g.cost ?? -1, g => g.cost == null ? "" : "$" + g.cost.toFixed(2), "num"],
  ["Minutes", g => g.duration_min ?? -1, g => g.duration_min ?? "", "num"],
  ["Errors", g => g.errors, g => g.errors ? `<span class="err" title="${esc(Object.entries(g.error_kinds).map(([k, n]) => k + " ×" + n).join(", "))}">${g.errors}</span>` : "0", "num"],
  ["Tips", g => g.tips, g => g.tips ? `${g.tips}/${g.n_players}` : "", "num"],
  ["Roles", g => g.roles.length, g => `<details><summary>${g.roles.length} roles</summary><div>${esc(g.roles.join(", "))}</div></details>`, "roles"],
];
function modelChips(models) {
  const c = {}; models.forEach(m => c[m] = (c[m] || 0) + 1);
  return Object.entries(c).sort((a, b) => ORDER.indexOf(tier(a[0])) - ORDER.indexOf(tier(b[0])) || b[1] - a[1])
    .map(([m, n]) => `<span class="chip t-${tier(m)}" title="${esc(m)} (${tier(m)})">${esc(sh(m))}${n > 1 ? " ×" + n : ""}</span>`).join("");
}
function winner(g) {
  if (!g.finished) return `<span class="muted">unfinished</span>`;
  if (!g.winner) return `<span class="muted">${esc(g.end_reason)}</span>`;
  const cls = ["Village", "Yakuza"].includes(g.winner) ? "win-" + g.winner : "win-other";
  return `<span class="${cls}" title="${esc(g.winners.join(", "))}">${esc(g.winner)}</span>`;
}
function links(g) {
  const l = g.links || {}, label = esc(g.started || g.game);
  const main = l.log ? `<a href="${esc(l.log)}" title="${esc(g.game)}">${label}</a>` : `<span title="${esc(g.game)}">${label}</span>`;
  return main + ["txt", "feedback"].filter(k => l[k]).map(k => ` <a class="muted" href="${esc(l[k])}">${k}</a>`).join("");
}
// filters
const winners = [...new Set(G.map(g => g.winner).filter(w => w && w !== "unfinished"))].sort();
$("winner").innerHTML += winners.map(w => `<option>${esc(w)}</option>`).join("") + `<option value="none">no winner</option>`;
const allModels = [...new Set(G.flatMap(g => g.models))].sort((a, b) => ORDER.indexOf(tier(a)) - ORDER.indexOf(tier(b)) || sh(a).localeCompare(sh(b)));
$("models").innerHTML = allModels.map(m => `<label class="chip t-${tier(m)}" title="${esc(m)}"><input type="checkbox" value="${esc(m)}">${esc(sh(m))}</label>`).join("");
$("legend").innerHTML = ORDER.slice(0, 3).map(t => `<span><b class="chip t-${t}">${t}</b> ` +
  Object.entries(M.tier_table).filter(([, v]) => v === t).map(([m]) => esc(m)).join(", ") + `</span>`).join("<br>");
const IDS = ["q", "mix", "minf", "winner", "pmin", "pmax", "since", "until", "unfinished", "errs", "tipsonly"];
let sortCol = 0, asc = false;
function state() {
  const s = {}; IDS.forEach(id => { const e = $(id); const v = e.type === "checkbox" ? (e.checked ? "1" : "") : e.value; if (v && v !== "0") s[id] = v; });
  const ms = [...document.querySelectorAll("#models input:checked")].map(e => e.value); if (ms.length) s.models = ms.join(",");
  if (sortCol) s.sort = sortCol; if (asc) s.asc = "1"; return s;
}
function restore() {
  const s = Object.fromEntries(new URLSearchParams(location.hash.slice(1)));
  IDS.forEach(id => { const e = $(id); if (e.type === "checkbox") e.checked = !!s[id]; else e.value = s[id] ?? (id === "minf" ? "0" : ""); });
  const ms = new Set((s.models || "").split(",")); document.querySelectorAll("#models input").forEach(e => e.checked = ms.has(e.value));
  sortCol = +(s.sort || 0); asc = !!s.asc;
}
function keep(g, s) {
  if (!g.finished && !s.unfinished) return false;
  if (s.mix && g.mix !== s.mix) return false;
  if (s.minf && g.frontier_share * 100 < +s.minf - 1e-9) return false;
  if (s.winner && (g.winner || "none").toLowerCase() !== s.winner.toLowerCase()) return false;
  if (s.pmin && g.n_players < +s.pmin) return false;
  if (s.pmax && g.n_players > +s.pmax) return false;
  if (s.since && g.date < s.since.replaceAll("-", "")) return false;
  if (s.until && g.date > s.until.replaceAll("-", "")) return false;
  if (s.errs && !g.errors) return false;
  if (s.tipsonly && !g.tips) return false;
  if (s.models && !s.models.split(",").every(m => g.models.includes(m))) return false;
  if (s.q) {
    const hay = [g.game, g.mix, g.winner, g.moderator, sh(g.moderator), ...g.roles, ...g.models.map(sh),
                 ...g.players.map(p => p.name), ...Object.keys(g.error_kinds)].join(" ").toLowerCase();
    if (!s.q.toLowerCase().split(/\s+/).every(w => hay.includes(w))) return false;
  }
  return true;
}
function draw() {
  const s = state(), rows = G.filter(g => keep(g, s)), key = COLS[sortCol][1];
  rows.sort((a, b) => { const x = key(a), y = key(b); return (x < y ? -1 : x > y ? 1 : 0) * (asc ? 1 : -1); });
  $("head").innerHTML = COLS.map((c, i) => `<th data-i="${i}" class="${i === sortCol ? "sorted" + (asc ? " asc" : "") : ""}">${c[0]}</th>`).join("");
  $("rows").innerHTML = rows.map(g => "<tr>" + COLS.map(c => `<td class="${c[3] || ""}">${c[2](g)}</td>`).join("") + "</tr>").join("");
  const cost = rows.reduce((t, g) => t + (g.cost || 0), 0), wins = {};
  rows.filter(g => g.winner && g.finished).forEach(g => wins[g.winner] = (wins[g.winner] || 0) + 1);
  $("sub").textContent = `${rows.length} of ${G.length} games · $${cost.toFixed(2)} · ` +
    (Object.entries(wins).map(([w, n]) => `${w} ${n}`).join(", ") || "no wins") +
    ` · ${M.live ? "live, rescanned" : "built"} ${M.built}` + (M.live ? "" : " (uv run game_index.py build)");
  const h = new URLSearchParams(s).toString(); history.replaceState(null, "", h ? "#" + h : location.pathname);
}
document.querySelector(".filters").addEventListener("input", draw);
$("head").addEventListener("click", e => { const i = +e.target.dataset.i; if (isNaN(i)) return;
  if (i === sortCol) asc = !asc; else { sortCol = i; asc = false; } draw(); });
$("reset").onclick = () => { location.hash = ""; restore(); draw(); };
window.addEventListener("hashchange", () => { restore(); draw(); });
restore(); draw();
</script></body></html>
"""


if __name__ == "__main__":
    main()
