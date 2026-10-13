"""The handbook page (handbook.py): built from the code's own sources, so it shows every rule, role and trait."""

import json
import re

import handbook
from role_summaries import RULES
from roles import ROLES
from traits import TRAITS


def test_rules_parse_into_every_rule_and_role():
    text = RULES.read_text(encoding="utf-8")
    parts = handbook.rules_parts(text)
    blocks = [b for p in parts for b in p["blocks"]]
    labels = [b["label"] for b in blocks if b["kind"] == "rule"]
    assert sorted(labels) == sorted(re.findall(r"^(R\d+) \(", text, flags=re.M))
    assert sorted(b["name"] for b in blocks if b["kind"] == "role") == sorted(ROLES)
    assert {b["title"] for b in blocks if b["kind"] == "faction"} == {"Village (Good)", "Yakuza (Evil)", "Neutral"}
    # no line of the rules is lost: every non-blank line is in some block (headings in their own fields)
    kept = " ".join(" ".join([b.get("label", ""), b.get("title", ""), b.get("name", ""), *b.get("lines", [])])
                    for b in blocks)
    for line in text.splitlines():
        if line.strip() and not line.startswith("=== "):
            assert line.strip().split(" (")[0].strip(" -") in kept, line


def test_page_has_every_role_and_trait(tmp_path):
    d = handbook.data()
    assert [r["name"] for r in d["roles"]] == list(ROLES)
    assert [t["name"] for t in d["traits"]] == list(TRAITS)
    assert all(r["rules"] for r in d["roles"]), "a role without a rules paragraph"
    assert all(r["icon"] in d["icons"] for r in d["roles"])
    assert len(d["setups"]["samples"]) == handbook.SAMPLES
    page = handbook.build(tmp_path / "handbook.html").read_text(encoding="utf-8")
    payload = page.split("const D = ", 1)[1].split(";\nconst $ =", 1)[0]
    assert json.loads(payload)["roles"][0]["name"] == next(iter(ROLES))
    assert "/*DATA*/" not in page


def test_builder_draws_what_a_game_with_that_seed_deals():
    import mafia
    args = mafia.build_parser().parse_args(["--roles", "standard", "--seed", "7"])
    roles, setup = mafia.choose_roles(mafia.build_parser(), args, 7)
    d = json.loads(handbook.respond("/handbook/draw?setup=standard&seed=7") or b"")
    assert sorted(d["roles"]) == sorted(roles)
    assert d["traits"] == mafia.choose_traits(mafia.build_parser(), args, roles, setup, 7)
    assert "error" in json.loads(handbook.respond("/handbook/draw?setup=classic&yakuza=2") or b"")
    assert "error" in json.loads(handbook.respond("/handbook/draw?players=99") or b"")
    assert handbook.respond("/handbook.html") is None
