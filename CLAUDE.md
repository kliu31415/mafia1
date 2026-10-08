# mafia1

The module map is in `mafia.py`'s docstring. The rules are `rules_1.txt` (Kevin's text; don't edit it
unless asked).

## Working preferences

- Commit and push straight to `main` once `uv run pytest` and `uv run ruff check .` pass. No need to ask
  first or to open a branch, unless Kevin asks for one.
- Small changes: test with offline mock games only, no live games.
- Bigger changes: also run a live game in the background: about 7-8 players with cheap player models
  (haiku-5.5, gpt-6-luna) and an opus-5.5 moderator. Keep a status line saying a live game is running
  until it finishes (games take 10-40 minutes).
- Low-cost API calls (Haiku, Luna) are fine whenever they help verify that code works.

## Checking changes

- `uv run pytest` runs the scenario and visibility tests (offline, about a second). Run it before
  every commit, and add a test when you fix a rules bug or change a code-handled role.
- `uv run ruff check .` catches undefined names, unused imports and likely bugs.
- `uv run mafia.py --mock` plays a full offline game. Its moderator only carries out the Katana attack,
  so moderator-handled roles are only exercised in live games.
- `tests/conftest.py` has `ScriptedClient` (players answer "do nothing" unless a `decide` function says
  otherwise; the moderator makes queued tool calls) and `game_factory` (seats Alice, Bob, ... with the
  roles you give, in order).

## Roles

- Which roles are implemented, and how, is tracked in `ROLE_STATUS` in `roles/__init__.py` (print it with
  `uv run mafia.py --list-roles`). Check it there instead of auditing the code, and update it whenever
  a role's handling changes or a role is first seen working in a live game.
- Adding or changing a role can touch all of these; check each one:
  1. `roles/__init__.py`: `ROLES` entry (alignment, category, Sheriff result, defense, tokens,
     `acts_at_night`) and `ROLE_STATUS`.
  2. `roles/<role>.py`: effects that code carries out, as hooks from `roles/base.py` (setup, briefing,
     deaths, dawn, ...). Register the file by importing it at the bottom of `roles/__init__.py`. Core
     code calls hooks and shouldn't name roles; if a role needs a hook that doesn't exist, add one to
     `RoleLogic`. Per-game role state goes in `game.role_state`, not new `Game` fields.
  3. Not yet moved into hooks: the Prosecutor, Clerk and Puppeteer `Game` fields (`prosecutions`,
     `rigged_day`, `puppets`) and their handling in `day.py`, and `night_action_schema` in `players.py`.
  4. `night.py`: the moderator's night instructions, which list passive effects by hand.
  5. `moderator.py`: a new `apply_changes` op needs an `OPS` entry, a `dispatch` case and a line in the
     tool description.
  6. `tests/test_rules.py`: a scenario test for anything code carries out.

## Conventions

- Hidden information: every `game.emit(...)` passes `visible_to` (None means everyone). A wrong list
  leaks secrets into other players' prompts; `tests/test_visibility.py` checks this per category.
- Every `emit` also passes `cat=` (`CHAT`, `PM`, `DEATH`, ... in `events.py`) plus that category's fields.
  The log viewer colors events by `cat`, never by their wording, so wording can change freely.
- `Player.status` keys that code reads are in `roles.Status`; use the constants, not strings.
