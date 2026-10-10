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

## Turned down for now

- **Whistleblower and Herald** (proposed Oct 10, 2026; Kevin: punt for now). Whistleblower (Village, 1 token): the
  next Day's trial votes are all public. Herald (Village, 1-2 tokens): publicly reveals one dead player's role at
  dawn, a public Coroner. Both undo the hidden-info defaults for a moment, which is their appeal and their risk.

- **End the game once a faction has an unbreakable voting majority** (suggested by a player in
  game_20261009_121338_61703, whose last day was a foregone 3-vs-2 hang). Would cut hollow final days.
  Turned down (Kevin, 2026-10-09): factions can still occasionally win from a minority, e.g. with a
  Medic save, a Vigilante shot or a Clerk rig, so "unbreakable" is hard to define in general.
