"""F-automerge-overrode-hold: decide whether automerge may merge a pull request, and say why.

A PR merges itself only when nothing holds it and it is low risk with every required check green. It is held when
it is a draft, carries the label "hold", or its body contains <!-- hold --> (Nowed: "N, try it first").

    echo '{"verdict": "low", "labels": ["docs"], "draft": false, "body": "...",
           "checks": [{"name": "engine", "conclusion": "success"}, ...]}' | python scripts/should_automerge.py

prints one line: "merge: <reason>" or "skip: <reason>". "checks" may also be a {name: conclusion} mapping.
"""
from __future__ import annotations

import json
import re
import sys

REQUIRED = ["engine", "hub", "studio", "actionmap", "scripts"]
HOLD_LABEL = "hold"
HOLD_MARKER = re.compile(r"<!--\s*hold\s*-->", re.IGNORECASE)


def passed_checks(checks) -> set[str]:
    """Names of checks with at least one successful run (a SHA can have both a push and a pull_request run)."""
    if isinstance(checks, dict):
        return {n for n, c in checks.items() if c == "success"}
    return {c.get("name") for c in checks or [] if c.get("conclusion") == "success"}


def decide(verdict: str, labels, draft: bool, body: str | None, checks) -> tuple[str, str]:
    names = {(x.get("name") if isinstance(x, dict) else x) or "" for x in labels or []}
    if draft:
        return "skip", "draft pull request"
    if HOLD_LABEL in {n.lower() for n in names}:
        return "skip", f'label "{HOLD_LABEL}": Nowed wants to try it first'
    if HOLD_MARKER.search(body or ""):
        return "skip", "body contains <!-- hold -->: Nowed wants to try it first"
    if verdict != "low":
        return "skip", f"{verdict or 'unknown'} risk: waits for Nowed"
    missing = [c for c in REQUIRED if c not in passed_checks(checks)]
    if missing:
        return "skip", "required checks not passed: " + ", ".join(missing)
    return "merge", "low risk, not held, required checks passed"


def main() -> int:
    d = json.load(sys.stdin)
    decision, reason = decide(d.get("verdict", ""), d.get("labels", []), bool(d.get("draft")), d.get("body"),
                              d.get("checks", []))
    print(f"{decision}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
