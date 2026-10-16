"""Insomniac: with a token, lies awake and learns the roles of up to 3 random players who visited someone that
night, in alphabetical order, without names."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import (Alignment, RecordedAction, RoleLogic, acted_tonight, fake_visits, is_fake, register, seen_role,
                        tokens_left_text)

if TYPE_CHECKING:
    from state import Game, Player

HEARS = 3  # rules: up to 3 visitors' roles
AWAKE = "insomniac_awake"  # game.role_state: Insomniacs who spent a token tonight, told once the visits are in


# Roles that act at night but whose actions are never visits (R6), so a real Insomniac can't hear them: a
# Roleplayer's random result leaves them out (a fake Oracle visitor decided game_20261016_032352_2).
# test_insomniac_fakes_name_only_roles_that_can_visit keeps this in step with the rules.
NEVER_VISITS = {"Archivist", "Cartographer", "Coroner", "Insomniac", "Oracle", "Roleplayer", "Veteran"}


def can_visit(role: str) -> bool:
    """Whether a player with this role can visit someone (R6): any Yakuza (the Katana), or a night action that can be
    a visit."""
    from roles import ROLES
    info = ROLES[role]
    return info.alignment is Alignment.EVIL or (info.acts_at_night and role not in NEVER_VISITS)


def random_visitor_roles(game: Game, n: int) -> list[str]:
    """n random roles on the game's script that can visit (can_visit), never a second copy of a unique role (R2)."""
    from roles import ROLES
    from scripts import script_roles
    pool = sorted(r for r in script_roles(game) if can_visit(r))
    roles: list[str] = []
    for _ in range(n):
        roles.append(game.rng.choice([r for r in pool if not (ROLES[r].unique and r in roles)] or pool))
    return roles


@register("Insomniac")
class Insomniac(RoleLogic):
    roleplayer = "code"  # random roles, as many as random visits give
    code_tells_user = True
    action = RecordedAction("stay_awake", "stays awake (code tells them visitors' roles at the end of the night)",
                            "code tells them the roles of up to 3 random players from your record_visits list",
                            token="insomniac", target="",
                            note="Staying awake is not a visit: don't put it in record_visits.")

    def carry_out(self, game: Game, by: Player, target: Player | None) -> None:
        game.role_state.setdefault(AWAKE, []).append(by.name)

    fake_carry_out = carry_out  # at_night_end gives a Roleplayer random roles

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
            p = game.player(name)
            if is_fake(p):  # a Roleplayer (rules: Roleplayer): random roles, as many as a random night's visitors
                heard_from = len({a for a, _ in fake_visits(game, p)})
                heard = sorted(random_visitor_roles(game, min(HEARS, heard_from)))
            else:
                heard_from = len(pool)
                heard = sorted(seen_role(game, q) for q in game.rng.sample(pool, min(HEARS, len(pool))))
            if not heard:
                text = "You lay awake all night and heard no footsteps: nobody visited anyone tonight."
            elif heard_from <= HEARS:
                text = (f"You lay awake all night and heard every player who visited someone tonight. Their "
                        f"roles: {', '.join(heard)}.")
            else:
                text = (f"You lay awake all night. More than {HEARS} players visited someone tonight; you heard "
                        f"{HEARS} of them, drawn at random. Their roles: {', '.join(heard)}.")
            game.tell([name], f"{text} {tokens_left_text(p, 'insomniac')}.")
