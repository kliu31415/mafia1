"""Decoy: a Neutral that wins by dying at night; next Day's announcement names its killers among 3 players."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RoleLogic, join_names, register

if TYPE_CHECKING:
    from state import Game, Player

NAMED = 3  # rules (Decoy): how many players the announcement names
KILLED = "decoys_killed"  # game.role_state: Decoys an attack killed tonight, announced at the end of the night
REVEALED = "decoys_revealed"  # game.role_state: Decoys whose death announcement shows the role


@register("Decoy")
class Decoy(RoleLogic):
    blocks_win = False
    night_end_order = 2  # after a Cursed player's curse, so the curse's victim isn't named as alive
    night_note = ("Decoy: code handles its win and next Day's announcement. When an attack kills a Decoy, list in "
                  "the kill's `by` every player whose attack would have killed them (R12): code names them.")

    def on_death(self, game: Game, p: Player, guilty_voters: list[str] | None) -> None:
        if game.phase != "night":  # rules (Decoy): only a night death wins
            return
        game.personal_winners.append(p.name)
        game.log.write("decoy_won", player=p.name, day=game.day)
        game.role_state.setdefault(KILLED, []).append(p.name)

    def at_night_end(self, game: Game) -> None:
        for name in game.role_state.pop(KILLED, []):
            p = game.player(name)
            killers = [k for k in dict.fromkeys(p.death["killers"] if p.death else []) if k != name]
            if not killers:  # a death no one attacked for (heartbreak): it still wins, but nothing is named
                continue
            game.rng.shuffle(killers)
            named = killers[:NAMED]
            others = sorted(q.name for q in game.alive() if q.name not in killers)
            named += game.rng.sample(others, min(NAMED - len(named), len(others)))
            game.rng.shuffle(named)
            game.role_state.setdefault(REVEALED, []).append(name)
            game.log.write("decoy", player=name, named=named, killers=killers[:NAMED], day=game.day)
            who = f"At least one of {join_names(named)} killed them" if len(named) > 1 else f"{named[0]} killed them"
            game.pending_announcements.append(f"{name} was the Decoy, who wins by dying at night. {who}.")
            game.death_record.append(f"Night {game.day}: {name} was the Decoy. {who}.")  # the ledger

    def reveals_on_death(self, game: Game, dead: Player) -> str | None:
        return "They were the Decoy" if dead.name in game.role_state.get(REVEALED, []) else None
