"""Keeps each role's one-line `summary` (ROLES) in step with its paragraph in rules_1.txt.

roles/summary_fingerprints.json holds a fingerprint of each role's rules paragraph as it was when its summary was
last checked. tests/test_logs.py fails when a paragraph no longer matches; update that role's summary if needed, then
`uv run role_summaries.py ROLE ...` records the new fingerprint (with no roles, it lists the stale ones).
"""

import hashlib
import json
import sys
from pathlib import Path

RULES = Path(__file__).parent / "rules_1.txt"
FINGERPRINTS = Path(__file__).parent / "roles" / "summary_fingerprints.json"


def role_paragraphs() -> dict[str, str]:
    """Each role's paragraph in the rules' roles part: its name on a line of its own, then indented lines."""
    lines = RULES.read_text(encoding="utf-8").split("PART 6: ROLES", 1)[1].split("\n=== ", 1)[0].splitlines()
    paragraphs: dict[str, str] = {}
    for i, line in enumerate(lines):
        body = []
        for following in lines[i + 1:]:
            if not following.startswith("  "):
                break
            body.append(following)
        if line.strip() and not line.startswith(" ") and body:
            paragraphs[line.strip()] = "\n".join(body)
    return paragraphs


def fingerprint(text: str) -> str:
    """Ignores line wrapping and spacing, so only changes to the wording count."""
    return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()[:12]


def stale_roles() -> list[str]:
    """Roles whose rules paragraph changed (or is missing) since their summary was last checked."""
    from roles import ROLES
    saved = json.loads(FINGERPRINTS.read_text(encoding="utf-8")) if FINGERPRINTS.exists() else {}
    paragraphs = role_paragraphs()
    return [r for r in ROLES if r not in paragraphs or saved.get(r) != fingerprint(paragraphs[r])]


def record(roles: list[str]) -> None:
    from roles import ROLES
    saved = json.loads(FINGERPRINTS.read_text(encoding="utf-8")) if FINGERPRINTS.exists() else {}
    paragraphs = role_paragraphs()
    for role in roles:
        if role not in ROLES or role not in paragraphs:
            sys.exit(f"{role!r} isn't both a ROLES entry and a role paragraph in rules_1.txt")
        saved[role] = fingerprint(paragraphs[role])
    saved = {r: saved[r] for r in ROLES if r in saved}  # ROLES order; drops removed roles
    FINGERPRINTS.write_text(json.dumps(saved, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if sys.argv[1:]:
        record(sys.argv[1:])
        print("Recorded:", ", ".join(sys.argv[1:]))
    else:
        print("Summaries to check:", ", ".join(stale_roles()) or "none")
