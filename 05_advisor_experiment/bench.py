#!/usr/bin/env python3
"""Reproducible snapshot scenarios, not a Factorio simulator or a playthrough."""
import math
from pathlib import Path

from advisor_core.model import Snapshot
from advisor_core.planner import next_step
from advisor_core.production import analyze, completion
from advisor_core.rules import Rules


# Case, expected common goal fraction, observed complete, next action.
CASES = [
    ("start", 0, False, "trigger"),
    ("starved", 0, False, "supply"),
    ("missing-coal", 0, False, "supply"),
    ("brownout", 40 / 137.5, False, "power"),
    ("ghosts", 0, False, "build"),
    ("disconnected", 0, False, "repair"),
    ("ready", 1, False, "verify"),
    ("observed", 1, True, "done"),
    ("oil-coproducts", 1, False, "verify"),
]


def main():
    rules = Rules.load()
    failed = 0
    print(f"{'SCENARIO':<20}{'GOAL BOUND':>12}{'OBSERVED':>12}  {'NEXT':<12}RESULT")
    for name, fraction, done, kind in CASES:
        snapshot = Snapshot.load(Path(__file__).resolve().parent / "examples" / f"{name}.json", rules)
        analysis = analyze(snapshot, rules)
        verified = completion(snapshot, rules, analysis)["complete"]
        step = next_step(snapshot, rules)
        ok = math.isclose(analysis["goal_fraction"], fraction, abs_tol=1e-7) and verified == done and step["kind"] == kind
        failed += not ok
        print(f"{name:<20}{analysis['goal_fraction']:>11.1%}{str(verified):>12}  {step['kind']:<12}{'PASS' if ok else 'FAIL'}")
    print(f"{len(CASES) - failed}/{len(CASES)} snapshot scenarios passed. No game simulation was run.")
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
