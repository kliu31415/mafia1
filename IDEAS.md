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
  Saves about 30%. Small loss: trial comments are mostly people explaining their vote, so few
  replies to each other are lost.
- **Chat in 2-3 batches per round.** Each batch sees what earlier batches said. Chat 2-3x faster
  while keeping most back-and-forth. Together with parallel trials: roughly 21 min -> 8 min.
- **Several games at once** (e.g. a `--games N` flag). No change to the game at all; multiplies games
  per hour, limited only by OpenRouter rate limits.
