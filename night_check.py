"""Night checks: a judge model audits each night's moderator resolution against the rules.

The check only reports; it never changes the game. It runs in a background thread while the game
continues, on a copy of everything it needs, so it adds little time. Each check is logged as one
"night_check" record (see CHECK_SCHEMA), which the feedback report and the HTML log show, and which
is meant for analysis across games (e.g. the moderator's error rate per model or per rule).
"""

import json
from concurrent.futures import Future, ThreadPoolExecutor

from gamelog import GameLog
from llm import LLMClient, Model, answer_json
from players import STR, obj

ISSUE_KINDS = ["wrong death", "missed death", "wrong result", "missing result", "leaked information",
               "token or status error", "other"]
CHECK_SCHEMA = obj(
    verdict={"type": "string", "enum": ["correct", "errors", "unsure"]},
    issues={"type": "array", "items": obj(
        rule=STR,  # e.g. "R9" or a role name
        severity={"type": "string", "enum": ["high", "medium", "low"]},  # high: changed who lives or what someone learned
        kind={"type": "string", "enum": ISSUE_KINDS},
        description=STR,
    )},
)


class NightChecker:
    def __init__(self, client: LLMClient, judge: Model, moderator: Model, rules: str, log: GameLog,
                 effort: str | None = None):
        self.client, self.judge, self.moderator, self.rules, self.log = client, judge, moderator, rules, log
        self.effort = effort  # the judge's reasoning effort; None: the client's default
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.pending: list[Future] = []

    def submit(self, night: int, instructions: str, before: dict, transcript: list[dict], after: dict) -> None:
        """Queue a check. Everything passed must be a snapshot: the game keeps changing meanwhile."""
        user = (f"{instructions}\n\n---\n\nHidden state before the moderator acted:\n{json.dumps(before)}\n\n"
                f"What the moderator did, in order (tool, arguments, result):\n{json.dumps(transcript, indent=1)}"
                f"\n\nHidden state after:\n{json.dumps(after)}\n\n---\n\n"
                "Check this resolution of the night against the rules. Work out what should have happened: "
                "who is role-blocked, who visits whom, attacks vs defenses, who dies, and what each player "
                "should be told. Compare that with what the moderator did. List every mistake: a wrong or "
                "missed death, a wrong or missing private result, information leaked beyond what the rules "
                "allow, wrong tokens or statuses. Cite the rule label (e.g. R9) or role. Code, not the "
                "moderator, carries out Jester/Executioner revenge and dawn effects, so don't expect those. "
                "Verdict 'correct' if there are no mistakes, 'unsure' if the rules are ambiguous for what "
                "happened (describe it as an issue of kind 'other').")
        messages = [{"role": "system", "content": f"{self.rules}\n\n---\n\nYou audit an LLM moderator's "
                     "resolution of one night of this game. Be precise and only report real mistakes."},
                    {"role": "user", "content": user}]
        alive = [p for p in before["players"] if p["alive"]]
        in_play = {"alive": len(alive), "roles_in_play": sorted(p["role"] for p in alive)}  # for analysis
        self.pending.append(self.pool.submit(self._check, night, messages, in_play))

    def _check(self, night: int, messages: list[dict], in_play: dict) -> None:
        try:
            reply = self.client.chat(self.judge, messages, schema=CHECK_SCHEMA, schema_name="night_check",
                                     effort=self.effort)
            out = answer_json(reply, CHECK_SCHEMA)
            self.log.write("night_check", night=night, judge=self.judge.value, moderator=self.moderator.value,
                           verdict=out["verdict"], issues=out["issues"], cost=reply.cost, usage=reply.usage,
                           **in_play)
            for issue in out["issues"]:
                if issue["severity"] == "high":  # changed who lives or what someone learned
                    self.log.error("night_check_issue", f"night {night}: {issue['description']}",
                                   night=night, issue=issue)
        except Exception as e:  # a failed check must never stop the game
            self.log.write("night_check", night=night, judge=self.judge.value, moderator=self.moderator.value,
                           verdict="failed", issues=[], error=f"{type(e).__name__}: {e}", **in_play)
            self.log.error("night_check_error", f"the night {night} check failed: {type(e).__name__}: {e}",
                           night=night)

    def finish(self) -> None:
        """Wait for the remaining checks (call before the log is closed)."""
        for f in self.pending:
            f.result()
        self.pool.shutdown()
