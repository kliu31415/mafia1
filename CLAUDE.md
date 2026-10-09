# mafia1

The module map is in `mafia.py`'s docstring. Ideas considered but not built yet, with their tradeoffs, are in `IDEAS.md`. The rules are `rules_1.txt` (Kevin's text; don't edit it
unless asked). Its general paragraphs are labeled R1-R15 and roles are cited by name; code that implements
a rule cites it (e.g. `# rules R8`), so `grep -n "R8"` finds every place the Katana rule is used. Keep
labels stable: add new paragraphs at the end of the general rules (R16, ...) instead of renumbering.

## Working preferences

- Commit and push straight to `main` once `uv run pytest`, `uv run ruff check .` and `uv run mypy .`
  pass. No need to ask first or to open a branch, unless Kevin asks for one.
- Small changes: test with offline mock games only, no live games.
- Bigger changes: also run a live game in the background: about 7-8 players with cheap player models
  (haiku-5.5, gpt-6-luna) and an opus-5.5 moderator. Keep a status line saying a live game is running
  until it finishes (games take 10-40 minutes).
- Low-cost API calls (Haiku, Luna) are fine whenever they help verify that code works.

## Live games in the cloud

Cloud threads (Claude Code on the web) can run live games once `OPENROUTER_API_KEY` is set in the cloud
environment, but their sandbox is deleted afterwards, so the logs go through the repo's `logs` branch
(logs/ and tips/ only, never code; `sync_logs.py` writes it with git plumbing, so main's checkout is untouched):
1. Before games: `uv run sync_logs.py tips` gets the PC's latest tips sheet into tips/ (add
   `--tips tips/tips.md --tips-for ...` to a game to give players tips).
2. Games detect the cloud (`CLAUDE_CODE_REMOTE=true`): they don't update the tips (the notebook on Kevin's PC
   is the one source of truth; a cloud copy would fork it), and when one ends, crashes or is stopped it
   pushes logs/ to the branch itself (`--sync`, on by default). If that prints `ALERT sync_error`, run
   `uv run sync_logs.py push` before saying the game is done; logs that aren't pushed are lost with the sandbox.
On the PC, `uv run sync_logs.py pull` copies new logs into logs/ (a game pushed again, e.g. after a
mid-game push, replaces its earlier copy and that copy's .txt/.html/feedback files), adds their lessons to
the tips notebook and publishes the new sheet to the branch (`--no-tips` only copies logs). A PC game also
publishes the sheet when it updates it, so cloud games get it without a pull.
`lessons.jsonl` and `alerts_reviewed.json` are merged, not overwritten; mock games are never synced.

## Checking changes

- `uv run pytest` runs the scenario and visibility tests (offline, about 10 seconds). Run it before
  every commit, and add a test when you fix a rules bug or change a code-handled role.
- `uv run ruff check .` catches undefined names, unused imports and likely bugs; `uv run mypy .` checks
  types (e.g. a possibly-None value used as a player).
- `uv run mafia.py --mock` plays a full offline game; the same `--seed` replays the same game. Its
  moderator only carries out the Katana attack, so moderator-handled roles are only exercised in live games.
- `uv run stats.py` reads every finished live game in `logs/`: win rates by faction, model and role (with
  95% intervals), Village win rate with and without each role, and per-decision skill by model or role.
  Logs are on Kevin's PC; `--csv DIR` exports the tables.
- `tests/conftest.py` has `ScriptedClient` (players answer "do nothing" unless a `decide` function says
  otherwise; the moderator makes queued tool calls) and `game_factory` (seats Alice, Bob, ... with the
  roles you give, in order).

## Roles

- `uv run mafia.py --list-roles` shows how every role is implemented: its code hooks and night note
  are read from the code; `tested` and `notes` in its `ROLES` entry are kept by hand. Check it there
  instead of auditing the code. Set `tested=True` when a role is first seen working in a live game, and
  update `notes` when its handling changes.
- Adding or changing a role can touch all of these; check each one:
  1. `roles/__init__.py`: `ROLES` entry (alignment, category, Sheriff result, defense, tokens,
     `acts_at_night`, `tested`, `notes`).
  2. `roles/<role>.py`: effects that code carries out, as hooks from `roles/base.py` (setup, briefing,
     deaths, dawn, ...). Register the file by importing it at the bottom of `roles/__init__.py`. Core
     code calls hooks and shouldn't name roles; if a role needs a hook that doesn't exist, add one to
     `RoleLogic`. Per-game role state goes in `game.role_state`, not new `Game` fields.
  3. Day mechanics roles trigger (`Game.prosecutions`, `rigged_day`, `puppets`) are generic and live in
     `state.py` and `day.py`; `night_action_schema` in `players.py` is one shape for every role.
  4. `night_note` on the role's class: a reminder the moderator gets each night for effects with no
     submitted action or that need a special op. Only roles in the game are included.
  5. A role-specific `apply_changes` op: declare it in the role's `ops`, validate it in `check_op` (the error goes back to the moderator) and carry it out in `apply_op`.
     The moderator is offered it only when the role is in the game. Ops every game needs are
     `CORE_OPS` in `moderator.py`.
  6. `tests/test_roles.py`: a scenario test for anything code carries out. Every role also gets a mock-game
     smoke test automatically (`test_every_role_survives_a_mock_game`).
  7. `setups.py` draws random setups (`--roles random:N`) by alignment and category, and `stats.py` scores
     some roles' night decisions (Sheriff, Medic, Vigilante, Katana target); add a scored decision there
     when the role's choices have a clear right answer.

## Conventions

- Hidden information: every `game.emit(...)` passes `visible_to` (None means everyone). A wrong list
  leaks secrets into other players' prompts; `tests/test_visibility.py` checks this per category.
- Every `emit` also passes `cat=` (`CHAT`, `PM`, `DEATH`, ... in `events.py`) plus that category's fields.
  The log viewer colors events by `cat`, never by their wording, so wording can change freely.
- `Player.status` keys that code reads are in `roles.Status`; use the constants, not strings.
- Logs are meant for analysis across games: each record kind keeps stable fields. If you change a
  record's fields, bump `LOG_VERSION` in `gamelog.py` (it's written in the "setup" record).
- Night checks (`night_check.py`, on by default) log a judge model's verdict on each night's moderator
  resolution as "night_check" records; they never change the game.
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
  (which games, which kinds, likely cause), then `uv run alerts.py --ack all` once he has seen them. Finished
  games also print a reminder line while anything is unreviewed. A new error kind needs no registration;
  anything that goes through `game.log.error` shows up everywhere above.
- Every model is pinned to its maker's own OpenRouter provider (`PROVIDERS` in `llm.py`); add one
  there for a new maker.
- Tips from past games (`tips.py`): `uv run tips.py build` distills the lessons and strategy reviews in
  game logs: each new game updates a verbose notebook (`tips/tips_notebook.json`/`.md`: every tip with its
  evidence, weights and reports against it, changed only through small ops) and the short sheet players get
  (`tips/tips.md`) is rewritten from it. Feedback from players who had tips and the moderator (`tips_feedback`)
  counts as evidence. games do this when they end, by default (`--no-update-tips` to skip; mock games use `logs/mock_tips/`); `--tips FILE --tips-for all|half|names|models` puts it in chosen players'
  system prompts, and `--player-tips WHO=FILE|none,...` sets each player's or model's file. Players see
  every section (all factions and roles). The models learn collectively: one file pools every model's lessons. The
  "tips" record and `tips` in the result's players say who had them, for comparing against fresh players.
  Lessons are weighted by their author's model strength and the game's average (`STRENGTH` in `tips.py`,
  1-5, kept by hand; a new model needs an entry there).
- Program safeguards that aren't rules from `rules_1.txt` are marked as such in code and in game text.
  Currently: a game stops with no winner after (players + 10) days (`EXTRA_DAYS` and `--max-days` in
  `mafia.py`), so a stuck game can't run forever.
