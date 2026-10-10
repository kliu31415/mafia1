"""Human-readable views of a game's JSONL log.

- text_line(record): one plain-text line for a log record, or None if the record is detail only.
  mafia.py uses it to write logs/<game>.txt live while a game runs.
- render_html(jsonl_path): a single self-contained HTML page. Game events are plain lines grouped
  by day and night; every model call (prompt, thinking, output, cost) is a collapsed row you can
  click to expand. Open it in any browser; no server or framework needed.
  Player names are colored by faction, with their role's icon from roles/icons/ inlined into the page.

Usage:
    uv run log_viewer.py logs/game_....jsonl     # writes logs/game_....html next to it
"""

import html
import json
import re
import sys
import urllib.parse
from collections import Counter
from pathlib import Path
from collections.abc import Iterable
from typing import Any

from gamelogs import faction_of
from records import read_records
from roles import ROLES
from texts import blank, describe_action, player_view


def text_line(r: dict) -> str | None:
    k = r["kind"]
    if r.get("alert"):  # GameLog.error
        return f"[ERROR {k}] {r['error']}"
    match k:
        case "setup":
            lines = ["Setup:"] + [f"  {p['name']:<8} seat {p['seat'] + 1:<2} {p['role']:<17} {p['model']}"
                                  + (f"  {p['status']}" if p.get("status") else "") for p in r["players"]]
            return "\n".join(lines + [f"  Katana starts with {r.get('katana')}"])
        case "event":
            text = r["text"]
            if is_phase_start(r):
                return f"\n===== {text.removesuffix(' begins.').upper()} ====="
            vis = r["visible_to"]
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
            return f"Katana: no attack ({res.get('note', 'no target')}); {res.get('holder') or 'nobody'} holds it."
        case "moderator_tool" if r["name"] == "end_phase":
            summary = tool_args(r["args"]).get("summary", "")
            return f"[Moderator summary] {summary}"
        case "claim":
            return f"[Claim] {r['player']}: {r['claim']}"
        case "moderator_flag":
            return f"[Moderator flag] {r['issue']}"
        case "player_feedback":
            return f"[Feedback from {r['player']}] {r['feedback']}"
        case "revenge":
            return f"[Revenge] {r['source']}'s Divine Attack hits {r['victim']}."
        case "night_check":
            return f"[Night check] {describe_check(r)}"
        case "tips":
            return "Tips from past games given to: " + (", ".join(f"{n} ({f})" for n, f in tips_files(r).items())
                                                        or "nobody")
        case "section":
            return f"\n===== {r['title'].upper()} ====="
        case "resume":
            return f"[Resumed from the checkpoint at the start of {r.get('at', 'day')} {r['day']}]"
        case "result":
            cost = "\n".join(usage_lines(r["usage"])) if "usage" in r else f"Cost: {r['cost']}"  # LOG_VERSION 10+
            return f"\n===== GAME OVER =====\nWinners: {', '.join(r['winners'] or []) or 'nobody'}\n{cost}"
    return None


def tool_args(text: str | None) -> dict:
    """A tool call's arguments as the model wrote them: invalid JSON (e.g. cut off) is shown as text."""
    try:
        args = json.loads(text or "{}")
    except json.JSONDecodeError:
        return {"unparsable arguments": text}
    return args if isinstance(args, dict) else {"arguments": args}


def tips_files(r: dict) -> dict[str, str]:
    """Player -> tips file of a "tips" record (LOG_VERSION 13+ has files; 11-12 had one file for all)."""
    return r.get("files") or dict.fromkeys(r["players"], r.get("file", "?"))


def describe_check(r: dict) -> str:
    """A night_check record (night_check.py) as one line."""
    head = f"Night {r['night']}: {r['verdict']}" + (f" ({r['error']})" if r.get("error") else "")
    issues = "; ".join(f"[{i['severity']}, {i['rule']}, {i['kind']}] {i['description']}" for i in r["issues"])
    return f"{head}. {issues}" if issues else head


# ---------------------------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------------------------

CSS = """
:root { color-scheme: light dark;
  --bg:#ffffff; --fg:#1d1d1f; --muted:#6e6e73; --line:#e5e5ea; --call:#f5f5f7; --code:#fafafa;
  --village:#1a7f37; --yakuza:#c62828; --neutral:#b45309;
  /* event colors avoid the faction hues (green, red, amber) */
  --c-chat:#9ca3af; --c-pm:#7c3aed; --c-yak:#a21caf; --c-nom:#2563eb; --c-vote:#0891b2; --c-claim:#4f46e5;
  --c-death:#9f1239; --c-result:#0f766e; --c-hidden:#64748b; --c-system:#9ca3af; --c-error:#dc2626; }
@media (prefers-color-scheme: dark) { :root {
  --bg:#141416; --fg:#ececf0; --muted:#9a9aa2; --line:#2c2c30; --call:#1e1e22; --code:#1a1a1d;
  --village:#4ade80; --yakuza:#f87171; --neutral:#fbbf24;
  --c-chat:#6b7280; --c-pm:#a78bfa; --c-yak:#e879f9; --c-nom:#60a5fa; --c-vote:#22d3ee; --c-claim:#818cf8;
  --c-death:#fb7185; --c-result:#2dd4bf; --c-hidden:#94a3b8; --c-system:#6b7280; --c-error:#f87171; } }
* { box-sizing:border-box; }
body { background:var(--bg); color:var(--fg); font:14px/1.55 system-ui, sans-serif; margin:0 auto;
       max-width:1000px; padding:0 16px 40px; }
h1 { font-size:20px; margin:16px 0 4px; } .muted { color:var(--muted); }
.controls { position:sticky; top:0; z-index:1; background:var(--bg); padding:8px 0;
            border-bottom:1px solid var(--line); display:flex; flex-wrap:wrap; gap:6px 14px; align-items:center; }
.legend { display:flex; flex-wrap:wrap; gap:6px; align-items:center; margin:8px 0; }
details.phase { border-top:1px solid var(--line); padding:6px 0; }
/* the browser skips rendering phases that are off screen (they stay searchable with Ctrl+F); each
   phase's estimated height is set inline so the scrollbar is about right before it is first drawn */
details.phase { content-visibility:auto; }
details.phase > summary { font-weight:650; font-size:16px; cursor:pointer; padding:4px 0; }
details.phase.night > summary { color:var(--c-hidden); }
.ev { padding:3px 0 3px 10px; margin:1px 0; border-left:3px solid var(--c); white-space:pre-wrap;
      overflow-wrap:anywhere; }
.ev.death { font-weight:600; color:var(--c-death); background:color-mix(in srgb, var(--c-death) 7%, transparent); } .ev.system, .ev.hidden { color:var(--muted); }
.badge { display:inline-block; font-size:11px; font-weight:600; line-height:1; padding:3px 6px; margin-right:6px;
         border-radius:4px; color:var(--c); border:1px solid var(--c); vertical-align:1px; white-space:nowrap; }
.chat { --c:var(--c-chat); } .pm { --c:var(--c-pm); } .yak { --c:var(--c-yak); } .nom { --c:var(--c-nom); }
.vote { --c:var(--c-vote); } .death { --c:var(--c-death); } .claim { --c:var(--c-claim); } .result { --c:var(--c-result); }
.hidden { --c:var(--c-hidden); } .system { --c:var(--c-system); } .error { --c:var(--c-error); }
.ev.error { color:var(--c-error); }
.errors { border:2px solid var(--c-error); border-radius:6px; padding:6px 12px; margin:8px 0; }
.errors summary { cursor:pointer; font-weight:650; color:var(--c-error); }
.errors ul { margin:4px 0; padding-left:20px; } .no-errors { margin:8px 0; }
.n { font-weight:650; } .n.Village { color:var(--village); } .n.Yakuza { color:var(--yakuza); }
.n.Neutral { color:var(--neutral); }
/* role icons (roles/icons/*.svg) in full color, each on a badge tinted by faction: each role's class sets --icon */
.n.Village { --tint:#dcfce7; --edge:#4ade80; } .n.Yakuza { --tint:#fee2e2; --edge:#f87171; }
.n.Neutral { --tint:#fef3c7; --edge:#fbbf24; }
.n.ic::before { content:""; display:inline-block; width:1.35em; height:1.35em; margin-right:3px; vertical-align:-0.35em;
  border-radius:5px; border:1px solid var(--edge); background:var(--icon) center/80% no-repeat, var(--tint); }
body.no-icons .n.ic::before { display:none; }
details.call { background:var(--call); border-radius:6px; margin:2px 0 2px 24px; padding:2px 8px; }
details.call > summary { cursor:pointer; color:var(--muted); font-size:13px; }
pre { background:var(--code); border:1px solid var(--line); border-radius:6px; padding:8px;
      white-space:pre-wrap; word-break:break-word; font-size:12px; max-height:500px; overflow:auto; }
table { border-collapse:collapse; } td, th { padding:2px 12px 2px 0; text-align:left; }
details.usage { border-bottom:1px solid var(--line); padding:3px 0; } details.usage > summary { cursor:pointer; }
div.usage.total { font-weight:650; padding:3px 0 3px 16px; }
.usage .who { display:inline-block; width:240px; } .usage .model { display:inline-block; width:200px; }
.usage .cost { display:inline-block; width:80px; text-align:right; margin-right:14px; font-variant-numeric:tabular-nums; }
details.usage table { margin:4px 0 8px 16px; }
body.no-calls details.call { display:none; } body.no-hidden .ev.hidden { display:none; }
body.no-hidden .ev.error { display:none; }
body.no-calls details.why { display:none; }
details.why { display:inline; margin-left:8px; font-size:12px; color:var(--muted); white-space:normal; }
details.why > summary { display:inline; cursor:pointer; text-decoration:underline dotted; }
details.why[open] { display:block; margin:2px 0 4px 16px; padding:4px 8px; background:var(--call); border-radius:6px; }
details.why[open] > summary { display:block; }
details.thinking > summary { cursor:pointer; }
details.votes { margin:4px 0; } details.votes > summary { cursor:pointer; color:var(--muted); font-size:13px; }
.scroll { overflow-x:auto; } details.votes table { font-size:12px; margin:4px 0; }
details.votes td, details.votes th { padding:1px 6px; text-align:center; border-bottom:1px solid var(--line); }
details.votes tr > th:first-child { text-align:left; white-space:nowrap; }
details.votes td.yes { font-weight:700; } details.votes td.no { color:var(--muted); }
.focus-hide { display:none !important; }
"""

JS = """
const toggle = (id, cls) => {
  const box = document.getElementById(id);
  const apply = () => document.body.classList.toggle(cls, !box.checked);
  box.addEventListener('change', apply); apply();
};
toggle('showcalls', 'no-calls');
toggle('showhidden', 'no-hidden');
toggle('showicons', 'no-icons');
document.getElementById('expand').addEventListener('click', () =>
  document.querySelectorAll('details.call').forEach(d => d.open = true));
document.getElementById('collapse').addEventListener('click', () =>
  document.querySelectorAll('details.call').forEach(d => d.open = false));
// Player filter: show only the lines and calls that involve the chosen player (their data-p).
const focus = document.getElementById('focus');
const applyFocus = () => {
  const who = focus.value;
  document.querySelectorAll('details.phase > .ev, details.phase > details.call').forEach(el =>
    el.classList.toggle('focus-hide', who !== '' && !(el.dataset.p || '').split(' ').includes(who)));
};
focus.addEventListener('change', applyFocus); applyFocus();
"""

CATEGORY_LABELS = {"chat": "Chat", "pm": "PM", "yak": "Yakuza chat", "nom": "Nomination", "vote": "Vote",
                   "death": "Death", "claim": "Claim", "result": "Result", "hidden": "Hidden info", "system": "System"}


def esc(x: Any) -> str:
    return html.escape(str(x))


def pre(label: str, value: Any, hint: str = "") -> str:
    """hint: hover text on the label explaining what it is."""
    if value in (None, "", {}, []):
        return ""
    text = value if isinstance(value, str) else json.dumps(value, indent=1, ensure_ascii=False)
    title = f" title='{esc(hint)}' style='cursor:help'" if hint else ""
    return f"<div class='muted'{title}>{esc(label)}{' ⓘ' if hint else ''}</div><pre>{esc(text)}</pre>"


REASONING_HINT = ("The model's own thinking before it answered, as its provider returns it: summarized for "
                  "Claude and Gemini, raw for Grok, Qwen and Kimi; OpenAI models (Sol, Luna) return it encrypted, "
                  "with a summary only on about 1 call in 8. Not part of the answer; nobody in the game sees it.")
REASON_HINT = ("The 'reason' field of the answer: the player's own explanation of this choice, written after "
               "deciding. Logged only; nobody in the game, nor the moderator, sees it. A paragraph of up to ~150 "
               "words by default; a sentence or a few for models whose reasoning comes back in full or whose API "
               "filters strictly (Claude, Grok, Qwen, Kimi; llm.SHORT_REASON).")


def short_model(model: str) -> str:
    return model.split("/")[-1]


def usage_lines(usage: list[dict]) -> list[str]:
    """The result record's cost by player (and moderator, and post-game steps) as plain-text lines."""
    label = {u["who"]: u["who"] + (f" ({u['role']})" if u.get("role") else "") for u in usage}
    width = max((len(s) for s in label.values()), default=0)
    lines = ["Cost by player (USD):"]
    for u in usage:
        lines.append(f"  {label[u['who']]:<{width}}  ${u['cost']:.4f}  {u['calls']:>3} calls  "
                     f"{', '.join(short_model(m) for m in u['models']) or '?'}")
    lines.append(f"  {'Total':<{width}}  ${sum(u['cost'] for u in usage):.4f}  "
                 f"{sum(u['calls'] for u in usage):>3} calls")
    return lines


def usage_html(usage: list[dict]) -> str:
    """The cost table at the end of the HTML view: one expandable row per player, the moderator and
    each post-game step, with its calls and tokens inside."""
    def num(n: float) -> str:
        return f"{n:,}"
    rows = []
    for u in usage:
        who = name_span(u['who'], u['role']) if u.get("role") \
            else esc(u["who"])
        detail = {"Role": u.get("role"), "Models": ", ".join(u["models"]), "Calls": u["calls"],
                  "Cost per call": f"${u['cost'] / u['calls']:.4f}" if u["calls"] else None,
                  "Prompt tokens": num(u["prompt_tokens"]), "Cached prompt tokens": num(u["cached_tokens"]),
                  "Completion tokens": num(u["completion_tokens"]),
                  "Reasoning tokens": num(u["reasoning_tokens"]),
                  "Failed calls": u.get("failed_calls"), "Fallback answers": u.get("fallbacks"),
                  "Retries at lower effort": u.get("effort_fallbacks")}
        cells = "".join(f"<tr><td class='muted'>{esc(k)}</td><td>{esc(v)}</td></tr>"
                        for k, v in detail.items() if v is not None)
        role = f" <span class='muted'>({esc(u['role'])})</span>" if u.get("role") else ""
        rows.append(f"<details class='usage'><summary><span class='who'>{who}{role}</span>"
                    f"<span class='model'>{esc(', '.join(short_model(m) for m in u['models']) or '?')}</span>"
                    f"<span class='cost'>${u['cost']:.4f}</span><span class='muted'>{u['calls']} calls</span>"
                    f"</summary><table>{cells}</table></details>")
    total = sum(u["cost"] for u in usage)
    rows.append(f"<div class='usage total'><span class='who'>Total</span><span class='model'></span>"
                f"<span class='cost'>${total:.4f}</span>"
                f"<span class='muted'>{sum(u['calls'] for u in usage)} calls</span></div>")
    return "<div class='muted'>Cost by player (USD), click a row for calls and tokens</div>" + "".join(rows)


ICONS = Path(__file__).parent / "roles" / "icons"  # <role-slug>.svg; generic.svg for roles without one


def icon_slug(role: str) -> str:
    """The icon file name for a role, e.g. "Ex-Con" -> "ex-con", "Vanilla Villager" -> "vanilla-villager"."""
    slug = re.sub(r"[^a-z0-9]+", "-", role.lower()).strip("-")
    return slug if (ICONS / f"{slug}.svg").exists() else "generic"


def name_span(name: str, role: str) -> str:
    """A player's (escaped) name colored by faction, with their role's icon and, on hover, the role's name,
    faction and one-line summary."""
    info = ROLES.get(role)
    hover = f"{role} ({faction_of(role)})" + (f": {info.summary}" if info and info.summary else "")
    return f"<span class='n {faction_of(role)} ic i-{icon_slug(role)}' title='{esc(hover)}'>{esc(name)}</span>"


def icons_css() -> str:
    """CSS rules giving each role class its icon, inlined as data URIs (all of them, about 25 KB) so the page
    stays one file. Icons come from the repo's roles/icons/, so every log shows the same icons until those
    files change."""
    rules = []
    for path in sorted(ICONS.glob("*.svg")):
        slug, svg = path.stem, " ".join(path.read_text(encoding="utf-8").split())
        rules.append(f".i-{slug} {{ --icon:url(\"data:image/svg+xml,{urllib.parse.quote(svg)}\"); }}")
    return "\n".join(rules)


class Namer:
    """Escapes text and wraps player names in spans colored by faction, with their role's icon."""

    def __init__(self, roles: dict[str, str]):
        self.spans = {n: name_span(n, role) for n, role in roles.items()}
        names = sorted(roles, key=len, reverse=True)
        self.pattern = re.compile(r"\b(" + "|".join(map(re.escape, names)) + r")\b") if names else None

    def __call__(self, text: str) -> str:
        escaped = esc(text)
        if not self.pattern:
            return escaped
        return self.pattern.sub(lambda m: self.spans[m[1]], escaped)

    def names_in(self, text: str) -> set[str]:
        return set(self.pattern.findall(text)) if self.pattern else set()


def is_phase_start(r: dict) -> bool:
    if "cat" in r:
        return r["cat"] == "phase"
    t = r["text"]  # logs from before events had categories
    return t.startswith(("Day ", "Night ")) and t.endswith("begins.")


def puppeted(r: dict) -> str:
    return f" (puppeted by {r['puppeteer']})" if r.get("puppeteer") else ""


def classify(r: dict) -> tuple[str, str, str]:
    """(category, badge text, body text) for an event, from the category and fields that
    state.Game.emit() logs."""
    if "cat" not in r:
        return classify_legacy(r)
    cat, t, vis = r["cat"], r["text"], r["visible_to"]
    match cat:
        case "chat":
            return "chat", "", f"{r['speaker']}{puppeted(r)}: {r['message']}"
        case "pm":
            return "pm", "PM", f"{r['speaker']}{puppeted(r)} → {r['to']}: {r['message']}"
        case "yak":
            return "yak", "Yakuza chat", f"{r['speaker']}: {r['message']}"
        case "result":
            return "result", f"Result → {', '.join(vis)}", r["message"]
        case "claim":
            return "claim", "Claim", f"{r['speaker']}{puppeted(r)}: {r['claim']}"
        case "announcement":
            return "result", "Announcement", r["message"]
        case "death" | "nom" | "vote":
            return cat, CATEGORY_LABELS[cat], t
    return "system", "" if vis == "all" else f"→ {', '.join(vis)}", t


def classify_legacy(r: dict) -> tuple[str, str, str]:
    """classify() for logs written before events had categories: guesses from the text."""
    t, vis = r["text"], r["visible_to"]
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
    records, unreadable = read_records(jsonl_path)
    roles: dict[str, str] = {}
    models: dict[str, str] = {}
    name = Namer({})
    alive: list[str] = []  # in seat order; shown at the start of each Day
    alive_order: list[str] = []  # every player in seat order: the votes tables' rows
    out: list[str] = []
    phase_start: int | None = None  # index in out of the open phase's opening tag
    errors: list[tuple[str, dict]] = []  # (anchor id, record) of each GameLog.error record
    votes: list[dict] = []  # every "vote" record, for the whole-game table at the top
    day_votes: list[dict] = []  # the open phase's, for its table at the end of the phase
    last_call: dict[str, dict] = {}  # player -> their latest player_call, whose reason explains what they say next
    explained: set[int] = set()  # ids of the calls already shown next to a message (once each, on its first)

    def end_phase() -> None:
        if phase_start is None:
            return
        # rough height for content-visibility until the phase is drawn: collapsed calls are one line,
        # other text wraps at about 110 characters
        if day_votes:
            out.append(votes_html(day_votes, name, alive_order, "Votes this Day"))
            day_votes.clear()
        px = 40
        for part in out[phase_start + 1:]:
            if part.startswith(("<details class='call'", "<details class='votes'")):
                px += 26
            else:
                part = re.sub(r"<details class='why'>.*?</details>(</details>)?", "", part)  # collapsed
                text = re.sub(r"<[^>]+>", "", part.replace("<tr", "\n<tr").replace("<div", "\n<div"))
                px += 23 * sum(1 + len(ln) // 110 for ln in text.strip("\n").split("\n"))
        out[phase_start] = out[phase_start].replace("<details ", f"<details style='contain-intrinsic-size:"
                                                                f"auto {px}px' ", 1)
        out.append("</details>")

    def start_phase(title: str) -> None:
        nonlocal phase_start
        end_phase()
        cls = "night" if title.startswith("Night") else ""
        phase_start = len(out)
        out.append(f"<details class='phase {cls}' open><summary>{esc(title)}</summary>")

    def line(category: str, badge: str, text: str, who: Iterable[str] = (), body_html: str | None = None,
             extra: str = "") -> None:
        """One event line. who: players it involves besides those named in text (the player filter's data-p)."""
        b = f"<span class='badge'>{esc(badge)}</span>" if badge else ""
        out.append(f"<div class='ev {category}'{involves(name.names_in(text) | set(who))}>{b}"
                   f"{name(text) if body_html is None else body_html}{extra}</div>")

    def why(r: dict) -> str:
        """The reason (and thinking) behind a player's message, claim or nomination, from the call that wrote
        it: the writer's latest call. Shown once per call, next to the first thing it said."""
        call = last_call.get(r.get("puppeteer") or r.get("speaker") or "")
        if not call or id(call) in explained:
            return ""
        explained.add(id(call))
        o = call.get("output") or {}
        reason = o.get("reason") or o.get("thoughts")  # "thoughts" in LOG_VERSION 22 and earlier
        if not reason and not call.get("reasoning"):
            return ""
        return ("<details class='why'><summary title='Why: the private reason and thinking behind this turn'>"
                "why</summary>" + (f"<div>{name(reason)}</div>" if reason else "")
                + (f"<details class='thinking'><summary>Model's thinking</summary><pre>{esc(call['reasoning'])}</pre>"
                   "</details>" if call.get("reasoning") else "") + "</details>")

    for r in records:
        k = r["kind"]
        if r.get("alert"):  # GameLog.error: shown where it happened and listed at the top
            anchor = f"error-{len(errors)}"
            errors.append((anchor, r))
            details = {f: v for f, v in r.items() if f not in ("t", "kind", "alert", "error", "traceback")}
            out.append(f"<div class='ev error' id='{anchor}'{involves([r['player']] if r.get('player') else [])}>"
                       f"<span class='badge'>Error: {esc(k)}</span>"
                       f"{name(r['error'])}" + (f"<details class='call'><summary>Details</summary>"
                                                f"{pre('Fields', details)}{pre('Traceback', r.get('traceback'))}"
                                                "</details>" if details or r.get("traceback") else "") + "</div>")
        elif k == "setup":
            roles = {p["name"]: p["role"] for p in r["players"]}
            models = {p["name"]: short_model(p["model"]) for p in r["players"]}
            name = Namer(roles)
            alive = [p["name"] for p in sorted(r["players"], key=lambda p: p["seat"])]
            alive_order = list(alive)
            rows = "".join(f"<tr><td>{name(p['name'])}</td><td>{p['seat'] + 1}</td><td>{esc(p['role'])}</td>"
                           f"<td>{esc(p['model'])}</td><td class='muted'>{name(str(p.get('status') or ''))}</td></tr>"
                           for p in r["players"])
            start_phase("Setup")
            out.append(f"<table><tr><th>Player</th><th>Seat</th><th>Role</th><th>Model</th><th></th></tr>"
                       f"{rows}</table><div class='muted'>Katana starts with {name(str(r.get('katana')))}</div>")
        elif k == "tips":
            files = tips_files(r)
            out.append(f"<div class='muted'>Tips from past games given to: {esc(', '.join(r['players']) or 'nobody')}"
                       "</div>")
            for who, file in files.items():
                shown = (player_view(r["texts"][file]) if "texts" in r else r["shown"].get(who, "") if "shown" in r
                         else player_view(r.get("text", "")))  # LOG_VERSION 11 had one text
                out.append(f"<details class='call'><summary>Tips for {name(who)} ({esc(roles.get(who, '?'))}, "
                           f"{esc(models.get(who, '?'))}): {esc(file)}</summary><pre>{esc(shown)}</pre></details>")
        elif k == "event":
            if is_phase_start(r):
                start_phase(r["text"].removesuffix(" begins."))
                if r["text"].startswith("Day "):  # night deaths are already logged, though revealed after this
                    line("system", f"Alive ({len(alive)})", ", ".join(alive) or "nobody")
                continue
            if r.get("cat") == "claim" and blank(r["claim"]):
                continue  # "null" meant no change (shown in logs from before a592f5f)
            if r.get("cat") == "death" and (m := re.match(r"(\w+) was the Executioner.* leave the game", r["text"])):
                alive = [n for n in alive if n != m[1]]  # LOG_VERSION 33 and earlier had no "left" record
            category, badge, body = classify(r)
            vis = r["visible_to"]
            line(category, badge, body, who=[] if vis == "all" else vis,
                 extra=why(r) if r.get("cat") in ("chat", "pm", "yak", "claim") else "")
        elif k in ("death", "left"):
            alive = [n for n in alive if n != r["player"]]
        elif k == "claim":
            line("system", "Claim", f"{r['player']}: {r['claim']}")
        elif k == "vote":
            votes.append(r)
            day_votes.append(r)
        elif k == "player_call":
            last_call[r["player"]] = r
            o = dict(r.get("output") or {})
            thoughts = o.pop("thoughts", "")  # LOG_VERSION 22 and earlier
            reason = o.pop("reason", "")  # LOG_VERSION 24+
            notepad = ""
            if "notepad_before" in r:  # LOG_VERSION 9+
                o.pop("notepad", None)
                before, after = r["notepad_before"] or "(empty)", r["notepad_after"] or "(empty)"
                notepad = (pre("Notepad before", before)
                           + pre("Notepad after", "(unchanged)" if after == before else after))
            first_line = r["task"].split("\n")[0]
            summary = (f"{name(r['player'])} ({esc(roles.get(r['player'], '?'))}, "
                       f"{esc(r['model'].split('/')[-1])}) · {esc(first_line[:90])} · ${r.get('cost', 0):.4f}")
            out.append(f"<details class='call'{involves([r['player']])}><summary>{summary}</summary>"
                       + pre("Reasoning (model's thinking)", r.get("reasoning"), REASONING_HINT)
                       + pre("Thoughts (private field)", thoughts) + pre("Reason (private field)", reason, REASON_HINT)
                       + pre("Output", o) + notepad
                       + pre("Task prompt", r["task"]) + pre("Usage", r.get("usage")) + "</details>")
        elif k == "moderator_call":
            calls = ", ".join(c["function"]["name"] for c in r.get("tool_calls") or []) or "no tool call"
            out.append(f"<details class='call'><summary>Moderator ({esc(r['model'].split('/')[-1])}) → "
                       f"{esc(calls)} · ${r.get('cost', 0):.4f}</summary>"
                       + pre("Reasoning", r.get("reasoning"), REASONING_HINT) + pre("Content", r.get("content"))
                       + pre("Tool calls", [{"name": c["function"]["name"],
                                             "args": tool_args(c["function"].get("arguments"))}
                                            for c in r.get("tool_calls") or []])
                       + pre("Usage", r.get("usage")) + "</details>")
        elif k == "moderator_tool":
            if r["name"] == "end_phase":
                line("hidden", "Moderator summary", str(tool_args(r["args"]).get("summary", "")))
            else:
                out.append(f"<details class='call'><summary>Tool {esc(r['name'])} result</summary>"
                           + pre("Args", r.get("args")) + pre("Result", r.get("result")) + "</details>")
        elif k == "night_actions":
            rows = "".join(f"<div>{name(n)} ({esc(r['roles'].get(n))}): {name(describe_action(a))}</div>"
                           for n, a in r["actions"].items())
            line("hidden", "Night actions", "", who=r["actions"], body_html=rows)
        elif k in ("katana", "revenge"):
            line("hidden", "Katana" if k == "katana" else "Revenge", text_line(r) or "")
        elif k == "night_check":
            line("hidden", "Night check", describe_check(r))
        elif k == "visits":  # the moderator's record_visits (LOG_VERSION 33+)
            line("hidden", "Visits", ", ".join(f"{a} → {b}" for a, b in r["visits"]) or "none")
        elif k == "night_effects_undone":
            line("hidden", "Undone", f"{r['player']} survived the night, so their {' and '.join(r['undone'])} "
                 "change was undone")
        elif k == "moderator_flag":
            line("hidden", "Moderator flag", r["issue"])
        elif k == "player_feedback":
            line("hidden", f"Feedback from {r['player']}", r["feedback"], who=[r["player"]])
        elif k == "resume":
            line("system", "Resumed", f"The game continued from the checkpoint at the start of {r.get('at', 'day')} "
                 f"{r['day']}; {r.get('cut_records', 0)} log records after it were dropped.")
        elif k == "debrief" and r["who"] == "moderator":  # players' debriefs are their player_call records
            out.append(f"<details class='call'><summary>Moderator ({esc(short_model(r['model']))}) debrief · "
                       f"${r.get('cost', 0):.4f}</summary>{pre('Answers', r['answers'])}</details>")
        elif k == "strategy_review":
            line("hidden", "Strategy review", r["summary"])
            out.append(f"<details class='call'><summary>Moderator ({esc(short_model(r['model']))}) lessons · "
                       f"${r.get('cost', 0):.4f}</summary>{pre('Lessons', r.get('lessons'))}</details>")
        elif k == "review":
            for i in r["issues"]:
                line("hidden", f"Review: {i.get('severity', '?')}, {i.get('kind', '?')}", i.get("description", ""))
            if not r["issues"]:
                line("hidden", "Review", "No issues found.")
        elif k in ("budget_warning", "message_dropped", "nomination_dropped", "player_error", "moderator_error"):
            out.append(f"<details class='call'{involves([r['player']] if r.get('player') else [])}><summary>"
                       f"{esc(k.replace('_', ' '))}: "
                       f"{esc(r.get('player', ''))}</summary>{pre('Details', r)}</details>")
        elif k == "section":  # post-game steps (feedback.POST_GAME_SECTIONS)
            start_phase(r["title"])
        elif k == "result":
            start_phase("Game over")
            line("result", "Winners", ", ".join(r["winners"] or []) or "nobody")
            if "usage" in r:  # LOG_VERSION 10+
                out.append(usage_html(r["usage"]))
            else:
                out.append(pre("Cost by model (USD)", r.get("cost")))
    end_phase()

    legend = "".join(f"<span class='badge {c}'>{esc(label)}</span>" for c, label in CATEGORY_LABELS.items())
    legend += ("<span class='n Village'>Village</span> <span class='n Yakuza'>Yakuza</span> "
               "<span class='n Neutral'>Neutral</span>")
    title = f"Mafia game {jsonl_path.stem}"
    focus_options = "".join(f"<option>{esc(n)}</option>" for n in alive_order)
    page = (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' "
            f"content='width=device-width, initial-scale=1'><title>{esc(title)}</title>"
            f"<style>{CSS}{icons_css()}</style>"
            f"</head><body><h1>{esc(title)}</h1><div class='legend'>{legend}</div><div class='controls'>"
            f"<label><input type='checkbox' id='showcalls' checked> Model details</label>"
            f"<label><input type='checkbox' id='showhidden' checked> Hidden night info</label>"
            f"<label><input type='checkbox' id='showicons' checked> Role icons</label>"
            f"<span><button id='expand'>Expand all</button> <button id='collapse'>Collapse all</button></span>"
            f"<label>Player <select id='focus'><option value=''>everyone</option>{focus_options}</select></label>"
            f"<span class='muted'>Untick the first two to read it like a player would.</span></div>"
            f"{errors_html(errors, unreadable)}"
            f"{votes_html(votes, name, alive_order, 'Votes (whole game)', show_day=True)}"
            f"{''.join(out)}<script>{JS}</script></body></html>")
    html_path = jsonl_path.with_suffix(".html")
    html_path.write_text(page, encoding="utf-8", errors="replace")
    return html_path


def involves(names: Iterable[str]) -> str:
    """The data-p attribute the player filter reads: the players a line or call involves."""
    return f" data-p='{esc(' '.join(sorted(names)))}'" if names else ""


def votes_html(votes: list[dict], name: Namer, seats: list[str], title: str, show_day: bool = False) -> str:
    """A collapsed table of vote records: a row per voter (in seat order), a column per vote. Yes and Guilty
    are ✓, No and Innocent are ✗, blank if they didn't vote (dead, or the nominee of a trial ...)."""
    if not votes:
        return ""
    voters = [n for n in seats if any(n in v["votes"] for v in votes)]
    heads, outcomes = [], []
    for v in votes:
        when = f"D{v['day']} " if show_day else ""
        stage = "trial" if v["stage"] == "trial" else "nom."
        heads.append(f"<th title='{esc(stage)} of {esc(v['nominee'])}, nominated by {esc(v.get('nominator'))}"
                     f"{' (prosecuted)' if v.get('prosecuted') else ''}'><span class='muted'>{when}{stage}</span>"
                     f"<br>{name(v['nominee'])}</th>")
        outcomes.append(f"<td class='muted'>{esc(v['outcome'])}</td>")

    def cell(v: dict, voter: str) -> str:
        if voter not in v["votes"]:
            return "<td></td>"
        weight = (v.get("weights") or {}).get(voter, 1)
        mark = ("✓" if v["votes"][voter] else "✗") + (f"×{weight}" if weight != 1 else "")
        return f"<td class='{'yes' if v['votes'][voter] else 'no'}'>{mark}</td>"
    rows = "".join(f"<tr><th>{name(n)}</th>{''.join(cell(v, n) for v in votes)}</tr>" for n in voters)
    trials = sum(v["stage"] == "trial" for v in votes)
    return (f"<details class='votes'><summary>{esc(title)}: {len(votes) - trials} nomination vote(s), "
            f"{trials} trial(s). ✓ Yes/Guilty, ✗ No/Innocent</summary><div class='scroll'><table>"
            f"<tr><th></th>{''.join(heads)}</tr>{rows}<tr><th class='muted'>Outcome</th>{''.join(outcomes)}</tr>"
            "</table></div></details>")


def errors_html(errors: list[tuple[str, dict]], unreadable: int = 0) -> str:
    """The box at the top of the page: how many errors of each kind, and links to the first few of each
    kind per player (the same ones the feedback report lists)."""
    bad_lines = (f"<details class='errors' open><summary>{unreadable} unreadable log line(s) skipped</summary>"
                 "The log has lines that aren't JSON, e.g. half-written when the game was killed.</details>"
                 if unreadable else "")
    if not errors:
        return bad_lines + "<div class='muted no-errors'>No program errors were logged.</div>"
    counts = Counter(r["kind"] for _, r in errors)
    shown: Counter[tuple[str, str]] = Counter()
    items = []
    for anchor, r in errors:
        shown[source := (r["kind"], str(r.get("player", "")))] += 1
        if shown[source] <= 3:
            items.append(f"<li><a href='#{anchor}'>{esc(r['kind'])}</a>: {esc(r['error'][:300])}</li>")
    more = len(errors) - len(items)
    return bad_lines + (f"<details class='errors' open><summary>{len(errors)} error{'s' if len(errors) > 1 else ''}: "
            + esc(", ".join(f"{n} {k}" for k, n in counts.most_common())) + "</summary><ul>" + "".join(items)
            + "</ul>" + (f"<div class='muted'>{more} more like these are marked in red below.</div>" if more else "")
            + "</details>")


def render_text(jsonl_path: Path) -> Path:
    lines = [text_line(r) for r in read_records(jsonl_path)[0]]
    txt_path = jsonl_path.with_suffix(".txt")
    txt_path.write_text("\n".join(line for line in lines if line is not None) + "\n", encoding="utf-8", errors="replace")
    return txt_path


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        p = Path(arg)
        print(render_text(p), render_html(p))
