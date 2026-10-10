"""Chronicler: marks players; a marked player's death reveals their role publicly, unless a Mortician cleans them."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RecordedAction, RoleLogic, Status, join_names, register, tokens_left_text

if TYPE_CHECKING:
    from state import Game, Player


@register("Chronicler")
class Chronicler(RoleLogic):
    roleplayer_can_fake = False  # the reveal is public and done by code
    code_tells_user = True
    action = RecordedAction("mark", "marks player (code reveals their role publicly if they ever die)",
                            "code sets the mark; when the marked player dies, the death announcement reveals "
                            "their role unless a Mortician cleans them", token="chronicler", visit=True,
                            note="The mark lasts for the rest of the game, even after the Chronicler dies. Don't "
                            "tell the marked player.")

    def target_error(self, game: Game, by: Player, target: Player | None) -> str | None:
        if target and target.status.get(Status.MARKED):
            return f"{target.name} is already marked; marking them again would change nothing"
        return None

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        assert target
        target.status[Status.MARKED] = by.name
        game.tell([by.name], f"You marked {target.name}: if they die, at any time, their role will be revealed "
                             f"to everyone (unless a Mortician cleans them). {tokens_left_text(by, 'chronicler')}.")

    def reveals_on_death(self, game: Game, dead: Player) -> str | None:
        return "They had been marked by a Chronicler" if dead.status.get(Status.MARKED) else None

    def briefing(self, game: Game, p: Player) -> list[str]:
        marked = [q.name for q in game.players if q.alive and q.status.get(Status.MARKED) == p.name]
        return [f"Your marks on living players: {join_names(marked)}." if marked else
                "None of your marks is on a living player."]
