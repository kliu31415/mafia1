"""Insomniac: with a token, lies awake and learns the roles of up to 3 random players who visited someone that
night, in alphabetical order, without names."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RecordedAction, RoleLogic, acted_tonight, register, tokens_left_text

if TYPE_CHECKING:
    from state import Game, Player

HEARS = 3  # rules: up to 3 visitors' roles
AWAKE = "insomniac_awake"  # game.role_state: Insomniacs who spent a token tonight, told once the visits are in


@register("Insomniac")
class Insomniac(RoleLogic):
    roleplayer_can_fake = False  # code draws the visitors from the recorded visits
    code_tells_user = True
    action = RecordedAction("stay_awake", "stays awake (code tells them visitors' roles at the end of the night)",
                            "code tells them the roles of up to 3 random players from your record_visits list",
                            token="insomniac", target="",
                            note="Staying awake is not a visit: don't put it in record_visits.")

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        game.role_state.setdefault(AWAKE, []).append(by.name)

    def at_night_end(self, game: Game) -> None:
        awake = game.role_state.pop(AWAKE, [])
        if not awake:
            return
        visits = game.night_visits.get(game.day)
        if visits is None:  # the moderator didn't record_visits (logged as visits_missing); a spent token stays spent
            game.log.error("insomniac_no_visits", f"night {game.day}: no visits were recorded, so the Insomniac "
                           "got no result", day=game.day, players=awake)
            return
        # Every player who visited anyone (themselves too), in seat order so the draw only depends on the seed.
        visitors = {a for a, _ in visits}
        pool = [p for p in game.players if p.name in visitors and acted_tonight(game, p)]
        for name in awake:
            heard = sorted(p.role for p in game.rng.sample(pool, min(HEARS, len(pool))))
            p = game.player(name)
            if not heard:
                text = "You lay awake all night and heard no footsteps: nobody visited anyone tonight."
            elif len(pool) <= HEARS:
                text = (f"You lay awake all night and heard every player who visited someone tonight. Their "
                        f"roles: {', '.join(heard)}.")
            else:
                text = (f"You lay awake all night. More than {HEARS} players visited someone tonight; you heard "
                        f"{HEARS} of them, drawn at random. Their roles: {', '.join(heard)}.")
            game.tell([name], f"{text} {tokens_left_text(p, 'insomniac')}.")
