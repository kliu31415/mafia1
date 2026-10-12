# Ideas backlog

Ideas considered but not built yet, with their tradeoffs. Move an item out when it's built or dropped.

## Faster games

Measured on an 8-player live game (2026-10-08, 21 minutes): 83% of the time was chat turns, which
run one player at a time (day chat 91 turns / 11 min, trial discussion 39 turns / 6.4 min). Votes and
night actions already run in parallel.

- **Fully simultaneous chat rounds.** Everyone writes their turn at once and sees the round's messages
  next round. About 3-4x shorter games (21 min -> ~6), more with more players.
  Costs: replies lag a full round (an accused player can't answer until next round), crosstalk and
  pile-ons, a tie-break rule for multiple nominations in one round, and less of the real-time reaction
  reading that Mafia relies on.
- **Parallel trial discussion.** The accused speaks first, then everyone else comments at once.
  Trial turns were 31% and 20% of play time in two 12-player games (2026-10-09), so this saves 10-18
  minutes a game. Punted (Kevin, 2026-10-09) as too big a change in play: trial comments build on each
  other (64-80% name an earlier commenter, e.g. "Mallory's question is the key one"), and nearly every
  player speaks (97 of 101 trial turns, ~55 words each). Two batches would keep part of that chain and save
  about half the trial time.
- **Chat in 2-3 batches per round.** Each batch sees what earlier batches said. Chat 2-3x faster
  while keeping most back-and-forth. Together with parallel trials: roughly 21 min -> 8 min.
- **Several games at once** (e.g. a `--games N` flag, with a `--budget $X` that stops starting new
  games once spent). No change to the game at all; multiplies games per hour, limited only by
  OpenRouter rate limits. Matters for `stats.py`: with the Yakuza winning about 1 game in 5, telling a
  role's or model's win rate apart from another's takes on the order of 100 games per setup.

## Other ways to run models

- **GPT models through the Codex CLI** (Kevin, Oct 11 2026: backlog unless he moves to a bigger Codex plan). Like
  `claude_code.py`, but `codex exec` on a ChatGPT subscription. Checked on the PC (codex-cli 0.162.0-alpha, Plus plan):
  a real night-action prompt gave schema-valid answers from gpt-6-luna and gpt-6-sol in 5-8 s, no tool use, five
  calls at once. What a module needs: `-c model_instructions_file=FILE` (the game's system prompt in place of
  Codex's), `--output-schema FILE`, `--json`, `-s read-only --skip-git-repo-check --ephemeral --ignore-user-config`,
  the prompt on stdin (`-`); the `include_*_instructions=false` keys, `skills.bundled.enabled=false` and
  `--disable` for tool features; and a model catalog (`-c model_catalog_json=FILE`) made at start-up from
  `codex debug models` with `tool_mode`, `multi_agent_version` and `model_messages` removed, which is the only way to
  drop the code-execution tool and the "you lead a team of agents" messages (13.7k -> 0.6k tokens of overhead; check
  with `codex debug prompt-input`). Usage isn't in the events: `codex app-server` answers `account/rateLimits/read`
  (5-hour and weekly `usedPercent`, `resetsAt`). The blocker is the limit: 30 small Sol calls used 5% of the 5-hour
  window and 1% of the week, so an 8-player all-Sol game is about one whole window and a 13-player one about two
  (rough, within 2x). Not checked: the moderator's tool loop, what a refused call looks like, reasoning summaries.

## Analysis

- **Suspicion over time.** Who each player thinks is evil, turn by turn, would show how fast each
  model finds the Yakuza and which claims or wills change minds. Two ways to get it:
  - Extract it after the game from what's already logged: every player call has `thoughts` and the
    notepad before and after. No game change, but it needs a cheap judge call per turn (or per day),
    and turns where a player didn't write down suspicions come out blank.
  - A private `suspects` field on every turn (1-3 names). Uniform and free to analyse, a few output
    tokens a turn, but asking every turn may itself make players think about suspicion more, which
    changes their play a little.
- **Decision puzzles from checkpoints.** Replay one saved moment (a close trial vote, a Sheriff
  deciding whether to claim) with many models, many times. Same situation, so little variance, and one
  call per sample instead of a whole game: the cheapest per-model comparison.
- **More scored decisions in `stats.py`.** Role-blocks (Pharmacist, Party Animal), Lookout/Tracker
  targets, and whether claims were true (claims are free text, so that needs a judge pass).

## Balance

- **Roleplayer and Ex-Con under hidden flips.** Before the hidden-info defaults, a flip cleared them: a dead
  Roleplayer's false results were exposed, and a hanged Ex-Con showed as a Villager. Now neither happens, so both
  probably cost the Village more than before. Kevin (Oct 10, 2026): leave them and their odds in `setups.py` alone
  until there's data. Options then: draw them less often in random setups, or give the Roleplayer a tell.
- **Ritualist under hidden roles.** Most Village roles are claimed, so its exact-role guesses get easier and its
  Divine attack ignores the Medic. Watch its kills per game before changing it.
- **Yakuza bluffs on a script** (Kevin, Oct 11 2026: backlog). With a script (`scripts.py`), a role not on it is
  known not to be in the game, which narrows fake claims and helps the Village. As in Blood on the Clocktower, the
  Yakuza could be told 2-3 script roles that aren't in play, as safe claims. Open choices: how many, whether
  Neutrals get some, and whether script size is enough of a lever on its own.
- **Tips on a script.** Players on the core script read tips about the Fixer and Ballot Stuffer, which aren't on
  it, and one asked for those to be dropped (game_20261011_011316_850196). The tips sheet could leave out role
  sections for roles off the script, and the general sections' mentions of them.
- **Script revisions at scale** (Kevin, Oct 11 2026). Every rules edit makes every hand-made script's cached
  revision stale (`rules_scripts/`), and each is remade by hand or by an Opus call. Fine for a few scripts; with
  many, explore not regenerating on every change: e.g. reapply the old edits automatically when their passages are
  still there and only flag scripts whose edited passages changed, revise only the paragraphs that changed, or let
  a stale script keep its old edits with a warning instead of failing the test.
- **Random scripts.** Besides hand-made scripts, draw a ~25-role script for each game (always containing the roles
  in play), so role stats stay poolable across games once there are too many roles to show them all.

## Turned down for now

- **Ventriloquist** (Yakuza, proposed Oct 11, 2026; Kevin: shelved for its bug risk). Forges a player's public
  message and claim that turn for a random half of the other players (2 tokens), or one of their private messages
  (1 token); the victim sees their own text and isn't told. Players then remember the same turn differently, a pure
  deception test. Cost: the claim ledger becomes per player (each claim entry records who saw it), plus split events
  for the moderator's public history, logs and reviews; about 200 lines, moderate bug risk. Caching is unaffected
  (the ledger is in the uncached part of the prompt). Simpler versions were dropped as a weaker Puppeteer.
- **Slippery trait** (Kevin, Oct 12 2026: punted). Once a game, a player voted Guilty isn't hanged: the moderator
  announces they're Slippery and the Day ends as usual. Any faction, so surviving clears nobody. It wastes a hang
  (only 55% of Days end in one), so it's worth more to a Yakuza (power ~0.3) than a Villager (~0.1), but it's
  mostly a one-day delay, since the town can re-hang them the next Day. Variant: the holder chooses whether to slip
  after seeing the vote (one extra yes/no call), which gives them a decision. A slip isn't a hanging: no Jester or
  Executioner win, no Martyr or Grudge.
- **Mole and Interceptor** (Oct 11, 2026). Mole (Village posing as Yakuza in their chat): too strong, since one will
  naming every Yakuza ends the game. Interceptor (reads the Yakuza chat under shuffled labels): terse or silent chat
  defeats it, so it mostly taxes Yakuza coordination.

- **Whistleblower and Herald** (proposed Oct 10, 2026; Kevin: punt for now). Whistleblower (Village, 1 token): the
  next Day's trial votes are all public. Herald (Village, 1-2 tokens): publicly reveals one dead player's role at
  dawn, a public Coroner. Both undo the hidden-info defaults for a moment, which is their appeal and their risk.

- **End the game once a faction has an unbreakable voting majority** (suggested by a player in
  game_20261009_121338_61703, whose last day was a foregone 3-vs-2 hang). Would cut hollow final days.
  Turned down (Kevin, 2026-10-09): factions can still occasionally win from a minority, e.g. with a
  Medic save, a Vigilante shot or a Clerk rig, so "unbreakable" is hard to define in general.
