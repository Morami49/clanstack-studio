import json
import os
import subprocess
import sys

from should_automerge import REQUIRED, decide

GREEN = [{"name": c, "conclusion": "success"} for c in REQUIRED]


def test_low_risk_green_merges():
    assert decide("low", [], False, "Fixes a typo", GREEN)[0] == "merge"


def test_hold_label_skips():
    d, why = decide("low", [{"name": "hold"}], False, "", GREEN)
    assert d == "skip" and "hold" in why
    assert decide("low", ["Hold"], False, "", GREEN)[0] == "skip"


def test_hold_marker_in_body_skips():
    for body in ["Try first <!-- hold -->", "<!--hold-->", "x\n<!--  HOLD  -->\ny"]:
        d, why = decide("low", [], False, body, GREEN)
        assert d == "skip" and "hold" in why, body
    assert decide("low", [], False, "hold on, this is fine", GREEN)[0] == "merge"


def test_draft_skips():
    d, why = decide("low", [], True, "", GREEN)
    assert d == "skip" and "draft" in why


def test_high_risk_skips():
    d, why = decide("high", [], False, "", GREEN)
    assert d == "skip" and "high risk" in why


def test_missing_or_failed_check_skips():
    d, why = decide("low", [], False, "", GREEN[:-1])
    assert d == "skip" and REQUIRED[-1] in why
    failed = GREEN[:-1] + [{"name": REQUIRED[-1], "conclusion": "failure"}]
    assert decide("low", [], False, "", failed)[0] == "skip"
    # a push run failed but the pull_request run passed: one success is enough
    assert decide("low", [], False, "", failed + GREEN[-1:])[0] == "merge"
    assert decide("low", [], False, "", {c: "success" for c in REQUIRED})[0] == "merge"


def test_hold_wins_over_everything():
    d, why = decide("high", ["hold"], True, "<!-- hold -->", [])
    assert d == "skip" and "draft" in why


def test_cli():
    here = os.path.dirname(os.path.abspath(__file__))
    data = {"verdict": "low", "labels": [{"name": "hold"}], "draft": False, "body": None, "checks": GREEN}
    out = subprocess.run([sys.executable, os.path.join(here, "should_automerge.py")], input=json.dumps(data),
                         capture_output=True, text=True, check=True).stdout.strip()
    assert out.startswith("skip: ") and "hold" in out, out


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
