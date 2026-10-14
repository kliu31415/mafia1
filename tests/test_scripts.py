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
    for label in ("R1 (", "R8 (", "R19 (", "R24 ("):  # general rules all stay
        assert label in text
    assert "Script: this game uses the core script" in text and f"only its {len(scripts.CORE)} roles" in text
    assert len(text) < len(RULES) * 0.8


def test_headings_without_roles_on_the_script_are_dropped(monkeypatch):
    monkeypatch.setitem(scripts.SCRIPTS, "tiny", ["Vanilla Villager", "Sheriff", "Grunt"])
    part = scripts.rules_for(RULES, "tiny").split("PART 6: ROLES", 1)[1]
    lines = set(part.splitlines())
    assert {"Townsfolk (most villagers, helpful to the Village)", "Investigative", "--- Yakuza (Evil) ---"} <= lines
    assert not {"Killing", "Protective", "Support", "--- Neutral ---"} & lines
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
    played = scripts.rules_for(RULES, "core") + setup_note(None, roles, traits=[])  # the cut rules, default settings
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


# --- the cached revision (scripts.revise) ---------------------------------------------------------------------

def test_every_script_revision_is_current():
    """Fails when rules_1.txt or a script changed since its revision was made: `uv run scripts.py revise` remakes
    the stale ones (an Opus call each), so games on the script play by a reviewed text."""
    stale = [s for s in scripts.SCRIPTS if scripts.stale(RULES, s)]
    assert not stale, f"stale script revisions: {stale}; run `uv run scripts.py revise` and commit rules_scripts/"
    for name in scripts.SCRIPTS:
        if scripts.SCRIPTS[name] is not None:
            assert scripts.role_names(scripts.rules_for(RULES, name)) == scripts.role_names(scripts.cut(RULES, name))


class EditsClient:
    """Answers the reviser's call with the given edits."""
    def __init__(self, edits):
        self.edits, self.calls = edits, 0

    def chat(self, model, messages, **kw):
        from llm import LLMReply
        self.calls += 1
        return LLMReply(json.dumps({"edits": self.edits}), None, [], {}, model.value, 0.1, {})


def test_a_rules_change_makes_the_revision_stale_until_it_is_remade(tmp_path, monkeypatch):
    monkeypatch.setattr(scripts, "CACHE_DIR", tmp_path)
    old = "A role may appear more than once in a game"
    edits = [{"old": old, "new": "A role may appear more than once", "reason": "test"}]
    assert scripts.stale(RULES, "core")  # no cache yet: the plain cut
    assert scripts.rules_for(RULES, "core") == scripts.cut(RULES, "core") + scripts.note("core")
    client = EditsClient(edits)
    scripts.revise(client, RULES, "core")
    assert not scripts.stale(RULES, "core") and client.calls == 1
    revised = scripts.rules_for(RULES, "core")
    assert old not in revised and "A role may appear more than once" in revised
    assert revised.endswith(scripts.note("core"))
    assert scripts.stale(RULES, "all") is False  # "all" is never revised
    changed = RULES.replace("R11 (The circle)\nPlayers sit in a circle.", "R11 (The circle)\nPlayers sit in a ring.")
    assert changed != RULES and scripts.stale(changed, "core")  # any rules edit
    assert "Players sit in a ring." in scripts.rules_for(changed, "core")  # meanwhile: the new cut, unrevised
    (tmp_path / "core.txt").write_text(revised.replace("ring", "loop"), encoding="utf-8")
    assert scripts.stale(RULES, "core")  # a hand-edited cache isn't trusted either


def test_edits_must_match_exactly_once_and_keep_roles_and_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(scripts, "CACHE_DIR", tmp_path)
    for bad in ([{"old": "no such passage", "new": "", "reason": ""}],
                [{"old": "Sheriff", "new": "Sheriff", "reason": "occurs many times"}],
                [{"old": "\nSheriff\n", "new": "\nMarshal\n", "reason": "renames a role"}],
                [{"old": "R11 (The circle)", "new": "The circle", "reason": "drops a label"}]):
        try:
            scripts.revise(EditsClient(bad), RULES, "core")
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted {bad}")
    assert not list(tmp_path.iterdir())  # nothing written


def test_a_game_on_a_stale_script_plays_by_the_cut_and_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(mafia, "LOG_DIR", tmp_path)
    monkeypatch.setattr(scripts, "CACHE_DIR", tmp_path / "none")
    roles = ["Sheriff", "Medic", "Vanilla Villager", "Lookout", "Grunt", "Pharmacist"]
    path = mafia.play_game(MockClient(3), mafia.GameConfig([Model.HAIKU_5_5], Model.HAIKU_5_5, roles, seed=3,
                                                           script="core"))
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["kind"] == "setup" and any(r["kind"] == "script_stale" and r["alert"] for r in records)
    played = scripts.cut(RULES, "core") + scripts.note("core") + setup_note(None, roles, traits=[])
    assert records[0]["rules_sha256"] == mafia.game_meta(played, {})["rules_sha256"]


def test_edits_written_in_a_session_are_recorded_like_an_api_revision(tmp_path, monkeypatch):
    """`scripts.py apply NAME FILE`: a Claude Code session writes the edits instead of an API call."""
    monkeypatch.setattr(scripts, "CACHE_DIR", tmp_path)
    edits = tmp_path / "edits.json"
    edits.write_text(json.dumps({"edits": [{"old": "A role may appear more than once in a game",
                                            "new": "A role may appear more than once", "reason": "test"}]}))
    monkeypatch.setattr("sys.argv", ["scripts.py", "apply", "core", str(edits)])
    scripts.main()
    assert not scripts.stale(RULES, "core")
    assert json.loads((tmp_path / "core.json").read_text())["made_by"] == "a Claude Code session"


def test_roles_the_setup_never_draws_are_named_to_players_and_left_out_of_fakes(game_factory):
    from setups import setup_note
    note = setup_note({"kind": "random", "name": "standard"}, ["Sheriff"] * 13)
    assert "nobody has them: Vanilla Villager, Grunt" in note
    game, _ = game_factory(["Sheriff", "Grunt"])
    assert "Grunt" in scripts.script_roles(game)
    game.rule_settings["setup_off"] = "Vanilla Villager,Grunt"
    assert not {"Vanilla Villager", "Grunt"} & set(scripts.script_roles(game))
    # A hand-picked list leaves them out too, unless it names them.
    hand = setup_note(None, ["Sheriff", "Medic", "Fixer"])
    assert "Any other role in the rules" in hand and "nobody has them: Vanilla Villager, Grunt" in hand
    named = setup_note(None, ["Sheriff", "Grunt", "Vanilla Villager"])
    assert "Any role in the rules" in named and "nobody has them" not in named
    assert "nobody has them: Vanilla Villager." in setup_note(None, ["Sheriff", "Grunt"])
    config = mafia.GameConfig([Model.HAIKU_5_5], Model.HAIKU_5_5, ["Sheriff", "Grunt"])
    assert config.rule_settings["setup_off"] == "Vanilla Villager"
    assert "nobody has them" not in setup_note(None, ["Sheriff"], ())  # an older log's own (grade.py)


def test_hand_picked_traits_are_told_roughly():
    # Kevin, Oct 14 2026: the setup note said only "Players may also have a trait" for hand-picked traits
    roles = ["Sheriff", "Medic", "Fixer"]
    assert "Nobody has a trait (R24)" in setup_note(None, roles, traits=[])
    assert "roughly 2 to 4 in all" in setup_note(None, roles, traits=["Martyr+Armed", "Grudge@Yakuza"])
    assert "roughly 1 to 3 in all" in setup_note(None, roles, traits=["Bonded"])  # a pair: two holders
    drawn = {"kind": "random", "name": "standard", "traits_given": True}
    assert "roughly 2 to 4 in all" in setup_note(drawn, ["Sheriff"] * 13, traits=["Bonded", "Bonded", "Loud"])
    assert "may also have a trait" in setup_note(None, roles)  # an older log, whose traits it wasn't told
