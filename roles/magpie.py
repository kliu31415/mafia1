"""Magpie: steals a token from a player each night, after the night's token use; wins once it has stolen from three
different players. Only drawn into random setups where at least a third of the roles have tokens."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RecordedAction, RoleLogic, Status, acted_tonight, logic, register, true_tokens

if TYPE_CHECKING:
    from state import Game, Player

ROLE = "Magpie"
NEEDED = 3
TONIGHT = "magpie_steals"  # game.role_state: {day: [(magpie, target)]}, carried out at the end of the night
ROBBED = "magpie_robbed"  # game.role_state: {magpie: [players it stole a token from]}


@register(ROLE)
class Magpie(RoleLogic):
    blocks_win = False
    code_tells_user = True
    night_end_order = -1  # before results that read token counts (Accountant)
    action = RecordedAction("steal", "steals a token from player",
                            "code takes the token at the end of the night, after this night's token use, and tells "
                            "both of them", visit=True)

    def fits_setup(self, roles: list[str]) -> bool:
        from roles import ROLES
        return 3 * sum(bool(ROLES[r].tokens) for r in roles) >= len(roles)

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        assert target
        game.role_state.setdefault(TONIGHT, {}).setdefault(game.day, []).append((by.name, target.name))

    def at_night_end(self, game: Game) -> None:
        for name, target_name in game.role_state.get(TONIGHT, {}).pop(game.day, []):
            me, target = game.player(name), game.player(target_name)
            robbed = game.role_state.setdefault(ROBBED, {}).setdefault(name, [])
            if target_name in robbed:
                game.tell([name], f"You already stole from {target_name}, so you took nothing: a Magpie needs two "
                          "different players.")
                continue
            if not (tokens := true_tokens(target)):
                game.tell([name], f"{target_name} had no tokens, so you stole nothing.")
                continue
            kind = game.rng.choices(list(tokens), list(tokens.values()))[0]
            target.tokens[kind] -= 1
            robbed.append(target_name)
            game.log.write("steal", player=name, target=target_name, token=kind, day=game.day)
            game.tell([name], f"You stole a token from {target_name} ({len(robbed)} of {NEEDED}).")
            if target.alive:
                game.tell([target_name], f"A Magpie stole one of your {kind} tokens. You have {target.tokens[kind]} "
                          "left.")
            if len(robbed) >= NEEDED and acted_tonight(game, me):
                win(game, me)


def win(game: Game, me: Player) -> None:
    game.personal_winners.append(me.name)
    if not me.alive:  # died tonight: a dead winner stays hidden like any death (R12)
        return
    me.alive = False  # leaves the game; not a death
    me.status[Status.LEFT] = True
    game.log.write("left", player=me.name, day=game.day, phase=game.phase)
    game.pending_announcements.append(f"{me.name} was the Magpie and stole enough tokens. They win and leave the game."
                                      + (f" Their last will: \"{me.last_will}\"" if me.last_will else ""))  # R12
    game.death_record.append(f"Day {game.day}: {me.name} (Magpie) won and left the game")
    for q in game.alive():  # leaving counts as a death for anyone targeting this one (an Executioner, ...)
        logic(q.role).on_other_death(game, q, me, None)

