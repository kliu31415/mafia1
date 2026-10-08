"""Executioner: wins if their target is hanged; becomes a Jester if the target dies otherwise."""

from events import DEATH
from roles.base import RoleLogic, Status, register


@register("Executioner")
class Executioner(RoleLogic):
    blocks_win = False

    def setup(self, game, p):
        p.status[Status.TARGET] = game.rng.choice([q.name for q in game.players if q is not p])

    def briefing(self, game, p):
        return [f"Your target is {p.status[Status.TARGET]}."]

    def on_other_death(self, game, me, dead, guilty_voters):
        if me.status.get(Status.TARGET) != dead.name:
            return
        if guilty_voters is not None:
            game.personal_winners.append(me.name)
            game.pending_revenge.append((me.name, guilty_voters))
            me.alive = False  # leaves the game; not a death
            me.status[Status.LEFT] = True
            game.emit(f"{me.name} was the Executioner, whose target was {dead.name}. "
                      f"They win and leave the game.", cat=DEATH)
            game.death_record.append(f"Day {game.day}: {me.name} (Executioner) won and left the game")
        else:
            # Our reading of "if you die of other means": the target dying otherwise.
            me.role = "Jester"
            game.emit("Your target died other than by hanging. You are now a Jester.", [me.name])
