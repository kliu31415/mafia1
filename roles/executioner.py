"""Executioner: wins if their target is hanged; becomes a Jester if the target dies otherwise."""

from events import DEATH
from roles.base import RoleLogic, Status, logic, register


@register("Executioner")
class Executioner(RoleLogic):
    blocks_win = False
    night_note = "Executioner revenge attacks are carried out by code after you finish; don't resolve them."

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
            game.emit(f"{me.name} was the Executioner, whose target was {dead.name}. They win and leave the game."
                      + (f" Last will: {me.last_will!r}" if me.last_will else ""), cat=DEATH)  # rules R12
            game.death_record.append(f"Day {game.day}: {me.name} (Executioner) won and left the game")
            for q in game.alive():  # leaving counts as a death, e.g. for an Executioner targeting this one
                logic(q.role).on_other_death(game, q, me, None)
        elif game.phase == "night":
            # Night deaths are simultaneous (R10): if the Executioner dies tonight too, they die an Executioner.
            game.role_state.setdefault(TURN_JESTER, []).append(me.name)
        else:
            turn_jester(game, me)

    def at_dawn(self, game):
        for name in game.role_state.pop(TURN_JESTER, []):
            if (me := game.player(name)).alive and me.role == "Executioner":
                turn_jester(game, me)


TURN_JESTER = "executioners_turning_jester"  # game.role_state: whose targets died tonight, not by hanging


def turn_jester(game, me):
    # Our reading of "if you die of other means": the target dying otherwise.
    me.role = "Jester"
    game.emit("Your target died other than by hanging. You are now a Jester.", [me.name])
