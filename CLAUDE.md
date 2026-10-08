# mafia1

The module map is in `mafia.py`'s docstring. The rules are `rules_1.txt` (Kevin's text; don't edit it
unless asked).

## Checking changes

- `uv run pytest` runs the scenario and visibility tests (offline, about a second). Run it before
  every commit, and add a test when you fix a rules bug or change a code-handled role.
- `uv run ruff check .` catches undefined names, unused imports and likely bugs.
- `uv run mafia.py --mock` plays a full offline game. Its moderator only carries out the Katana attack,
  so moderator-handled roles are only exercised in live games.
- Live (API) games cost money: skip them for small changes. For bigger ones use a small game with cheap
  player models (haiku-5.5, gpt-6-luna) and run it in the background.
- `tests/conftest.py` has `ScriptedClient` (players answer "do nothing" unless a `decide` function says
  otherwise; the moderator makes queued tool calls) and `game_factory` (seats Alice, Bob, ... with the
  roles you give, in order).

## Roles

- Which roles are implemented, and how, is tracked in `ROLE_STATUS` in `roles.py` (print it with
  `uv run mafia.py --list-roles`). Check it there instead of auditing the code, and update it whenever
  a role's handling changes or a role is first seen working in a live game.
- Adding or changing a role can touch all of these; check each one:
  1. `roles.py`: `ROLES` entry (alignment, category, Sheriff result, defense, tokens, `acts_at_night`)
     and `ROLE_STATUS`.
  2. `state.py`: role-specific logic in `Game.kill`, `setup_game`, `check_winner`, dawn effects, and
     any per-role `Game` field (e.g. `rigged_day`, `puppets`).
  3. `players.py`: `role_briefing` (what the player is told at the start) and `night_action_schema`.
  4. `night.py`: the moderator's night instructions, which list passive effects by hand.
  5. `moderator.py`: a new `apply_changes` op needs an `OPS` entry, a `dispatch` case and a line in the
     tool description.
  6. `tests/test_rules.py`: a scenario test for anything code carries out.

## Conventions

- Hidden information: every `game.emit(...)` passes `visible_to` (None means everyone). A wrong list
  leaks secrets into other players' prompts; `tests/test_visibility.py` checks this per category.
- Every `emit` also passes `cat=` (`CHAT`, `PM`, `DEATH`, ... in `state.py`) plus that category's fields.
  The log viewer colors events by `cat`, never by their wording, so wording can change freely.
- `Player.status` keys that code reads are in `state.Status`; use the constants, not strings.
