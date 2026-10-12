"""Enforcer: visits one player a night (a token adds a second) and attacks one who made an Attack that night, Basic or,
with a token, Strong. The moderator resolves it; the briefing spells out what the tokens buy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles.base import RoleLogic, register, tokens_left_text

if TYPE_CHECKING:
    from state import Game, Player


@register("Enforcer")
class Enforcer(RoleLogic):
    night_note = (
        "Enforcer: visits its target, and second_target too if it named one (each a visit). Its tokens_to_spend pays "
        "1 for a second target and 1 for a Strong Attack: with two targets, 1 token means Basic and 2 mean Strong; "
        "with one, 1 token means Strong. Tokens are spent whether or not it attacks (set_tokens). If a player it "
        "visited made an Attack of their own choosing tonight (fatal or not; a Katana attack counts for its holder; "
        "not if role-blocked; a Veteran's alert, a trap or a revenge doesn't count), the Enforcer deals them a Basic Attack, or Strong if paid for; if both "
        "did, random_choice picks one. Tell the Enforcer whether it attacked and whether that killed, or that it "
        "didn't attack; with two targets never say which of them it attacked (with one, naming it is fine).")

    def briefing(self, game: Game, p: Player) -> list[str]:
        # The Medic's two independent token costs were misread until its briefing listed them (Oct 2026).
        return [f"Token costs (set tokens_to_spend to match; {tokens_left_text(p, 'enforcer')}): one target with a "
                "Basic Attack costs 0 tokens, with a Strong Attack 1; two targets (target and second_target) with a "
                "Basic Attack cost 1, with a Strong Attack 2. Tokens are spent whether or not you attack."]
