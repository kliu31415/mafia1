# mafia1

The module map is in `mafia.py`'s docstring. Ideas considered but not built yet, with their tradeoffs, are in `IDEAS.md`. The rules are `rules_1.txt` (Kevin's text; don't edit it
unless asked). Its general paragraphs are labeled R1-R21 (grouped by topic, so not in numeric order; R18 defines terms, R19 is what investigations see, R20 the night checklist, R21 next-Day effects whose user died) and roles are cited by name; code that implements
a rule cites it (e.g. `# rules R8`), so `grep -n "R8"` finds every place the Katana rule is used. Keep
labels stable: add new paragraphs at the end of the general rules (R16, ...) instead of renumbering.

## Working preferences

- Commit and push straight to `main` once `uv run pytest`, `uv run ruff check .` and `uv run mypy .`
  pass. No need to ask first or to open a branch, unless Kevin asks for one.
- GitHub runs the same checks on every push to main (`.github/workflows/checks.yml`, skipped for tips-only
  commits). After pushing, check your commit's run (GitHub tools: workflow runs for `checks.yml` on main) and fix a
  red one yourself, including breakage from another thread's push; Kevin doesn't watch CI emails.
- Small changes: test with offline mock games only, no live games.
- Bigger changes: also run a live game in the background: about 7-8 players with cheap player models
  (haiku-5.5, gpt-6-luna) and an opus-5.5 moderator. Keep a status line saying a live game is running
  until it finishes (games take 10-40 minutes).
- Low-cost API calls (Haiku, Luna) are fine whenever they help verify that code works.
- Don't pick DeepSeek V4.1 Flash as a player unless Kevin asks: its thinking often runs into the token cap, so
  turns fall back to defaults, and its feedback reports problems that didn't happen (details above its entry in
  `llm.py`). When reviewing alerts, check its reports against the log before treating them as bugs.

## Live games in the cloud

Cloud threads (Claude Code on the web) can run live games once `OPENROUTER_API_KEY` is set in the cloud
environment, but their sandbox is deleted afterwards, so the logs go through the repo's `logs` branch
(logs/ and tips/ only, never code; `sync_logs.py` writes it with git plumbing, so main's checkout is untouched):
1. Before games: `uv run sync_logs.py tips` gets the PC's latest tips sheet into tips/ (add
   `--tips tips/tips.md --tips-for ...` to a game to give players tips).
2. Games detect the cloud (`CLAUDE_CODE_REMOTE=true`): they don't update the tips (the notebook on Kevin's PC
   is the one source of truth; a cloud copy would fork it), and when one ends, crashes or is stopped it
   pushes logs/ to the branch itself (`--sync`, on by default); it fetches only the branch's file lists, plus the files it merges).
   It also pushes them after each checkpoint (every Day and Night), so a game whose sandbox is lost mid-game resumes in a
   new one: `uv run sync_logs.py get GAME`, then `uv run mafia.py --resume logs/GAME.ckpt`. If that prints `ALERT sync_error`, run
   `uv run sync_logs.py push` before saying the game is done; logs that aren't pushed are lost with the sandbox.
On the PC, `uv run sync_logs.py pull` copies new logs into logs/ (a game pushed again, e.g. after a
mid-game push, replaces its earlier copy and that copy's .txt/.html/feedback files), adds their lessons to
the tips notebook and publishes the new sheet to the branch (`--no-tips` only copies logs). A PC game also
publishes the sheet when it updates it, so cloud games get it without a pull. A PC game (with `--sync`, the
default) also does the pull's first part before it starts (`sync_logs.catch_up`: new cloud logs, and their
lessons into the notebook with the game's moderator model), so the tips don't fall behind cloud games.
`lessons.jsonl` and `alerts_reviewed.json` are merged, not overwritten; mock games are never synced.
tips/ (sheet, notebook, and old sheets in history/; the notebook's old versions are in git history) is also
tracked on main, so a new PC can pull it and keep building the notebook. A PC game that updates the tips (and
`sync_logs.py pull`) commits tips/ alone to main and pushes it, as a tips-only commit on the remote's main when
the local main has other unpushed commits (`sync_logs.commit_tips`; staged work stays staged; skipped off main).
Git never merges two notebooks: before a build, `sync_logs.rebase_tips` takes main's notebook if it has games
this PC's lacks, and the build adds this PC's other games again (an extra tips-model call each). Cloud threads
never commit tips/ (their copy comes from the branch and the PC's commit is what counts). Changes under tips/
don't mark a game's `git_dirty`. logs/ stays untracked (large; it lives on the `logs` branch and the PC).

## Checking changes

- `uv run pytest` runs the scenario and visibility tests (offline, about 20 s on 4 cores, in parallel through
  pytest-xdist; `-n0` runs them in one process, for debugging). Run it before every commit, and add a test when you
  fix a rules bug or change a code-handled role. Tests write only under `tmp_path`, since they run at the same time.
- `uv run ruff check .` catches undefined names, unused imports and likely bugs; `uv run mypy .` checks
  types (e.g. a possibly-None value used as a player), including the bodies of unannotated functions.
- `tests/test_prompts.py` keeps what players and the moderator are sent for a short scripted game in
  `tests/prompts/`, and checks that each player's cached system message stays the same within a phase. After an
  intended prompt change, run `uv run pytest --update-prompts` and read the diff of `tests/prompts/` before committing.
- `uv run mafia.py --mock` plays a full offline game; the same `--seed` replays the same game. Its
  moderator only carries out the Katana attack, so moderator-handled roles are only exercised in live games.
- `uv run stats.py` reads every finished live game in `logs/`: win rates by faction, model and role (with
  95% intervals), Village win rate with and without each role, and per-decision skill by model or role.
  Logs are on Kevin's PC; `--csv DIR` exports the tables.
- `uv run game_index.py build` writes `logs/index.html`, one filterable table of every game (models by tier,
  winner, cost, errors, tips) linking to each HTML log; games and `sync_logs.py pull` rebuild it, and
  `uv run game_index.py serve` shows an always-current copy on localhost. `stats.py` takes the same filters
  (`--mix frontier`, `--min-frontier 0.7`, `--model`, `--winner`, ...; `--list` lists the games). Model tiers
  are each model's `tier` in `MODELS` (`llm.py`), relative to today's frontier: re-check them when a new
  frontier model comes out.
- `tests/conftest.py` has `ScriptedClient` (players answer "do nothing" unless a `decide` function says
  otherwise; the moderator makes queued tool calls) and `game_factory` (seats Alice, Bob, ... with the
  roles you give, in order).

## Roles

- `uv run mafia.py --list-roles` shows how every role is implemented: its code hooks and night note
  are read from the code; `tested` and `notes` in its `ROLES` entry are kept by hand. Check it there
  instead of auditing the code. Set `tested=True` when a role is first seen working in a live game, and
  update `notes` when its handling changes.
- Adding or changing a role can touch all of these; check each one:
  1. `roles/__init__.py`: `ROLES` entry (alignment, category (its rules heading) and, for Investigative roles, subcategory, Sheriff result, `summary` (one line shown when
     hovering the role's icon in the HTML log; a test fails when the role's rules paragraph changes, until
     `uv run role_summaries.py ROLE` records that the summary was checked), defense, tokens, `acts_at_night`, `tested`, `notes`).
  2. `roles/<role>.py`: effects that code carries out, as hooks from `roles/base.py` (setup, briefing,
     deaths, dawn, ...). Every module in roles/ is imported (and so registered) automatically. Core
     code calls hooks and shouldn't name roles; if a role needs a hook that doesn't exist, add one to
     `RoleLogic`. Per-game role state goes in `game.role_state`, not new `Game` fields.
  3. Day mechanics roles trigger (`Game.prosecutions`, `rigged_day`, `puppets`) are generic and live in
     `state.py` and `day.py`; `night_action_schema` in `players.py` is one shape for every role.
  4. `night_note` on the role's class: a reminder the moderator gets each night for effects with no
     submitted action or that need a special op. Only roles in the game are included.
  5. A role-specific `apply_changes` op. For a night action the moderator just records and code carries out (most
     info and token roles), set `action = RecordedAction(...)` and write `carry_out` (plus `target_error` for any
     extra check): `@register` builds the op, the standard checks (user has the role and was alive when the night
     began, R10; token; target alive then; not themselves) and the night note, and
     `test_recorded_actions_check_their_user_target_and_token` tests them. Otherwise declare the op in `ops` and
     write `check_op` and `apply_op` with `token_user_error` and `spend_token`. Use `game.tell` for a private
     result; `join_names`, `neighbor_group` and `tokens_left_text` in `roles/base.py` cover common wording and
     groups. The moderator is offered the op only when the role is in the game. Ops every game needs are
     `CORE_OPS` in `moderator.py`.
  6. `tests/test_roles.py`: a scenario test for anything code carries out. Every role also gets a mock-game
     smoke test automatically (`test_every_role_survives_a_mock_game`). `apply_ops` and `told` in
     `tests/conftest.py` apply moderator ops and read a player's private results.
  7. `roles/icons/<role-name>.svg` (e.g. `ex-con.svg`): the icon next to the role's players in the HTML log, a
     24x24 color drawing, distinct from the other roles at a glance (the viewer puts it on a badge tinted by faction).
     A test checks every role has one.
  8. Scripts (`scripts.py`, `--script`, Blood on the Clocktower style): a game's rules list only its script's roles,
     and every role in it comes from the script. `all` (the default, rules unchanged) has every role, so a new role
     needs nothing there; add it to a hand-made script (`core`, 30 roles) only if it fits. Code that draws "any role"
     (fakes, decoys) must draw from `scripts.script_roles(game)`, not `ROLES`. Each hand-made script's rules are the
     cut plus small edits an Opus call made once (dropping mentions of off-script roles), cached in `rules_scripts/`.
     After any edit to `rules_1.txt`, `test_every_script_revision_is_current` fails until the stale ones are remade.
     A Claude session that edits the rules writes the edits itself (Kevin, Oct 11 2026: no API call needed):
     `uv run scripts.py task NAME` prints what to edit, `uv run scripts.py apply NAME FILE` records a JSON file of
     edits (start from the previous ones in `rules_scripts/NAME.json`); `uv run scripts.py revise` asks Opus instead
     (about $0.10 each), e.g. after a hand edit. Check the diff of `rules_scripts/*.txt` and commit it with the rules. A game on a stale script plays by the plain cut and logs `script_stale`.
  9. `setups.py` draws setups (`--roles standard`, the default: 13 players, no Vanilla Villager or Grunt (`Setup.off`, told to players and left out of `script_roles`), balanced with the role powers in
     `role_power.py`: hand-set priors, refit from game results into `tips/role_power.json`/`.md` wherever the tips are
     updated, and carried by the tips commit and publish; `classic` is the older 11-15 player draw; `NAME:N` sets the count) by alignment and category, and tells players how (a note after the rules, never the role list), and `stats.py` scores
     some roles' night decisions (Sheriff, Medic, Vigilante, Katana target); add a scored decision there
     when the role's choices have a clear right answer.

- Traits (`traits.py`, rules R24: Martyr, Armed, Avenger): an extra ability on top of a player's role; a player may hold
  several, never one twice, and keeps them if the role changes. A trait is a `TRAITS` entry (who can get it, the
  holder's line, its power, its corner mark in the HTML log) plus a `TraitLogic` with the hooks it needs; a night
  action (Armed's shot) is `can_act` + `action_task` + `ops`, asked for in the night answer's `trait_actions` list.
  Drawn setups deal 0-3 (`setups.draw_traits`, balancing with the powers); `--traits` sets them (`Martyr+Armed`:
  one player gets both). Add a scenario test like the Martyr's and Armed's.

## Conventions

- Hidden information: every `game.emit(...)` passes `visible_to` (None means everyone). A wrong list
  leaks secrets into other players' prompts; `tests/test_visibility.py` checks this per category.
- Every `emit` also passes `cat=` (`CHAT`, `PM`, `DEATH`, ... in `events.py`) plus that category's fields.
  The log viewer colors events by `cat`, never by their wording, so wording can change freely.
- `Player.status` keys that code reads are in `roles.Status`; use the constants, not strings.
- Logs are meant for analysis across games: each record kind keeps stable fields. If you change a
  record's fields, bump `LOG_VERSION` in `gamelog.py` (it's written in the "setup" record). Likewise bump
  `CHECKPOINT_VERSION` when `Game`, `Player` or `Event` fields change. `tests/test_versions.py` fails when either
  set of fields changes without its bump; after bumping, `uv run pytest --update-versions` records the new fields.
  An older checkpoint is refused on resume; `--force-resume` resumes it anyway (new fields get their defaults,
  logged as a `resume_forced` alert), which is usually fine after small changes.
  Tools that read many games go through `gamelogs.py` (log files, setup/result, one dict per player); shims for
  old log versions belong there only.
- Night checks (`night_check.py`, on by default) log a judge model's verdict on each night's moderator
  resolution as "night_check" records. With `--fix-nights` (the default) the check runs before dawn and its
  high-severity findings go back to the moderator, who verifies each and corrects the real ones ("night_fix"
  records); the judge never changes the game itself. `--no-fix-nights` runs checks in the background instead.
- Anything that goes wrong (a failed or empty LLM answer, a fallback, an API retry, a moderator tool
  error, a failed post-game step, a crash) goes through `game.log.error(kind, summary, ...)`, never a
  bare `write` or a silent `except`. It's logged with `alert: true`, counted in the result record, listed
  at the top of the feedback report and of the HTML view (each error is also marked in red where it
  happened, and in the .txt as `[ERROR kind]`), and printed as an `ALERT ...` line. When running a live game,
  watch its output for `ALERT` lines and tell Kevin about new kinds of errors as they happen.
- Player answers are checked against their schema (`players.schema_errors`) before the game uses them; one
  that breaks it is a `player_error`, retried and then replaced by the fallback. Moderator ops that apply but
  look wrong (e.g. killing a dead player) come back to the moderator as notes and are `moderator_warning`s.
- Errors get looked at even in games Kevin runs himself: `uv run alerts.py` lists games in `logs/` with errors
  nobody has reviewed (and games killed without a result, moderator flags, players' feedback-field reports and
  high-severity log-review issues, since those often point at bugs such as a leak), and a SessionStart hook in `.claude/settings.json`
  puts that list in Claude's context when a session starts in this folder. When it does, tell Kevin first
  (which games, which kinds, likely cause). Ack what's fully handled (fixed, settled, or noise) yourself with
  `uv run alerts.py --ack GAME ...`, without asking, and say so; mark what's still being discussed with
  `--wip GAME ... --note "what's pending"` (listed apart, not re-reported) and ack it once resolved. Finished
  games also print a reminder line while anything is unreviewed. A new error kind needs no registration;
  anything that goes through `game.log.error` shows up everywhere above.
- Prompt caching: a prompt starts with what many calls repeat (the rules, via `llm.rules_system`), and ends
  each stable part with `llm.cache_block`; Claude and Gemini cache only up to those marks, and OpenAI only the
  system message, so a player's stable text (briefing, earlier phases' history) goes there. The answer schema is part of the cached
  prefix too, so live games send every in-game player call one schema (`players.shared_schema`) and check the
  answer against the task's own afterwards. Check `cached_tokens`
  in `player_call` usage after changing a prompt's layout.
- Models: everything the program knows about a model (short name, tier, strength, default effort, quirks) is its
  `MODELS` entry in `llm.py`, with notes on its quirks next to it; a new model is a `Model` id plus that entry
  (a test checks it), and a new maker also needs `PROVIDERS`.
- Reasoning effort: each model has a default (`effort` in `MODELS`: high, except Qwen and Gemini Flash at medium,
  since at high they run near or past the token cap); measured cost and time per turn at medium vs high are in the comment there.
  `model:effort` or `--effort` override it. A player answer cut off at max_tokens is retried one step lower
  (`llm.lower_effort`), logged as an `effort_fallback` alert (from/to effort; counted per player in result usage).
- Player and moderator answers use strict JSON schemas (structured outputs). Some providers reject schema shapes
  others accept; known cases and workarounds are in the comment above `flat_nullable_enums` in `llm.py`. When a
  new model or a new schema field fails with HTTP 400 or empty answers, check there first.
- Every model is pinned to its maker's own OpenRouter provider (`PROVIDERS` in `llm.py`; GLM uses Together,
  since Z.AI's endpoint lacks structured outputs); add one there for a new maker.
- Claude models' calls run through the Claude Code CLI (`claude -p`, the signed-in subscription's
  quota, $0 in the cost tables; list price and plan utilization are in each call's usage) wherever a `claude`
  command is on PATH (the default since Oct 11 2026; `--no-claude-code` sends them through OpenRouter, `--claude-code`
  insists on the CLI), and other models through OpenRouter, so a game can mix both. Tools outside games (tips builds,
  catch-up and `sync_logs.py pull`, `grade.py`, `scripts.py revise`) route the same way (`claude_code.default_client`). On Kevin's PC `claude` (and `codex`)
  are launchers in `~/.local/bin` that run the desktop app's newest bundled CLI (source in `~/.local/share/cli-launcher`).
  When a Claude seat misbehaves, check whether the CLI route is the cause (`via` in the log) before the game code.
  Each call is a fresh CLI process with no tools and the game's own system prompt; the moderator's tools
  become an answer schema (details in `claude_code.py`). A subscription limit is waited out, or stops the game for
  `--resume` when it resets more than 6 hours later. Games also leave part of the subscription for Kevin's other
  work (a program safeguard): at 70% of the 5-hour or 7-day window (`PLAN_CAPS` in `claude_code.py`; `--plan-cap
  5H,WEEK` in percent, `100,100` for none) a game doesn't start (one small Haiku call reads the utilization and
  prints it), and a running one waits for the reset (a `plan_cap` alert) or stops for `--resume`. Early in the
  week a new game needs more room: it starts only below a figure that rises evenly through the week (10% of the
  7-day window at its reset, 40% halfway, 70% at the next reset; `start_cap`). The same effort can think more through the CLI, so a model's
  CLI default can differ (`cli_effort` in `MODELS`: Haiku medium). Logs record each player's route (`via`), and
  `stats.py` counts Claude Code seats as their own model ("haiku-5.5 (CC)").
- Tips from past games (`tips.py`): `uv run tips.py build` distills the lessons and strategy reviews in
  game logs: each new game updates a verbose notebook (`tips/tips_notebook.json`/`.md`: every tip with its
  evidence, weights and reports against it, changed only through small ops) and the short sheet players get
  (`tips/tips.md`) is rewritten from it. Feedback from players who had tips and the moderator (`tips_feedback`)
  counts as evidence. games do this when they end, by default (`--no-update-tips` to skip; mock games use `logs/mock_tips/`); `--tips FILE --tips-for all|half|names|models` puts it in chosen players'
  system prompts, and `--player-tips WHO=FILE|none,...` sets each player's or model's file. After a rules change, `uv run tips.py revise --note ...` (on the PC) rewords or retires the notebook entries that no longer hold, and `sync_logs.py publish-tips` publishes and commits the result. Players see
  every section (all factions and roles). The models learn collectively: one file pools every model's lessons. The
  "tips" record and `tips` in the result's players say who had them, for comparing against fresh players.
  Lessons are weighted by their author's model strength and the game's average (`strength` in
  `llm.MODELS`, 1-5, kept by hand).
- Rule settings (`variants.py`: `--flips`, `--trial-votes`, `--nomination-votes`): `rules_1.txt` describes the game
  with the defaults, which hide the most (deaths reveal only cause and will, secret votes). A non-default choice
  changes a rule without editing the file: it adds a note after the rules text, so every prompt sees it. Code reads
  `game.rule_settings`; logs without them used `variants.LEGACY` (role flips, public votes), as did the rules text
  before Oct 10 2026. Keep rules wording in line with the defaults when they change.
- Program safeguards that aren't rules from `rules_1.txt` are marked as such in code and in game text.
  Currently: a game stops with no winner after (players + 10) days (`EXTRA_DAYS` and `--max-days` in
  `mafia.py`), so a stuck game can't run forever.
