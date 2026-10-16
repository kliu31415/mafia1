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

import base64
import contextvars
import functools
import gzip
import html
import json
import os
import re
import sys
import urllib.parse
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Iterable, Sequence
from typing import Any

from gamelogs import faction_of, trait_details
from traits import TRAITS
from records import caller_of, read_records
from role_summaries import role_paragraphs
from roles import RETIRED, RETIRED_BY_LABEL, ROLES, log_role, role_info
from texts import blank, describe_action, player_view


def status_text(status: dict | None) -> str:
    """A setup row's status, e.g. "target: Bob; targets: Bob, Carol, Dave"."""
    return "; ".join(f"{k}: {', '.join(map(str, v)) if isinstance(v, list) else v}"
                     for k, v in (status or {}).items())


def via_note(p: dict) -> str:
    """Marks a setup player whose model ran through the Claude Code CLI (LOG_VERSION 47), not the API."""
    return " (via Claude Code)" if p.get("via") == "claude_code" else ""


def phase_ended(r: dict) -> bool:
    """Whether an end_phase tool record ended the phase: the code refuses one with work left (e.g. a held tell), and
    the moderator's later end_phase repeats the summary, which was then shown twice (game_20261016_060619_1008)."""
    return (r.get("result") or {}).get("ok") is not False


def text_line(r: dict) -> str | None:
    k = r["kind"]
    if r.get("alert"):  # GameLog.error
        return f"[ERROR {k}] {r['error']}"
    match k:
        case "setup":
            lines = ["Setup:"] + [f"  {p['name']:<8} seat {p['seat'] + 1:<2} {p['role']:<17} {p['model']}{via_note(p)}"
                                  + (f"  trait: {traits_text(p['traits'], p.get('trait_details'))}"
                                     if p.get("traits") else "")
                                  + (f"  ({status_text(p['status'])})" if p.get("status") else "") for p in r["players"]]
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
            if not phase_ended(r):  # refused, so a later end_phase writes the summary that counts
                return f"[Moderator end_phase refused] {(r.get('result') or {}).get('note', '')}"
            return f"[Moderator summary] {summary}"
        case "briefing":
            return f"[Setup note to players] {r['setup_note']}"
        case "claim":
            return f"[Claim] {r['player']}: {r['claim']}"
        case "moderator_flag":
            return f"[Moderator flag] {r['issue']}"
        case "player_feedback":
            return f"[Feedback from {r['player']}] {r['feedback']}"
        case "vote" if r.get("secret"):  # players saw only the totals; the log keeps who voted which way
            yes, no = ("Guilty", "Innocent") if r["stage"] == "trial" else ("Yes", "No")
            names = {v: [n for n, x in r["votes"].items() if x is v] for v in (True, False)}
            return (f"[Secret {r['stage']} votes on {r['nominee']}] {yes} - {', '.join(names[True]) or 'nobody'}; "
                    f"{no} - {', '.join(names[False]) or 'nobody'}")
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
/* someone saying something: the speaker as a tinted label, the message beside it (wrapped lines stay right of it) */
.ev.said { display:flex; align-items:baseline; gap:8px; }
.ev.said .badge { flex:none; margin-right:0; }
.ev.said .who { flex:none; min-width:6.5em; padding:1px 7px; border-radius:5px; white-space:nowrap;
                background:color-mix(in srgb, var(--c) 16%, transparent); }
.ev.said .msg { flex:1; min-width:0; }
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
label.apicost { display:block; margin:4px 0; } .costs .cost.api { display:none; }
.costs:has(label.apicost input:checked) .cost.api { display:inline-block; }
.costs:has(label.apicost input:checked) .cost.paid { display:none; }
body.no-calls details.call { display:none; } body.no-hidden .ev.hidden { display:none; }
body.no-hidden .ev.error { display:none; }
body.no-calls details.why { display:none; }
body.hide-chat .ev.chat, body.hide-pm .ev.pm, body.hide-yak .ev.yak, body.hide-nom .ev.nom, body.hide-vote .ev.vote,
body.hide-death .ev.death, body.hide-claim .ev.claim, body.hide-result .ev.result, body.hide-hidden .ev.hidden, body.hide-system .ev.system { display:none; }
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
#jump { flex-basis:100%; display:flex; flex-wrap:wrap; gap:2px 4px; font-size:12.5px; }
#jump a { padding:1px 6px; border-radius:4px; text-decoration:none; color:var(--fg); border:1px solid var(--line); }
#jump a.night { color:var(--c-hidden); } #jump a.here { background:var(--call); border-color:var(--muted); }
#jump .deaths { color:var(--c-death); margin-left:2px; }
details.phase { scroll-margin-top:110px; }
.legend .badge[data-cat] { cursor:pointer; user-select:none; } .legend .badge.off { opacity:.35; text-decoration:line-through; }
body.no-hidden details.card { display:none; } details.card td { text-align:left; vertical-align:top; }
details.card td:first-child { white-space:nowrap; }
/* roster panel: beside the log on wide screens, a corner overlay on narrow ones (off by default there) */
#roster { display:none; font-size:12.5px; background:var(--bg); border:1px solid var(--line); border-radius:8px;
          padding:6px 10px; overflow:auto; z-index:2; }
body.roster-on #roster { display:block; position:fixed; right:8px; bottom:8px; width:320px; max-height:50vh; }
@media (min-width: 1400px) {
  body.roster-on { margin-left:max(16px, calc(50vw - 670px)); }
  body.roster-on #roster { top:12px; bottom:auto; right:max(16px, calc(50vw - 670px)); max-height:calc(100vh - 24px); }
}
#roster .p { padding:3px 0; border-bottom:1px solid var(--line); }
#roster .p.dead .n { text-decoration:line-through; opacity:.6; } #roster .claim { padding-left:24px; }
#roster .truth { font-size:10.5px; font-weight:700; padding:0 4px; border-radius:3px; margin-right:4px; }
#roster .truth.false { color:var(--c-death); border:1px solid var(--c-death); }
#roster .truth.true { color:var(--muted); border:1px solid var(--line); }
"""

JS = """
// Keeps the line at the top of the window (just under the sticky bar) where it is while a control shows or hides
// lines: change() runs, then the page scrolls back so that line, or the next one still shown, doesn't move.
const keepPlace = change => {
  const below = document.querySelector('.controls').getBoundingClientRect().bottom;
  const lines = document.querySelectorAll('details.phase > *, body > details:not(.phase)');
  const near = [];
  for (const el of lines) {
    if (!el.getClientRects().length) continue;
    const r = el.getBoundingClientRect();
    if (r.bottom <= below) continue;
    near.push([el, r.top]);
    if (r.top > innerHeight) break;
  }
  change();
  const kept = near.find(([el]) => el.getClientRects().length);
  if (kept) scrollBy(0, kept[0].getBoundingClientRect().top - kept[1]);
};
const toggle = (id, cls) => {
  const box = document.getElementById(id);
  const apply = () => document.body.classList.toggle(cls, !box.checked);
  box.addEventListener('change', () => keepPlace(apply)); apply();
};
toggle('showcalls', 'no-calls');
toggle('showhidden', 'no-hidden');
toggle('showicons', 'no-icons');
// Model details and reasons are packed (Packer): gzipped together into one base64 blob, unpacked the first time
// one is opened and put in place as each is opened.
const zData = document.getElementById('z-data');
let zParts = null, zLoading = null;
const unpack = () => zLoading ??= (async () => {
  const bin = atob(zData.textContent), bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);  // Uint8Array.from(..., map) is 15x slower
  const text = await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).text();
  zParts = JSON.parse(text);
})();
const fill = d => {
  if (d.dataset.z === undefined || !zParts) return;
  d.querySelector(':scope > summary').insertAdjacentHTML('afterend', zParts[+d.dataset.z]);
  delete d.dataset.z;
};
document.addEventListener('toggle', e => {  // toggle doesn't bubble, but a capturing listener sees it
  const d = e.target;
  if (d.open && d.dataset && d.dataset.z !== undefined) unpack().then(() => fill(d));
}, true);
document.getElementById('expand').addEventListener('click', async () => {
  if (zData) await unpack();
  keepPlace(() => document.querySelectorAll('details.call').forEach(d => { fill(d); d.open = true; }));
});
document.getElementById('collapse').addEventListener('click', () => keepPlace(() =>
  document.querySelectorAll('details.call').forEach(d => d.open = false)));
// Player filter: show only the lines and calls that involve the chosen player (their data-p).
const focus = document.getElementById('focus');
const applyFocus = () => {
  const who = focus.value;
  document.querySelectorAll('details.phase > .ev, details.phase > details.call').forEach(el =>
    el.classList.toggle('focus-hide', who !== '' && !(el.dataset.p || '').split(' ').includes(who)));
};
focus.addEventListener('change', () => keepPlace(applyFocus)); applyFocus();
// Legend badges hide or show their category's lines.
document.querySelectorAll('.legend .badge[data-cat]').forEach(b => b.addEventListener('click', () => keepPlace(() =>
  b.classList.toggle('off', document.body.classList.toggle('hide-' + b.dataset.cat)))));
// Jump bar: marks the phase at the top of the window.
const jumps = [...document.querySelectorAll('#jump a')].map(a => [a, document.getElementById(a.hash.slice(1))]);
let jumpPending = false;
const markPhase = () => {
  jumpPending = false;
  let here = jumps[0];
  for (const j of jumps) if (j[1].getBoundingClientRect().top < 120) here = j;
  jumps.forEach(j => j[0].classList.toggle('here', j === here));
};
addEventListener('scroll', () => { if (!jumpPending) { jumpPending = true; requestAnimationFrame(markPhase); } },
                 { passive: true });
if (jumps.length) markPhase();
// Phases off screen have estimated heights until drawn (content-visibility), so a jump lands a little off at
// first: jump again once the page around it has been drawn.
jumps.forEach(([a, phase]) => a.addEventListener('click', e => {
  e.preventDefault();
  history.replaceState(null, '', a.hash);
  phase.scrollIntoView();
  setTimeout(() => phase.scrollIntoView(), 120);
  setTimeout(() => phase.scrollIntoView(), 400);
}));
// Roster panel: shows the snapshot whose marker (i.snap) is the last one above the top of the window.
const rosterData = document.getElementById('roster-data');
if (rosterData) {
  const R = JSON.parse(rosterData.textContent), aside = document.getElementById('roster');
  const marks = [...document.querySelectorAll('i.snap')];
  const rosterBox = document.getElementById('showroster');
  rosterBox.checked = window.innerWidth >= 1400;
  rosterBox.addEventListener('change', () =>
    keepPlace(() => document.body.classList.toggle('roster-on', rosterBox.checked)));
  document.body.classList.toggle('roster-on', rosterBox.checked);
  const top = el => {  // a marker in a collapsed phase has no box: use its phase's
    const r = el.getBoundingClientRect();
    return r.top || r.left ? r.top : el.closest('details.phase').getBoundingClientRect().top;
  };
  let shown = -1;
  const render = i => {
    if (i === shown) return;
    shown = i;
    const s = R.snaps[i];
    aside.innerHTML = "<div class='muted'>Roster, as of the part of the log at the top of the window</div>" +
      R.players.map(p => {
        const [alive, death, claim, truth] = s[p.n];
        const mark = truth ? `<span class='truth ${truth}' title='${truth === 'false' ?
          'names a role other than their own' : 'names their own role'}'>${truth === 'false' ? 'false' : 'true'}</span>` : '';
        return `<div class='p ${alive ? '' : 'dead'}'>${p.html} <span class='muted'>${p.model}${death ? ' · ' + death : ''}</span>` +
          (claim ? `<div class='claim'>${mark}${claim}</div>` : '') + '</div>';
      }).join('');
  };
  const update = () => {
    let lo = 0, hi = marks.length - 1, best = 0;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (top(marks[mid]) < 60) { best = mid; lo = mid + 1; } else hi = mid - 1;
    }
    render(+marks[best].dataset.snap);
  };
  let pending = false;
  addEventListener('scroll', () => { if (!pending) { pending = true; requestAnimationFrame(() => { pending = false; update(); }); } },
                   { passive: true });
  update();
}
"""

CATEGORY_LABELS = {"chat": "Chat", "pm": "PM", "yak": "Yakuza chat", "nom": "Nomination", "vote": "Vote",
                   "death": "Death", "claim": "Claim", "result": "Result", "hidden": "Hidden info", "system": "System"}


def esc(x: Any) -> str:
    return html.escape(str(x))


class Packer:
    """The bulky parts of a page (model details, reasons and thinking), packed: each packed element keeps its summary
    and a data-z index, and its contents go into one gzipped, base64 blob that the page's script unpacks the first
    time one is opened. Packing them together lets gzip use what calls repeat (the same prompts call after call):
    pages shrink to about a third. Browsers decompress gzip natively (DecompressionStream)."""

    def __init__(self) -> None:
        self.parts: list[str] = []

    def details(self, cls: str, summary: str, body: str, attrs: str = "") -> str:
        """<details class=cls> with this summary, its body packed. summary: the whole <summary> element's HTML."""
        if not body:
            return f"<details class='{cls}'{attrs}>{summary}</details>"
        self.parts.append(body)
        return f"<details class='{cls}'{attrs} data-z='{len(self.parts) - 1}'>{summary}</details>"

    def blob(self) -> str:
        if not self.parts:
            return ""
        data = gzip.compress(json.dumps(self.parts, ensure_ascii=False).encode(), mtime=0)  # mtime 0: same page each time
        return f"<script type='application/octet-stream' id='z-data'>{base64.b64encode(data).decode()}</script>"


def unpacked(page: str) -> str:
    """The page with every packed part back in place, as the page's script puts it when opened (tests, debugging)."""
    m = re.search(r"<script type='application/octet-stream' id='z-data'>([^<]*)</script>", page)
    if not m:
        return page
    parts = json.loads(gzip.decompress(base64.b64decode(m[1])))
    page = page[:m.start()] + page[m.end():]
    return re.sub(r" data-z='(\d+)'>(<summary.*?</summary>)", lambda z: f">{z[2]}{parts[int(z[1])]}", page, flags=re.S)


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


def claude_code_costs(records: list[dict]) -> dict[str, float]:
    """What each caller's Claude Code calls (cost $0, on the subscription) would have cost at API list price: the
    CLI's own figure (list_cost_usd), which prices its cache writes at the 1-hour rate (2x input)."""
    costs: dict[str, float] = {}
    for r in records:
        usage = r.get("usage")
        who = caller_of(r)
        if who and isinstance(usage, dict) and usage.get("via") == "claude_code":
            costs[who] = costs.get(who, 0.0) + float(usage.get("list_cost_usd") or 0)
    return costs


def usage_html(usage: list[dict], cc_costs: dict[str, float] | None = None) -> str:
    """The cost table at the end of the HTML view: one expandable row per player, the moderator and
    each post-game step, with its calls and tokens inside. cc_costs (claude_code_costs) adds a checkbox that
    shows the cost with Claude Code calls priced at API rates."""
    cc_costs = {who: c for who, c in (cc_costs or {}).items() if c}

    def num(n: float) -> str:
        return f"{n:,}"

    def cost(paid: float, who: str | None = None) -> str:
        """The paid cost, and with cc_costs also the API-equivalent cost (only one shows, by the checkbox)."""
        api = paid + (cc_costs.get(who, 0.0) if who else sum(cc_costs.values()))
        if not cc_costs:
            return f"<span class='cost'>${paid:.4f}</span>"
        return f"<span class='cost paid'>${paid:.4f}</span><span class='cost api'>${api:.4f}</span>"
    rows = []
    for u in usage:
        who = name_span(u['who'], u['role']) if u.get("role") \
            else esc(u["who"])
        cc = cc_costs.get(u["who"])
        detail = {"Role": u.get("role"), "Models": ", ".join(u["models"]), "Calls": u["calls"],
                  "Cost per call": f"${u['cost'] / u['calls']:.4f}" if u["calls"] else None,
                  "Claude Code calls at API price": f"${cc:.4f}" if cc else None,
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
                    f"{cost(u['cost'], u['who'])}<span class='muted'>{u['calls']} calls</span>"
                    f"</summary><table>{cells}</table></details>")
    total = sum(u["cost"] for u in usage)
    rows.append(f"<div class='usage total'><span class='who'>Total</span><span class='model'></span>"
                f"{cost(total)}<span class='muted'>{sum(u['calls'] for u in usage)} calls</span></div>")
    toggle = ("<label class='apicost'><input type='checkbox'> Include Claude Code calls at API price "
              "<span class='muted'>(they cost $0 on the subscription; this is Claude Code's own list-price figure, "
              "with cache writes at the 1-hour rate)</span></label>") if cc_costs else ""
    return ("<div class='costs'><div class='muted'>Cost by player (USD), click a row for calls and tokens</div>"
            + toggle + "".join(rows) + "</div>")


ICONS = Path(__file__).parent / "roles" / "icons"  # <role-slug>.svg; generic.svg for roles without one


def trait_slug(trait: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", trait.lower()).strip("-")


def icon_slug(role: str) -> str:
    """The icon file name for a role, e.g. "Ex-Con" -> "ex-con", "Vanilla Villager" -> "vanilla-villager"; a retired
    role's log_role label gets its icon from roles/icons/retired/ ("r-" + its file name)."""
    if role in RETIRED_BY_LABEL:
        return "r-" + Path(RETIRED_BY_LABEL[role].icon).stem
    slug = re.sub(r"[^a-z0-9]+", "-", role.lower()).strip("-")
    return slug if role in ROLES and (ICONS / f"{slug}.svg").exists() else "generic"


@dataclass
class LogContext:
    """What a log says about its own roles and traits (setup role_info and trait_info, log version 51 on), and its
    version, for reading role names that have since been retired or reused (roles.log_role)."""
    version: int = 10 ** 9  # no log: every role name means today's role
    roles: dict[str, dict] = field(default_factory=dict)
    traits: dict[str, dict] = field(default_factory=dict)
    details: dict[str, dict[str, str]] = field(default_factory=dict)  # gamelogs.trait_details


# The log being rendered (render_html sets it), so name_span describes roles as that game had them.
CONTEXT: contextvars.ContextVar[LogContext | None] = contextvars.ContextVar("log_context", default=None)


def context() -> LogContext:
    return CONTEXT.get() or LogContext()


@functools.cache
def current_paragraphs() -> dict[str, str]:
    return role_paragraphs()


def role_hover(role: str) -> tuple[str, str]:
    """(faction, hover text) for a role as the log being rendered had it: its own description when it has one
    (log version 51 on), else the role list (retired roles included), plus the role's rules paragraph when that
    differs from today's (or the role is gone)."""
    ctx = context()
    label = log_role(role, ctx.version)
    own = ctx.roles.get(role)
    if own:
        faction = faction_of(role, ctx.roles)
        summary, rules = own.get("summary", ""), own.get("rules", "")
    else:
        info = role_info(label)
        faction, summary = faction_of(label), info.summary if info else ""
        rules = RETIRED_BY_LABEL[label].rules if label in RETIRED_BY_LABEL else ""
    hover = f"{label} ({faction})" + (f": {summary}" if summary else "")
    if rules and (label in RETIRED_BY_LABEL or rules != current_paragraphs().get(label)):
        hover += f"\n\nRules in this game{' (role since retired)' if label in RETIRED_BY_LABEL else ''}:\n" + rules
    return faction, hover


def traits_text(traits: Iterable[str], details: dict[str, str] | None = None) -> str:
    """A player's traits, each followed by what it was dealt with (gamelogs.trait_details): "Disguised as Sheriff"."""
    return ", ".join(f"{t} {details[t]}" if details and details.get(t) else t for t in traits)


def name_span(name: str, role: str, traits: list[str] | tuple[str, ...] = ()) -> str:
    """A player's (escaped) name colored by faction, with their role's icon (a corner mark for each trait,
    traits.py) and, on hover, the role's name, faction and one-line summary, then each trait's."""
    faction, hover = role_hover(role)
    own, details = context().traits, context().details.get(name, {})
    hover += "".join(f"\nTrait: {traits_text([t], details)}"
                     + (f": {own[t]['hover']}" if t in own else f": {TRAITS[t].hover}" if t in TRAITS else "")
                     for t in traits)
    shown = [t for t in traits if t in TRAITS][:len(CORNERS)]
    marks = (f" tn{len(shown)}" if shown else "") + "".join(f" t{i}-{trait_slug(t)}" for i, t in enumerate(shown))
    label = log_role(role, context().version)
    return (f"<span class='n {faction} ic i-{icon_slug(label)}{marks}' title='{esc(hover)}'>"
            f"{esc(name)}</span>")


def icons_css(trait_sets: Iterable[Sequence[str]] = ()) -> str:
    """CSS rules giving each role class its icon, inlined as data URIs (all of them, about 25 KB) so the page
    stays one file. Icons come from the repo's roles/icons/, so every log shows the same icons until those
    files change. trait_sets: the players' traits, for their marks."""
    rules = []
    for path in [*sorted(ICONS.glob("*.svg")), *sorted((ICONS / "retired").glob("*.svg"))]:
        slug = ("r-" if path.parent.name == "retired" else "") + path.stem
        svg = " ".join(path.read_text(encoding="utf-8").split())
        rules.append(f".i-{slug} {{ --icon:url(\"data:image/svg+xml,{urllib.parse.quote(svg)}\"); }}")
    # A trait's mark sits in a corner of the icon, over the role's icon: the first trait top right, then top left,
    # bottom right, bottom left. Each set of traits a player has gets one rule (a CSS background can't be added to
    # by a second class), keyed by its classes in name_span's order. Only the game's own sets: a rule for every
    # possible set grew with the number of traits to the fourth power (250 MB pages at 22 traits, Oct 13 2026).
    for combo in sorted({tuple(t for t in ts if t in TRAITS)[:len(CORNERS)] for ts in trait_sets} - {()}):
        layers = "".join(f"url(\"data:image/svg+xml,{urllib.parse.quote(' '.join(TRAITS[t].mark.split()))}\") "
                         f"{corner}/45% no-repeat, " for t, corner in zip(combo, CORNERS))
        rules.append(f".n.ic.tn{len(combo)}{''.join(f'.t{i}-{trait_slug(t)}' for i, t in enumerate(combo))}::before "
                     f"{{ background:{layers}var(--icon) center/80% no-repeat, var(--tint); }}")
    return "\n".join(rules)


CORNERS = ("top right", "top left", "bottom right", "bottom left")


class Namer:
    """Escapes text and wraps player names in spans colored by faction, with their role's icon."""

    def __init__(self, roles: dict[str, str], traits: dict[str, list[str]] | None = None):
        self.spans = {n: name_span(n, role, (traits or {}).get(n, ())) for n, role in roles.items()}
        names = sorted(roles, key=len, reverse=True)
        self.pattern = re.compile(r"\b(" + "|".join(map(re.escape, names)) + r")\b") if names else None

    def __call__(self, text: str) -> str:
        escaped = esc(text)
        if not self.pattern:
            return escaped
        return self.pattern.sub(lambda m: self.spans[m[1]], escaped)

    def names_in(self, text: str) -> set[str]:
        return set(self.pattern.findall(text)) if self.pattern else set()


SAID = ("chat", "pm", "yak", "claim")  # categories whose text is "speaker: message" (classify)


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
        case "pm":  # a Confidant's hidden PM (rules R24): the hidden field since log version 71, the text before
            hidden = r.get("hidden") or t.startswith(f"{r['speaker']} -> {r['to']} (private, hidden")
            body = f"{r['speaker']}{puppeted(r)} → {r['to']}: {r['message']}"
            return "pm", "Hidden PM" if hidden else "PM", body
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
    setup = next((r for r in records if r.get("kind") == "setup"), {})
    CONTEXT.set(LogContext(setup.get("log_version", 1), setup.get("role_info") or {}, setup.get("trait_info") or {},
                           trait_details(records)))
    roles: dict[str, str] = {}
    traits: dict[str, list[str]] = {}
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
    phase_title = ""
    phases: list[dict] = []  # id, title and deaths of each phase, for the jump bar
    nights: dict[int, dict] = {}  # night -> what its summary card shows (night_html)
    roster: dict[str, dict] = {}  # player -> alive, death, claim as of this point in the log
    believed: dict[str, set[str | None]] = {}  # player -> their role, and the role a Roleplayer thinks they have
    snaps: list[dict] = []  # copies of roster, each marked in the page where it starts to hold (the roster panel)
    packer = Packer()

    def call(summary: str, body: str, attrs: str = "") -> str:
        """A model details box: one line until opened, its body packed."""
        return packer.details("call", f"<summary>{summary}</summary>", body, attrs)

    def night(n: int) -> dict:
        return nights.setdefault(n, {"actions": {}, "results": {}, "deaths": [], "katana": None, "check": None,
                                     "visits": None})

    def snap() -> None:
        if roster:
            snaps.append({n: dict(v) for n, v in roster.items()})
            out.append(f"<i class='snap' data-snap='{len(snaps) - 1}'></i>")

    def gone(player: str, how: str) -> None:
        nonlocal alive
        alive = [n for n in alive if n != player]
        if player in roster and roster[player]["alive"]:
            roster[player].update(alive=False, death=how)
            if phases:
                phases[-1]["deaths"] += 1
            snap()

    def end_phase() -> None:
        if phase_start is None:
            return
        if day_votes:
            out.append(votes_html(day_votes, name, alive_order, "Votes this Day"))
            day_votes.clear()
        if phase_title.startswith("Night "):
            out.append(f"\0night {phase_title.split()[1]}\0")  # its card, once its night check has arrived
        # rough height for content-visibility until the phase is drawn: collapsed calls are one line,
        # other text wraps at about 110 characters
        px = 40
        for part in out[phase_start + 1:]:
            if part.startswith("<i class='snap'"):
                continue
            if part.startswith(("<details class='call'", "<details class='votes'", "\0night")):
                px += 26
            else:
                part = re.sub(r"<details class='why'.*?</details>", "", part)  # collapsed, its contents packed
                text = re.sub(r"<[^>]+>", "", part.replace("<tr", "\n<tr").replace("<div", "\n<div"))
                px += 23 * sum(1 + len(ln) // 110 for ln in text.strip("\n").split("\n"))
        out[phase_start] = out[phase_start].replace("<details ", f"<details style='contain-intrinsic-size:"
                                                                f"auto {px}px' ", 1)
        out.append("</details>")

    def start_phase(title: str) -> None:
        nonlocal phase_start, phase_title
        end_phase()
        cls = "night" if title.startswith("Night") else ""
        phase_start, phase_title = len(out), title
        anchor = f"phase-{len(phases)}"
        phases.append({"id": anchor, "title": title, "deaths": 0})
        out.append(f"<details class='phase {cls}' id='{anchor}' open><summary>{esc(title)}</summary>")
        snap()

    def line(category: str, badge: str, text: str, who: Iterable[str] = (), body_html: str | None = None,
             extra: str = "") -> None:
        """One event line. who: players it involves besides those named in text (the player filter's data-p)."""
        b = f"<span class='badge'>{name(badge)}</span>" if badge else ""  # e.g. "Result → Alice": names get icons
        cls = category
        if body_html is None and category in SAID and ": " in text:
            # The speaker ("Bob", "Bob → Carol", "Bob (puppeted by Dan)") as a label, the message in its own block,
            # so a name opening the message doesn't read as its speaker
            speaker, message = text.split(": ", 1)
            body_html = f"<span class='who'>{name(speaker)}</span><span class='msg'>{name(message)}{extra}</span>"
            cls, extra = f"{category} said", ""
        out.append(f"<div class='ev {cls}'{involves(name.names_in(text) | set(who))}>{b}"
                   f"{name(text) if body_html is None else body_html}{extra}</div>")

    def why(r: dict) -> str:
        """The reason (and thinking) behind a player's message, claim or nomination, from the call that wrote
        it: the writer's latest call. Shown once per call, next to the first thing it said."""
        src = last_call.get(r.get("puppeteer") or r.get("speaker") or "")
        if not src or id(src) in explained:
            return ""
        explained.add(id(src))
        o = src.get("output") or {}
        reason = o.get("reason") or o.get("thoughts")  # "thoughts" in LOG_VERSION 22 and earlier
        if not reason and not src.get("reasoning"):
            return ""
        return packer.details(
            "why", "<summary title='Why: the private reason and thinking behind this turn'>why</summary>",
            (f"<div>{name(reason)}</div>" if reason else "")
            + (f"<details class='thinking'><summary>Model's thinking</summary><pre>{esc(src['reasoning'])}</pre>"
               "</details>" if src.get("reasoning") else ""))

    for r in records:
        k = r["kind"]
        if r.get("alert"):  # GameLog.error: shown where it happened and listed at the top
            anchor = f"error-{len(errors)}"
            errors.append((anchor, r))
            details = {f: v for f, v in r.items() if f not in ("t", "kind", "alert", "error", "traceback")}
            out.append(f"<div class='ev error' id='{anchor}'{involves([r['player']] if r.get('player') else [])}>"
                       f"<span class='badge'>Error: {esc(k)}</span>"
                       f"{name(r['error'])}" + (call("Details", pre("Fields", details) + pre("Traceback", r.get("traceback")))
                                                if details or r.get("traceback") else "") + "</div>")
        elif k == "setup":
            roles = {p["name"]: p["role"] for p in r["players"]}
            models = {p["name"]: short_model(p["model"]) for p in r["players"]}
            traits = {p["name"]: p.get("traits") or [] for p in r["players"]}
            name = Namer(roles, traits)
            alive = [p["name"] for p in sorted(r["players"], key=lambda p: p["seat"])]
            alive_order = list(alive)
            believed = {p["name"]: {p["role"], (p.get("status") or {}).get("fake_role")} for p in r["players"]}
            roster = {n: {"alive": True, "death": "", "claim": "", "truth": ""} for n in alive}
            rows = "".join(f"<tr><td>{name(p['name'])}</td><td>{p['seat'] + 1}</td><td>{esc(p['role'])}"
                           f"{' (' + esc(traits_text(p['traits'], context().details.get(p['name']))) + ')' if p.get('traits') else ''}</td>"
                           f"<td>{esc(p['model'] + via_note(p))}</td><td class='muted'>{name(status_text(p.get('status')))}</td></tr>"
                           for p in r["players"])
            start_phase("Setup")
            out.append(f"<table><tr><th>Player</th><th>Seat</th><th>Role</th><th>Model</th><th></th></tr>"
                       f"{rows}</table><div class='muted'>Katana starts with {name(str(r.get('katana')))}</div>")
        elif k == "briefing":
            out.append(f"<div class='muted'>{esc(r['setup_note'])}</div>"
                       + call("What every player was told at the start",
                              pre("Rules as played (rules, rule settings and setup note)", r["rules"])
                              + "".join(pre(f"Role briefing: {who} ({roles.get(who, '?')})", text)
                                        for who, text in r["players"].items())))
        elif k == "tips":
            files = tips_files(r)
            out.append(f"<div class='muted'>Tips from past games given to: {esc(', '.join(r['players']) or 'nobody')}"
                       "</div>")
            for who, file in files.items():
                shown = (player_view(r["texts"][file]) if "texts" in r else r["shown"].get(who, "") if "shown" in r
                         else player_view(r.get("text", "")))  # LOG_VERSION 11 had one text
                out.append(call(f"Tips for {name(who)} ({esc(roles.get(who, '?'))}, {esc(models.get(who, '?'))}): "
                                f"{esc(file)}", f"<pre>{esc(shown)}</pre>"))
        elif k == "event":
            if is_phase_start(r):
                start_phase(r["text"].removesuffix(" begins."))
                if r["text"].startswith("Day "):  # night deaths are already logged, though revealed after this
                    line("system", f"Alive ({len(alive)})", ", ".join(alive) or "nobody")
                continue
            if r.get("cat") == "claim" and blank(r["claim"]):
                continue  # "null" meant no change (shown in logs from before a592f5f)
            if r.get("cat") == "death" and (m := re.match(r"(\w+) was the Executioner.* leave the game", r["text"])):
                gone(m[1], f"won and left, Day {r.get('day')}")  # LOG_VERSION 33 and earlier had no "left" record
            if r.get("cat") == "result" and r.get("phase") == "night":
                for who in r["visible_to"]:
                    night(r["day"])["results"].setdefault(who, []).append(r["message"])
            category, badge, body = classify(r)
            vis = r["visible_to"]
            line(category, badge, body, who=[] if vis == "all" else vis,
                 extra=why(r) if r.get("cat") in ("chat", "pm", "yak", "claim") else "")
            if r.get("cat") == "claim" and r["speaker"] in roster:
                roster[r["speaker"]].update(claim=r["claim"], truth=claim_truth(r["claim"], believed[r["speaker"]]))
                snap()
        elif k == "death":
            when = f"{'Night' if r.get('phase') == 'night' else 'Day'} {r.get('day')}"
            gone(r["player"], f"died {when}: {r.get('cause')}")
            if r.get("phase") == "night":
                night(r["day"])["deaths"].append((r["player"], r.get("cause")))
        elif k == "left":
            gone(r["player"], f"won and left, Day {r.get('day')}")
        elif k == "claim":
            line("system", "Claim", f"{r['player']}: {r['claim']}")
        elif k == "vote":
            votes.append(r)
            day_votes.append(r)
            if r.get("secret"):  # players saw only the totals: show who voted which way where the vote happened
                line("hidden", "Secret votes", "", who=r["votes"], body_html=vote_split(r, name, alive_order))
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
            out.append(call(summary, pre("Reasoning (model's thinking)", r.get("reasoning"), REASONING_HINT)
                            + pre("Thoughts (private field)", thoughts) + pre("Reason (private field)", reason, REASON_HINT)
                            + pre("Output", o) + notepad
                            + pre("Task prompt", r["task"]) + pre("Usage", r.get("usage")), involves([r["player"]])))
        elif k == "moderator_prompt":
            out.append(call("Moderator's instructions for this phase",
                            pre("Instructions", r["instructions"]) + pre("State summary", r["state_summary"])
                            + pre("Full state", r["full_state"])))
        elif k == "moderator_call":
            calls = ", ".join(c["function"]["name"] for c in r.get("tool_calls") or []) or "no tool call"
            out.append(call(f"Moderator ({esc(r['model'].split('/')[-1])}) → {esc(calls)} · ${r.get('cost', 0):.4f}",
                            pre("Reasoning", r.get("reasoning"), REASONING_HINT) + pre("Content", r.get("content"))
                            + pre("Tool calls", [{"name": c["function"]["name"],
                                                  "args": tool_args(c["function"].get("arguments"))}
                                                 for c in r.get("tool_calls") or []])
                            + pre("Usage", r.get("usage"))))
        elif k == "moderator_tool":
            if r["name"] == "end_phase" and phase_ended(r):
                line("hidden", "Moderator summary", str(tool_args(r["args"]).get("summary", "")))
            else:
                out.append(call(f"Tool {esc(r['name'])} result", pre("Args", r.get("args")) + pre("Result", r.get("result"))))
        elif k == "night_actions":
            rows = "".join(f"<div>{name(n)} ({esc(r['roles'].get(n))}): {name(describe_action(a))}</div>"
                           for n, a in r["actions"].items())
            line("hidden", "Night actions", "", who=r["actions"], body_html=rows)
            night(r["day"]).update(actions=r["actions"], roles=r["roles"])
        elif k in ("katana", "revenge"):
            if k == "katana":
                night(r["day"])["katana"] = text_line(r)
            line("hidden", "Katana" if k == "katana" else "Revenge", text_line(r) or "")
        elif k == "night_check":
            line("hidden", "Night check", describe_check(r))
            night(r["night"])["check"] = r
        elif k == "visits":  # the moderator's record_visits (LOG_VERSION 33+)
            line("hidden", "Visits", ", ".join(f"{a} → {b}" for a, b in r["visits"]) or "none")
            night(r["day"])["visits"] = r["visits"]
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
            out.append(call(f"Moderator ({esc(short_model(r['model']))}) debrief · ${r.get('cost', 0):.4f}",
                            pre("Answers", r["answers"])))
        elif k == "strategy_review":
            line("hidden", "Strategy review", r["summary"])
            out.append(call(f"Moderator ({esc(short_model(r['model']))}) lessons · ${r.get('cost', 0):.4f}",
                            pre("Lessons", r.get("lessons"))))
        elif k == "review":
            for i in r["issues"]:
                line("hidden", f"Review: {i.get('severity', '?')}, {i.get('kind', '?')}", i.get("description", ""))
            if not r["issues"]:
                line("hidden", "Review", "No issues found.")
        elif k in ("budget_warning", "message_dropped", "nomination_dropped", "player_error", "moderator_error"):
            out.append(call(f"{esc(k.replace('_', ' '))}: {esc(r.get('player', ''))}", pre("Details", r),
                            involves([r["player"]] if r.get("player") else [])))
        elif k == "section":  # post-game steps (feedback.POST_GAME_SECTIONS)
            start_phase(r["title"])
        elif k == "result":
            start_phase("Game over")
            line("result", "Winners", ", ".join(r["winners"] or []) or "nobody")
            if "usage" in r:  # LOG_VERSION 10+
                out.append(usage_html(r["usage"], claude_code_costs(records)))
            else:
                out.append(pre("Cost by model (USD)", r.get("cost")))
    end_phase()
    # One pass over the page for every night card (a replace per night took a third of the render time)
    body = re.sub("\0night ([0-9]+)\0",
                  lambda m: night_html(int(m[1]), nights[int(m[1])], name) if int(m[1]) in nights else "",
                  "".join(out))

    legend = "".join(f"<span class='badge {c}' data-cat='{c}' title='Click to hide or show these lines'>{esc(label)}"
                     "</span>" for c, label in CATEGORY_LABELS.items())
    legend += ("<span class='n Village'>Village</span> <span class='n Yakuza'>Yakuza</span> "
               "<span class='n Neutral'>Neutral</span>")
    title = f"Mafia game {jsonl_path.stem}"
    focus_options = "".join(f"<option>{esc(n)}</option>" for n in alive_order)
    page = (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' "
            f"content='width=device-width, initial-scale=1'><title>{esc(title)}</title>"
            f"<style>{CSS}{icons_css(traits.values())}</style>"
            f"</head><body><h1>{esc(title)}</h1><div class='legend'>{legend}</div><div class='controls'>"
            f"<label><input type='checkbox' id='showcalls' checked> Model details</label>"
            f"<label><input type='checkbox' id='showhidden' checked> Hidden info</label>"
            f"<label><input type='checkbox' id='showicons' checked> Role icons</label>"
            f"<span><button id='expand'>Expand all</button> <button id='collapse'>Collapse all</button></span>"
            f"<label><input type='checkbox' id='showroster'> Roster</label>"
            f"<label>Player <select id='focus'><option value=''>everyone</option>{focus_options}</select></label>"
            f"<span class='muted'>Untick the first two to read it like a player would.</span>"
            f"<nav id='jump'>{jump_html(phases)}</nav></div>"
            f"{errors_html(errors, unreadable)}"
            f"{votes_html(votes, name, alive_order, 'Votes (whole game)', show_day=True)}"
            f"{body}{roster_html(snaps, alive_order, roles, models, traits)}{packer.blob()}<script>{JS}</script>"
            "</body></html>")
    html_path = jsonl_path.with_suffix(".html")
    # through a temp file, so `game_index.py serve` (or a browser) never sends a half-written page
    tmp = html_path.with_name(f"{html_path.name}.{os.getpid()}.tmp")  # per process: a game and serve may both render
    tmp.write_text(page, encoding="utf-8", errors="replace")
    os.replace(tmp, html_path)
    return html_path


def involves(names: Iterable[str]) -> str:
    """The data-p attribute the player filter reads: the players a line or call involves."""
    return f" data-p='{esc(' '.join(sorted(names)))}'" if names else ""


def vote_split(v: dict, name: Namer, seats: list[str]) -> str:
    """One vote record as "Guilty (n): names · Innocent (n): names" in seat order, marking doubled, reversed and
    fixed votes."""
    yes, no = ("Guilty", "Innocent") if v["stage"] == "trial" else ("Yes", "No")
    weights, flipped, fixed = v.get("weights") or {}, set(v.get("reversed") or []), v.get("fixed") or {}

    def who(n: str) -> str:
        notes = ([f"×{weights[n]}"] if weights.get(n, 1) != 1 else []) + (["reversed by a Fixer"] if n in flipped else []) \
            + ([f"fixed by {fixed[n]}"] if n in fixed else [])
        return name(n) + (f" <span class='muted'>({', '.join(notes)})</span>" if notes else "")
    groups = [(label, [n for n in sorted(v["votes"], key=lambda n: seats.index(n) if n in seats else len(seats))
                                       if v["votes"][n] is side]) for label, side in ((yes, True), (no, False))]
    return (f"<span class='muted'>{esc(v['stage'])} of</span> {name(v['nominee'])} "
            f"<span class='muted'>({esc(str(v['outcome']))})</span> · "
            + " · ".join(f"<b>{label}</b> ({sum(weights.get(n, 1) for n in names)}): "
                         f"{', '.join(map(who, names)) or 'nobody'}" for label, names in groups))


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


ROLE_NAMES = re.compile(r"\b(" + "|".join(re.escape(r) for r in sorted([*ROLES, *RETIRED], key=len, reverse=True))
                        + r"|Vanilla)\b", re.I)


def claim_truth(claim: str, believed: set[str | None]) -> str:
    """'true' if a claim names the player's role (or the one a Roleplayer believes they have), 'false' if it names
    only other roles, '' if it names none."""
    named = {m.lower() for m in ROLE_NAMES.findall(claim)}
    if not named:
        return ""
    own = {r.lower() for r in believed if r} | ({"vanilla"} if "Vanilla Villager" in believed else set())
    return "true" if named & own else "false"


def night_html(n: int, info: dict, name: Namer) -> str:
    """A collapsed card at the end of a Night: who did what, what each was told, the Katana, deaths and the night
    check's verdict, in one place."""
    deaths = ", ".join(f"{p} ({c})" for p, c in info["deaths"]) or "nobody"
    check = info["check"]
    verdict = f" · night check: {check['verdict']}" if check else ""
    acted = {p: a for p, a in info["actions"].items() if a.get("act") or a.get("katana_vote_holder")}
    rows = "".join(f"<tr><td>{name(p)}</td><td class='muted'>{esc(info.get('roles', {}).get(p, ''))}</td>"
                   f"<td>{name(describe_action(a))}</td>"
                   f"<td>{'<br>'.join(map(name, info['results'].get(p, [])))}</td></tr>" for p, a in acted.items())
    told = "".join(f"<tr><td>{name(p)}</td><td></td><td class='muted'>no action</td>"
                   f"<td>{'<br>'.join(map(name, msgs))}</td></tr>"
                   for p, msgs in info["results"].items() if p not in acted)
    extra = "".join(f"<div>{label}: {name(text)}</div>" for label, text in (
        ("Katana", info["katana"]), ("Visits", ", ".join(f"{a} → {b}" for a, b in info["visits"] or []))) if text)
    if check and check["issues"]:
        extra += f"<div>Night check: {name(describe_check(check))}</div>"
    return (f"<details class='votes card'><summary>Night {n} summary: {len(acted)} acted · died: {name(deaths)}"
            f"{esc(verdict)}</summary><div class='scroll'><table><tr><th>Player</th><th>Role</th><th>Action</th>"
            f"<th>Told</th></tr>{rows}{told}</table></div>{extra}</details>")


def roster_html(snaps: list[dict], seats: list[str], roles: dict[str, str], models: dict[str, str],
                traits: dict[str, list[str]] | None = None) -> str:
    """The roster panel: every player's alive or dead state and latest claim as of the part of the log on screen.
    The page marks where each snapshot starts (<i class='snap'>), and the script shows the last one above."""
    if not snaps:
        return ""
    data = {"players": [{"n": n, "html": name_span(n, roles[n], (traits or {}).get(n, ())), "role": roles[n], "model": models.get(n, "")}
                        for n in seats],
            "snaps": [{n: [s[n]["alive"], esc(s[n]["death"]), esc(s[n]["claim"]), s[n]["truth"]] for n in seats}
                      for s in snaps]}
    return ("<aside id='roster'></aside><script type='application/json' id='roster-data'>"
            + json.dumps(data, ensure_ascii=False).replace("</", "<\\/") + "</script>")


def jump_html(phases: list[dict]) -> str:
    """Links to each phase for the sticky bar: N1, D1, ... with a † per death in it, then one link to the
    post-game sections and one to the result."""
    links, post_game = [], False
    for p in phases:
        t = p["title"]
        if m := re.fullmatch(r"(Day|Night) (\d+)", t):
            short = m[1][0] + m[2]
        elif t in ("Setup", "Game over"):
            short = t
        elif not post_game:
            short, post_game = "Post-game", True
        else:
            continue
        deaths = f"<span class='deaths'>{'†' * p['deaths']}</span>" if p["deaths"] else ""
        cls = " class='night'" if t.startswith("Night") else ""
        links.append(f"<a href='#{p['id']}'{cls} title='{esc(t)}'>{esc(short)}{deaths}</a>")
    return "".join(links)


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
