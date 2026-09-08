#!/usr/bin/env python3
"""Place and extend declared modules in the isolated flat proving ground."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from demo import build as build_demo
from factory import plan

HERE = Path(__file__).resolve().parent
ADVISOR = HERE.parent / "05_advisor_experiment"
sys.path.insert(0, str(ADVISOR))
sys.path.insert(0, str(ADVISOR / "tools"))
from proving_ground import SOURCE, build as build_ground
from build_observer import lua
from run_observer_smoke import run


def run_test(binary, destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    first, expanded, initial, incremental = build_demo(destination / "design")
    scenario = build_ground(
        json.loads((SOURCE / "config.json").read_text()), destination / "scenario"
    )
    shutil.copy2(HERE / "integration/control.lua", scenario / "control.lua")
    (scenario / "designs.lua").write_text(
        "return "
        + lua(
            {
                "first": first,
                "expanded": expanded,
                "initial": initial,
                "incremental": incremental,
            }
        )
        + "\n"
    )

    def verify(engine):
        report = json.loads(
            (engine / "user-data/script-output/declarative-results.json").read_text()
        )
        checked = plan(expanded, first, observation=report["before"])
        drift = plan(expanded, first, observation=report["drift"])
        if (
            report["initial_added"] != len(initial["add"])
            or report["incremental_added"] != len(incremental["add"])
            or report["repeat_added"] != 0
            or checked["kind"] != "additive"
            or checked["add"] != incremental["add"]
            or drift["kind"] != "blocked"
            or len(report["gear_crafts"]) != 2
            or min(report["gear_crafts"].values()) < 10
            or any(
                report[k] is not True
                for k in (
                    "retained_ids_preserved",
                    "obstacle_rejected",
                    "locked_rejected",
                    "drift_rejected",
                )
            )
        ):
            raise RuntimeError("declarative engine assertions failed")
        for key, observed in report["before"]["entities"].items():
            if report["after"]["entities"][key] != observed:
                raise RuntimeError(
                    "an existing managed entity changed during expansion"
                )
        (destination / "observation-bound-plan.json").write_text(
            json.dumps(checked, indent=2) + "\n"
        )
        (destination / "verification.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print(
            json.dumps(
                {
                    k: v
                    for k, v in report.items()
                    if k not in ("before", "after", "drift")
                },
                indent=2,
            )
        )
        return report

    return run(
        binary,
        destination / "engine",
        scenario_name="declarative-smoke",
        scenario_directory=scenario,
        ticks=1805,
        verify_result=verify,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--factorio", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        run_test(args.factorio, args.out)
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        parser.exit(2, f"declarative-smoke: {error}\n")
