#!/usr/bin/env python3
"""Check flat chunk generation, rectangular finite deposits, and starter inventory in Factorio."""

import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import subprocess

from run_observer_smoke import HERE, run
from proving_ground import SOURCE, build, validate
from advisor_core.game_import import digest
from advisor_core.survey import write_map


def verify(destination):
    output = destination / "user-data/script-output"
    report = json.loads((output / "ground-results.json").read_text())
    config = validate(report["config"])
    totals, counts = Counter(), Counter()
    for patch in config["patches"]:
        counts[patch["item"]] += patch["width"] * patch["height"]
        totals[patch["item"]] += patch["width"] * patch["height"] * patch["amount"]
    actual_inventory = {s["name"]: s["count"] for s in report["inventory"]}
    if (
        report["resource_totals_before_depletion"] != dict(totals)
        or report["resource_tile_counts"] != dict(counts)
        or report["tree_count"] != len(config["trees"])
        or report["water_count"]
        != sum(r["width"] * r["height"] for r in config["water"])
        or actual_inventory != config["inventory"]
        or report["researched"] not in ([], {})
        or report["width"] != 2000000
        or report["height"] != 2000000
        or report["far_tile"] != "grass-1"
        or report["resource_not_refilled"] is not True
    ):
        raise RuntimeError("Proving-ground engine facts differ from the configuration")
    survey = json.loads(
        next((output / "blueprint-gen-observer").glob("*-survey.json")).read_text()
    )
    area = survey["scope"]["area"]
    expected_cells = {}
    for patch in config["patches"]:
        for x in range(patch["x"], patch["x"] + patch["width"]):
            for y in range(patch["y"], patch["y"] + patch["height"]):
                if (
                    area[0][0] <= x + 0.5 < area[1][0]
                    and area[0][1] <= y + 0.5 < area[1][1]
                ):
                    expected_cells[(patch["item"], x + 0.5, y + 0.5)] = patch["amount"]
    first = config["patches"][0]
    depleted = (first["item"], first["x"] + 0.5, first["y"] + 0.5)
    if depleted in expected_cells:
        expected_cells[depleted] -= 3
    actual_cells = {
        (r["prototype"], r["position"]["x"], r["position"]["y"]): r["amount"]
        for r in survey["survey"]["resources"]
    }
    if actual_cells != expected_cells:
        raise RuntimeError(
            "Observed resource coordinates/amounts differ from the configured rectangles"
        )
    write_map(survey, destination / "ground.svg")
    report["config_sha256"] = digest(config)
    report["surveyed_positions_checked"] = len(actual_cells)
    (destination / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "factorio_version",
                    "config_sha256",
                    "resource_tile_counts",
                    "water_count",
                    "tree_count",
                    "far_tile",
                    "resource_not_refilled",
                )
            },
            indent=2,
        )
    )
    return report


def run_test(binary, destination, config):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    scenario = build(config, destination / "scenario")
    shutil.copy2(
        HERE / "integration/proving-ground-smoke/control.lua", scenario / "control.lua"
    )
    return run(
        binary,
        destination / "engine",
        scenario_name="ground-smoke",
        scenario_directory=scenario,
        ticks=125,
        verify_result=verify,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--factorio", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=SOURCE / "config.json")
    args = parser.parse_args()
    try:
        run_test(args.factorio, args.out, json.loads(args.config.read_text()))
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        parser.exit(2, f"ground-smoke: {error}\n")


if __name__ == "__main__":
    main()
