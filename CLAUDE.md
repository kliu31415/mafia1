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

## Checking changes

- `uv run pytest` runs the scenario and visibility tests (offline, about 10 seconds). Run it before
  every commit, and add a test when you fix a rules bug or change a code-handled role.
- `uv run ruff check .` catches undefined names, unused imports and likely bugs; `uv run mypy .` checks
  types (e.g. a possibly-None value used as a player).
- `uv run mafia.py --mock` plays a full offline game; the same `--seed` replays the same game. Its
  moderator only carries out the Katana attack, so moderator-handled roles are only exercised in live games.
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
  5. A role-specific `apply_changes` op: declare it in the role's `ops` and carry it out in `apply_op`.
     The moderator is offered it only when the role is in the game. Ops every game needs are
     `CORE_OPS` in `moderator.py`.
  6. `tests/test_roles.py`: a scenario test for anything code carries out. Every role also gets a mock-game
     smoke test automatically (`test_every_role_survives_a_mock_game`).

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
- Program safeguards that aren't rules from `rules_1.txt` are marked as such in code and in game text.
  Currently: a game stops with no winner after (players + 10) days (`EXTRA_DAYS` and `--max-days` in
  `mafia.py`), so a stuck game can't run forever.
