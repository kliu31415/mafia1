"""Scripts (scripts.py): the roles a game can use, the rules text players get, and draws that stay on the script."""

import json
import random

import mafia
import role_summaries
import scripts
from llm import MockClient, Model
from roles import ROLES, Status, logic
from setups import SETUPS, setup_note

RULES = mafia.RULES_PATH.read_text(encoding="utf-8")


def role_paragraphs(text: str) -> set[str]:
    """Role names with a paragraph in this rules text's roles part (as role_summaries reads them)."""
    lines = text.split("PART 6: ROLES", 1)[1].splitlines()
    return {line.strip() for i, line in enumerate(lines[:-1])
            if line.strip() in ROLES and not line.startswith(" ") and lines[i + 1].startswith("  ")}


def test_scripts_name_known_roles_and_can_fill_a_setup():
    for name, roles in scripts.SCRIPTS.items():
        assert roles is None or (set(roles) <= set(ROLES) and len(set(roles)) == len(roles)), name
        assert "Vanilla Villager" in scripts.roles_of(name)  # setups fill seats with it
    assert scripts.roles_of("all") == list(ROLES)
    assert 25 <= len(scripts.CORE) <= 35


def test_the_all_script_keeps_the_rules_text_unchanged():
    assert scripts.rules_for(RULES, "all") == RULES
    assert role_paragraphs(RULES) == set(role_summaries.role_paragraphs()) == set(ROLES)


def test_a_script_keeps_only_its_roles_and_the_general_rules():
    text = scripts.rules_for(RULES, "core")
    assert role_paragraphs(text) == set(scripts.CORE)
    for label in ("R1 (", "R8 (", "R19 (", "R23 ("):  # general rules all stay
        assert label in text
    assert "Script: this game uses the core script" in text and f"only its {len(scripts.CORE)} roles" in text
    assert len(text) < len(RULES) * 0.8


def test_headings_without_roles_on_the_script_are_dropped(monkeypatch):
    monkeypatch.setitem(scripts.SCRIPTS, "tiny", ["Vanilla Villager", "Sheriff", "Grunt"])
    part = scripts.rules_for(RULES, "tiny").split("PART 6: ROLES", 1)[1]
    lines = set(part.splitlines())
    assert {"Townsfolk (most villagers, helpful to the Village)", "Investigative", "--- Yakuza (Evil) ---"} <= lines
    assert not {"Combat", "Misc", "--- Neutral ---"} & lines
    assert not any(line.startswith("Outsiders") for line in lines)
    assert "Every role lists the same fields" in part and "(2 Village, 1 Yakuza, 0 Neutral)" in part


def test_setups_draw_only_script_roles():
    core = set(scripts.CORE)
    for name, setup in SETUPS.items():
        for seed in range(30):
            roles = setup.draw(13, random.Random(seed), "all", script="core")
            assert len(roles) == 13 and set(roles) <= core, (name, seed, set(roles) - core)


def test_draws_of_any_role_stay_on_the_script(game_factory):
    from roles.archivist import archive_roles
    from roles.profiler import profile_candidates
    from roles.vulture import report_deaths
    from tests.conftest import told
    core = set(scripts.CORE)
    game, _ = game_factory(["Archivist", "Profiler", "Vulture", "Roleplayer", "Sheriff", "Grunt", "Jester",
                            "Vanilla Villager"])
    game.rule_settings["script"] = "core"
    game.phase = "night"
    for seed in range(100):
        game.rng = random.Random(seed)
        shown = archive_roles(game, game.player("Alice"))[2]
        # Vulture and Roleplayer aren't on the core script, but are real roles here: only fakes must be on it
        assert set(shown) - core <= {"Vulture", "Roleplayer", "Archivist", "Profiler"}
        assert set(profile_candidates(game, "Bob", "Frank")) - {"Grunt"} <= core | {"Vulture", "Roleplayer",
                                                                                   "Archivist"}
        logic("Roleplayer").setup(game, game.player("Dave"))
        assert game.player("Dave").status[Status.FAKE_ROLE] in core
    fakes: set[str] = set()
    game.player("Grace").death = {"day": game.day, "phase": "night", "cause": "Katana"}  # the Jester
    for seed in range(60):
        game.rng = random.Random(seed)
        game.role_state.clear()
        report_deaths(game, [game.player("Carol")])
        fakes.add(told(game, "Carol")[-1].rsplit("Grace: ", 1)[1].rstrip("."))
    assert fakes <= core and len(fakes) > 3


def test_a_mock_game_on_a_script_plays_by_its_rules(tmp_path, monkeypatch):
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    roles = ["Sheriff", "Medic", "Vanilla Villager", "Lookout", "Grunt", "Pharmacist"]
    path = mafia.play_game(MockClient(3), mafia.GameConfig([Model.HAIKU_5_5], Model.HAIKU_5_5, roles, seed=3,
                                                           script="core"))
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    setup = records[0]
    assert setup["settings"]["script"] == "core" and records[-1]["kind"] == "result"
    played = scripts.rules_for(RULES, "core") + setup_note(None, roles)  # the cut rules, with the default settings
    assert setup["rules_sha256"] == mafia.game_meta(played, {})["rules_sha256"]


def test_the_roles_part_is_still_shaped_the_way_scripts_cut_it():
    """scripts.rules_for cuts rules_1.txt's roles part into blank-line-separated blocks: each role's paragraph is its
    name (exactly as in ROLES) and then only indented lines, with no blank line inside it; everything else is a
    heading or the part's intro. If an edit breaks that shape (a blank line inside a role, a renamed role, a new part
    after the roles), a cut script would keep stray text or lose a heading, so this fails first."""
    part = RULES.split("PART 6: ROLES", 1)[1]
    assert "\nPART " not in part and "=== PART" not in part  # the roles part is the last one
    for block in part.strip("\n= ").split("\n\n"):
        first, *rest = block.split("\n")
        if first in ROLES:
            assert rest and all(line.startswith("  ") for line in rest), f"{first}: its name, then indented lines"
        else:
            assert not first.startswith(" "), f"text with no role above it (a blank line inside a role?): {first!r}"
            assert len(rest) <= 2, f"an unknown block (not a role in ROLES?): {first!r}"
