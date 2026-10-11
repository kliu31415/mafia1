"""Chronicler: marks players; a marked player's death reveals their role publicly, unless a Mortician cleans them."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import (RecordedAction, RoleLogic, Status, chosen_name, join_names, register,
                        tokens_left_text)

if TYPE_CHECKING:
    from state import Game, Player

MARKS = "chronicler_marks"  # game.role_state: Chronicler's name -> the players they chose to mark (R23)


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
        # Only the user's own marks, by the names they chose: refusing another Chronicler's mark would tell them a
        # second Chronicler exists, and refusing where their own swapped mark landed would show the swap (R23).
        if target and (chosen := chosen_name(game, target.name)) in game.role_state.get(MARKS, {}).get(by.name, []):
            return f"{by.name} already marked {chosen}; marking them again would change nothing"
        return None

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        assert target
        target.status.setdefault(Status.MARKED, by.name)  # another Chronicler's earlier mark stays theirs
        chosen = chosen_name(game, target.name)  # after a swap the mark is on `target`, but the user chose `chosen`
        game.role_state.setdefault(MARKS, {}).setdefault(by.name, []).append(chosen)
        game.tell([by.name], f"You marked {chosen}: if they die, at any time, their role will be revealed "
                             f"to everyone (unless a Mortician cleans them). {tokens_left_text(by, 'chronicler')}.")

    def reveals_on_death(self, game: Game, dead: Player) -> str | None:
        return "They had been marked by a Chronicler" if dead.status.get(Status.MARKED) else None

    def briefing(self, game: Game, p: Player) -> list[str]:
        marked = [n for n in game.role_state.get(MARKS, {}).get(p.name, []) if game.player(n).alive]
        return [f"Your marks on living players: {join_names(marked)}." if marked else
                "None of your marks is on a living player."]
