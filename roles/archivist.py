"""Archivist: once per game, sees the roles of a random three quarters of the other living players."""

from events import RESULT
from roles.base import RoleLogic, register

PENDING = "archive_uses"  # game.role_state: Archivists who consulted the archive tonight
SHARE = 0.75  # rules: floor(0.75 * N) of the other living players


@register("Archivist")
class Archivist(RoleLogic):
    roleplayer_can_fake = False  # code draws the sample
    night_note = ("An Archivist who spent their token (and wasn't role-blocked): use the archive op, which spends "
                  "the token; code shows them the sampled roles at dawn.")
    ops = {"archive": ({"by"}, set(), "{op:'archive', by}: the Archivist `by` consults the archive (spends their "
                                      "token; code draws and tells the roles at dawn)")}

    def check_op(self, game, change):
        by = game.player(change["by"])
        if by.role != "Archivist" or not by.alive:
            return f"{by.name} is not a living Archivist"
        if by.tokens.get("archive", 0) < 1:
            return f"{by.name} has no archive token left"
        return None

    def apply_op(self, game, change):
        game.player(change["by"]).tokens["archive"] -= 1
        game.role_state.setdefault(PENDING, []).append(change["by"])

    def at_dawn(self, game):
        for name in game.role_state.pop(PENDING, []):
            if not game.player(name).alive:  # died the same night: the result is never read
                continue
            others = [p for p in game.alive() if p.name != name]
            drawn = game.rng.sample(others, int(len(others) * SHARE))
            roles = ", ".join(sorted(p.role for p in drawn)) or "none"
            text = f"The archive shows {len(drawn)} of the {len(others)} other living players' roles: {roles}."
            game.emit(f"Moderator (private): {text}", [name], cat=RESULT, message=text)
