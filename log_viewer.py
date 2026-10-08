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
import sys
from pathlib import Path
from typing import Any


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
:root { --bg:#fff; --fg:#1d1d1f; --muted:#6e6e73; --line:#e5e5ea; --pub:#1d1d1f; --priv:#7a4cc2;
        --yak:#b3261e; --mod:#0b6bcb; --death:#b3261e; --call:#f5f5f7; --code:#fafafa; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#141416; --fg:#ececf0; --muted:#9a9aa2; --line:#2c2c30; --pub:#ececf0; --priv:#b996f2;
          --yak:#f28b82; --mod:#7cb7ff; --death:#f28b82; --call:#1e1e22; --code:#1a1a1d; } }
body { background:var(--bg); color:var(--fg); font:14px/1.5 system-ui, sans-serif; margin:0 auto;
       max-width:1000px; padding:16px; }
h1 { font-size:20px; } .muted { color:var(--muted); }
details.phase { border-top:1px solid var(--line); padding:6px 0; }
details.phase > summary { font-weight:600; font-size:16px; cursor:pointer; }
.ev { padding:2px 0 2px 8px; white-space:pre-wrap; }
.ev.private { color:var(--priv); } .ev.yakuza { color:var(--yak); } .ev.mod { color:var(--mod); }
.ev.death { color:var(--death); font-weight:600; } .ev.info { color:var(--muted); }
.tag { font-size:12px; color:var(--muted); margin-right:6px; }
details.call { background:var(--call); border-radius:6px; margin:2px 0 2px 24px; padding:2px 8px; }
details.call > summary { cursor:pointer; color:var(--muted); font-size:13px; }
pre { background:var(--code); border:1px solid var(--line); border-radius:6px; padding:8px;
      white-space:pre-wrap; word-break:break-word; font-size:12px; max-height:500px; overflow:auto; }
table { border-collapse:collapse; } td, th { padding:2px 10px 2px 0; text-align:left; }
.controls { position:sticky; top:0; background:var(--bg); padding:6px 0; border-bottom:1px solid var(--line); }
body.hide-calls details.call { display:none; }
"""

JS = """
const box = document.getElementById('showcalls');
box.addEventListener('change', () => document.body.classList.toggle('hide-calls', !box.checked));
document.getElementById('expand').addEventListener('click', () =>
  document.querySelectorAll('details.call').forEach(d => d.open = true));
document.getElementById('collapse').addEventListener('click', () =>
  document.querySelectorAll('details.call').forEach(d => d.open = false));
"""


def esc(x: Any) -> str:
    return html.escape(str(x))


def pre(label: str, value: Any) -> str:
    if value in (None, "", {}, []):
        return ""
    text = value if isinstance(value, str) else json.dumps(value, indent=1, ensure_ascii=False)
    return f"<div class='muted'>{esc(label)}</div><pre>{esc(text)}</pre>"


def event_class(r: dict) -> str:
    t = r["text"]
    if " died" in t or "executed by hanging" in t:
        return "death"
    if "(Yakuza chat)" in t:
        return "yakuza"
    if t.startswith("Moderator"):
        return "mod"
    if r.get("visible_to") != "all":
        return "private"
    if "(public)" in t:
        return ""
    return "info"


def render_html(jsonl_path: Path) -> Path:
    records = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line]
    roles: dict[str, str] = {}
    out: list[str] = []
    open_phase = False

    def start_phase(title: str) -> None:
        nonlocal open_phase
        if open_phase:
            out.append("</details>")
        out.append(f"<details class='phase' open><summary>{esc(title)}</summary>")
        open_phase = True

    for r in records:
        k = r["kind"]
        if k == "setup":
            roles = {p["name"]: p["role"] for p in r["players"]}
            rows = "".join(f"<tr><td>{esc(p['name'])}</td><td>{p['seat']}</td><td>{esc(p['role'])}</td>"
                           f"<td>{esc(p['model'])}</td><td class='muted'>{esc(p.get('status') or '')}</td></tr>"
                           for p in r["players"])
            start_phase("Setup")
            out.append(f"<table><tr><th>Player</th><th>Seat</th><th>Role</th><th>Model</th><th></th></tr>"
                       f"{rows}</table><div class='muted'>Katana starts with {esc(r.get('katana'))}</div>")
        elif k == "event":
            t = r["text"]
            if t.startswith(("Day ", "Night ")) and t.endswith("begins."):
                start_phase(t[:-len(" begins.")])
                continue
            vis = r.get("visible_to")
            tag = "" if vis == "all" else f"<span class='tag'>to {esc(', '.join(vis))}</span>"
            out.append(f"<div class='ev {event_class(r)}'>{tag}{esc(t)}</div>")
        elif k == "player_call":
            o = dict(r.get("output") or {})
            thoughts = o.pop("thoughts", "")
            first_line = r["task"].split("\n")[0]
            u = r.get("usage") or {}
            summary = (f"{esc(r['player'])} ({esc(roles.get(r['player'], '?'))}, {esc(r['model'].split('/')[-1])})"
                       f" · {esc(first_line[:90])} · ${r.get('cost', 0):.4f}")
            out.append(f"<details class='call'><summary>{summary}</summary>"
                       + pre("Reasoning (model's summarized thinking)", r.get("reasoning"))
                       + pre("Thoughts (private field)", thoughts) + pre("Output", o)
                       + pre("Task prompt", r["task"]) + pre("Usage", u) + "</details>")
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
                out.append(f"<div class='ev mod'>{esc(text_line(r))}</div>")
            else:
                out.append(f"<details class='call'><summary>Tool {esc(r['name'])} result</summary>"
                           + pre("Args", r.get("args")) + pre("Result", r.get("result")) + "</details>")
        elif k in ("night_actions", "katana", "revenge"):
            out.append(f"<div class='ev info'>{esc(text_line(r))}</div>")
        elif k in ("budget_warning", "message_dropped", "player_error", "moderator_error"):
            out.append(f"<details class='call'><summary>{esc(k.replace('_', ' '))}: "
                       f"{esc(r.get('player', ''))}</summary>{pre('Details', r)}</details>")
        elif k == "result":
            start_phase("Game over")
            out.append(f"<div class='ev death'>Winners: {esc(', '.join(r['winners'] or []) or 'nobody')}</div>"
                       + pre("Cost by model (USD)", r.get("cost")))
    if open_phase:
        out.append("</details>")

    title = f"Mafia game {jsonl_path.stem}"
    page = (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' "
            f"content='width=device-width, initial-scale=1'><title>{esc(title)}</title><style>{CSS}</style>"
            f"</head><body><h1>{esc(title)}</h1><div class='controls'><label><input type='checkbox' "
            f"id='showcalls' checked> Show model calls</label> · <button id='expand'>Expand all</button> "
            f"<button id='collapse'>Collapse all</button></div>{''.join(out)}<script>{JS}</script></body></html>")
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
