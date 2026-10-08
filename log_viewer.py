"""Human-readable views of a game's JSONL log.

- text_line(record): one plain-text line for a log record, or None if the record is detail only.
  mafia.py uses it to write logs/<game>.txt live while a game runs.
- render_html(jsonl_path): a single self-contained HTML page. Game events are plain lines grouped
  by day and night; every model call (prompt, thinking, output, cost) is a collapsed row you can
  click to expand. Open it in any browser; no server or framework needed.

Usage:
    uv run log_viewer.py logs/game_....jsonl     # writes logs/game_....html next to it
"""

import html
import json
import re
import sys
from pathlib import Path
from typing import Any

from roles import ROLES, Alignment


def text_line(r: dict) -> str | None:
    k = r["kind"]
    match k:
        case "setup":
            lines = ["Setup:"] + [f"  {p['name']:<8} seat {p['seat']:<2} {p['role']:<17} {p['model']}"
                                  + (f"  {p['status']}" if p.get("status") else "") for p in r["players"]]
            return "\n".join(lines + [f"  Katana starts with {r.get('katana')}"])
        case "event":
            text = r["text"]
            if text.startswith(("Day ", "Night ")) and text.endswith("begins."):
                return f"\n===== {text[:-len(' begins.')].upper()} ====="
            vis = r.get("visible_to")
            prefix = "" if vis == "all" else f"(to {', '.join(vis)}) "
            return f"{prefix}{text}"
        case "night_actions":
            lines = ["Night actions:"]
            for name, a in r["actions"].items():
                lines.append(f"  {name} ({r['roles'].get(name)}): {describe_action(a)}")
            return "\n".join(lines)
        case "katana":
            res = r["result"]
            if res.get("attack"):
                return f"Katana: {res['holder']} holds it and attacks {res['attack']}."
            return f"Katana: no attack ({res.get('note', 'no target')}); {res.get('holder')} keeps it."
        case "moderator_tool" if r["name"] == "end_phase":
            summary = json.loads(r["args"] or "{}").get("summary", "")
            return f"[Moderator summary] {summary}"
        case "revenge":
            return f"[Revenge] {r['source']}'s Divine Attack hits {r['victim']}."
        case "result":
            return f"\n===== GAME OVER =====\nWinners: {', '.join(r['winners'] or []) or 'nobody'}\nCost: {r['cost']}"
    return None


def describe_action(a: dict) -> str:
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


# ---------------------------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------------------------

CSS = """
:root { color-scheme: light dark;
  --bg:#ffffff; --fg:#1d1d1f; --muted:#6e6e73; --line:#e5e5ea; --call:#f5f5f7; --code:#fafafa;
  --village:#1a7f37; --yakuza:#c62828; --neutral:#b45309;
  --c-chat:#9ca3af; --c-pm:#7c3aed; --c-yak:#c62828; --c-nom:#d97706; --c-vote:#0891b2;
  --c-death:#c62828; --c-result:#2563eb; --c-hidden:#64748b; --c-system:#9ca3af; }
@media (prefers-color-scheme: dark) { :root {
  --bg:#141416; --fg:#ececf0; --muted:#9a9aa2; --line:#2c2c30; --call:#1e1e22; --code:#1a1a1d;
  --village:#4ade80; --yakuza:#f87171; --neutral:#fbbf24;
  --c-chat:#6b7280; --c-pm:#a78bfa; --c-yak:#f87171; --c-nom:#fbbf24; --c-vote:#22d3ee;
  --c-death:#f87171; --c-result:#60a5fa; --c-hidden:#94a3b8; --c-system:#6b7280; } }
* { box-sizing:border-box; }
body { background:var(--bg); color:var(--fg); font:14px/1.55 system-ui, sans-serif; margin:0 auto;
       max-width:1000px; padding:0 16px 40px; }
h1 { font-size:20px; margin:16px 0 4px; } .muted { color:var(--muted); }
.controls { position:sticky; top:0; z-index:1; background:var(--bg); padding:8px 0;
            border-bottom:1px solid var(--line); display:flex; flex-wrap:wrap; gap:6px 14px; align-items:center; }
.legend { display:flex; flex-wrap:wrap; gap:6px; align-items:center; margin:8px 0; }
details.phase { border-top:1px solid var(--line); padding:6px 0; }
details.phase > summary { font-weight:650; font-size:16px; cursor:pointer; padding:4px 0; }
details.phase.night > summary { color:var(--c-hidden); }
.ev { padding:3px 0 3px 10px; margin:1px 0; border-left:3px solid var(--c); white-space:pre-wrap;
      overflow-wrap:anywhere; }
.ev.death { font-weight:600; } .ev.system, .ev.hidden { color:var(--muted); }
.badge { display:inline-block; font-size:11px; font-weight:600; line-height:1; padding:3px 6px; margin-right:6px;
         border-radius:4px; color:var(--c); border:1px solid var(--c); vertical-align:1px; white-space:nowrap; }
.chat { --c:var(--c-chat); } .pm { --c:var(--c-pm); } .yak { --c:var(--c-yak); } .nom { --c:var(--c-nom); }
.vote { --c:var(--c-vote); } .death { --c:var(--c-death); } .result { --c:var(--c-result); }
.hidden { --c:var(--c-hidden); } .system { --c:var(--c-system); }
.n { font-weight:650; } .n.Village { color:var(--village); } .n.Yakuza { color:var(--yakuza); }
.n.Neutral { color:var(--neutral); }
details.call { background:var(--call); border-radius:6px; margin:2px 0 2px 24px; padding:2px 8px; }
details.call > summary { cursor:pointer; color:var(--muted); font-size:13px; }
pre { background:var(--code); border:1px solid var(--line); border-radius:6px; padding:8px;
      white-space:pre-wrap; word-break:break-word; font-size:12px; max-height:500px; overflow:auto; }
table { border-collapse:collapse; } td, th { padding:2px 12px 2px 0; text-align:left; }
body.no-calls details.call { display:none; } body.no-hidden .ev.hidden { display:none; }
"""

JS = """
const toggle = (id, cls) => {
  const box = document.getElementById(id);
  const apply = () => document.body.classList.toggle(cls, !box.checked);
  box.addEventListener('change', apply); apply();
};
toggle('showcalls', 'no-calls');
toggle('showhidden', 'no-hidden');
document.getElementById('expand').addEventListener('click', () =>
  document.querySelectorAll('details.call').forEach(d => d.open = true));
document.getElementById('collapse').addEventListener('click', () =>
  document.querySelectorAll('details.call').forEach(d => d.open = false));
"""

CATEGORY_LABELS = {"chat": "Chat", "pm": "PM", "yak": "Yakuza chat", "nom": "Nomination", "vote": "Vote",
                   "death": "Death", "result": "Result", "hidden": "Hidden info", "system": "System"}


def esc(x: Any) -> str:
    return html.escape(str(x))


def pre(label: str, value: Any) -> str:
    if value in (None, "", {}, []):
        return ""
    text = value if isinstance(value, str) else json.dumps(value, indent=1, ensure_ascii=False)
    return f"<div class='muted'>{esc(label)}</div><pre>{esc(text)}</pre>"


def faction_of(role: str) -> str:
    info = ROLES.get(role)
    if info is None:
        return "Village"
    return {Alignment.GOOD: "Village", Alignment.EVIL: "Yakuza", Alignment.NEUTRAL: "Neutral"}[info.alignment]


class Namer:
    """Escapes text and wraps player names in spans colored by faction."""

    def __init__(self, factions: dict[str, str]):
        self.factions = factions
        names = sorted(factions, key=len, reverse=True)
        self.pattern = re.compile(r"\b(" + "|".join(map(re.escape, names)) + r")\b") if names else None

    def __call__(self, text: str) -> str:
        escaped = esc(text)
        if not self.pattern:
            return escaped
        return self.pattern.sub(lambda m: f"<span class='n {self.factions[m[1]]}'>{m[1]}</span>", escaped)


def classify(r: dict) -> tuple[str, str, str]:
    """(category, badge text, body text) for an event."""
    t, vis = r["text"], r.get("visible_to")
    if m := re.match(r"(\w+) \(public\): (.*)", t, re.S):
        return "chat", "", f"{m[1]}: {m[2]}"
    if m := re.match(r"(\w+) -> (\w+) \(private\): (.*)", t, re.S):
        return "pm", "PM", f"{m[1]} → {m[2]}: {m[3]}"
    if m := re.match(r"(\w+) \(Yakuza chat\): (.*)", t, re.S):
        return "yak", "Yakuza chat", f"{m[1]}: {m[2]}"
    if t.startswith("Moderator (private): "):
        return "result", f"Result → {', '.join(vis)}", t[len("Moderator (private): "):]
    if t.startswith("Moderator: "):
        return "result", "Announcement", t[len("Moderator: "):]
    if " died" in t or "executed by hanging" in t or "leave the game" in t:
        return "death", "Death", t
    if " nominated " in t:
        return "nom", "Nomination", t
    if "votes" in t.lower() or "put on trial" in t or "found Innocent" in t or "nomination of" in t:
        return "vote", "Vote", t
    badge = "" if vis == "all" else f"→ {', '.join(vis)}"
    return "system", badge, t


def render_html(jsonl_path: Path) -> Path:
    records = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line]
    roles: dict[str, str] = {}
    name = Namer({})
    out: list[str] = []
    open_phase = False

    def start_phase(title: str) -> None:
        nonlocal open_phase
        if open_phase:
            out.append("</details>")
        cls = "night" if title.startswith("Night") else ""
        out.append(f"<details class='phase {cls}' open><summary>{esc(title)}</summary>")
        open_phase = True

    def line(category: str, badge: str, body_html: str) -> None:
        b = f"<span class='badge'>{esc(badge)}</span>" if badge else ""
        out.append(f"<div class='ev {category}'>{b}{body_html}</div>")

    for r in records:
        k = r["kind"]
        if k == "setup":
            roles = {p["name"]: p["role"] for p in r["players"]}
            name = Namer({n: faction_of(role) for n, role in roles.items()})
            rows = "".join(f"<tr><td>{name(p['name'])}</td><td>{p['seat']}</td><td>{esc(p['role'])}</td>"
                           f"<td>{esc(p['model'])}</td><td class='muted'>{name(str(p.get('status') or ''))}</td></tr>"
                           for p in r["players"])
            start_phase("Setup")
            out.append(f"<table><tr><th>Player</th><th>Seat</th><th>Role</th><th>Model</th><th></th></tr>"
                       f"{rows}</table><div class='muted'>Katana starts with {name(str(r.get('katana')))}</div>")
        elif k == "event":
            t = r["text"]
            if t.startswith(("Day ", "Night ")) and t.endswith("begins."):
                start_phase(t[:-len(" begins.")])
                continue
            category, badge, body = classify(r)
            line(category, badge, name(body))
        elif k == "player_call":
            o = dict(r.get("output") or {})
            thoughts = o.pop("thoughts", "")
            first_line = r["task"].split("\n")[0]
            summary = (f"{name(r['player'])} ({esc(roles.get(r['player'], '?'))}, "
                       f"{esc(r['model'].split('/')[-1])}) · {esc(first_line[:90])} · ${r.get('cost', 0):.4f}")
            out.append(f"<details class='call'><summary>{summary}</summary>"
                       + pre("Reasoning (model's summarized thinking)", r.get("reasoning"))
                       + pre("Thoughts (private field)", thoughts) + pre("Output", o)
                       + pre("Task prompt", r["task"]) + pre("Usage", r.get("usage")) + "</details>")
        elif k == "moderator_call":
            calls = ", ".join(c["function"]["name"] for c in r.get("tool_calls") or []) or "no tool call"
            out.append(f"<details class='call'><summary>Moderator ({esc(r['model'].split('/')[-1])}) → "
                       f"{esc(calls)} · ${r.get('cost', 0):.4f}</summary>"
                       + pre("Reasoning", r.get("reasoning")) + pre("Content", r.get("content"))
                       + pre("Tool calls", [{"name": c["function"]["name"],
                                             "args": json.loads(c["function"].get("arguments") or "{}")}
                                            for c in r.get("tool_calls") or []])
                       + pre("Usage", r.get("usage")) + "</details>")
        elif k == "moderator_tool":
            if r["name"] == "end_phase":
                line("hidden", "Moderator summary", name(json.loads(r["args"] or "{}").get("summary", "")))
            else:
                out.append(f"<details class='call'><summary>Tool {esc(r['name'])} result</summary>"
                           + pre("Args", r.get("args")) + pre("Result", r.get("result")) + "</details>")
        elif k == "night_actions":
            rows = "".join(f"<div>{name(n)} ({esc(r['roles'].get(n))}): {name(describe_action(a))}</div>"
                           for n, a in r["actions"].items())
            line("hidden", "Night actions", rows)
        elif k in ("katana", "revenge"):
            line("hidden", "Katana" if k == "katana" else "Revenge", name(text_line(r)))
        elif k in ("budget_warning", "message_dropped", "nomination_dropped", "player_error", "moderator_error"):
            out.append(f"<details class='call'><summary>{esc(k.replace('_', ' '))}: "
                       f"{esc(r.get('player', ''))}</summary>{pre('Details', r)}</details>")
        elif k == "result":
            start_phase("Game over")
            line("death", "Winners", name(", ".join(r["winners"] or []) or "nobody"))
            out.append(pre("Cost by model (USD)", r.get("cost")))
    if open_phase:
        out.append("</details>")

    legend = "".join(f"<span class='badge {c}'>{esc(label)}</span>" for c, label in CATEGORY_LABELS.items())
    legend += ("<span class='n Village'>Village</span> <span class='n Yakuza'>Yakuza</span> "
               "<span class='n Neutral'>Neutral</span>")
    title = f"Mafia game {jsonl_path.stem}"
    page = (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' "
            f"content='width=device-width, initial-scale=1'><title>{esc(title)}</title><style>{CSS}</style>"
            f"</head><body><h1>{esc(title)}</h1><div class='legend'>{legend}</div><div class='controls'>"
            f"<label><input type='checkbox' id='showcalls' checked> Model details</label>"
            f"<label><input type='checkbox' id='showhidden' checked> Hidden night info</label>"
            f"<span><button id='expand'>Expand all</button> <button id='collapse'>Collapse all</button></span>"
            f"<span class='muted'>Untick both to read it like a player would.</span></div>"
            f"{''.join(out)}<script>{JS}</script></body></html>")
    html_path = jsonl_path.with_suffix(".html")
    html_path.write_text(page, encoding="utf-8")
    return html_path


def render_text(jsonl_path: Path) -> Path:
    lines = [text_line(json.loads(l)) for l in jsonl_path.read_text(encoding="utf-8").splitlines() if l]
    txt_path = jsonl_path.with_suffix(".txt")
    txt_path.write_text("\n".join(l for l in lines if l is not None) + "\n", encoding="utf-8")
    return txt_path


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        p = Path(arg)
        print(render_text(p), render_html(p))
