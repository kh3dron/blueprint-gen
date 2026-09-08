#!/usr/bin/env python3
"""Request native routes, compile their instructions in Python, then walk/mine in Factorio."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess

from build_observer import lua
from run_observer_smoke import HERE, run
from advisor_core.routes import compile_route, map_plan
from advisor_core.survey import write_map


def verify_requests(destination):
    output = destination / "user-data/script-output/blueprint-gen-observer"
    documents = [json.loads(p.read_text()) for p in output.glob("route-*.json")]
    by_sequence = {d["sequence"]: d for d in documents}
    if set(by_sequence) != {1, 2, 3, 4, 5}:
        raise RuntimeError(
            f"Expected five route receipts, found sequences {sorted(by_sequence)}"
        )
    for document in documents:
        compile_route(document)
    expected = {
        1: "ready",
        2: "no_path",
        3: "invalidated",
        4: "ready",
        5: "invalidated",
    }
    if {n: d["status"] for n, d in by_sequence.items()} != expected:
        raise RuntimeError(
            f"Unexpected route outcomes: {[(n, d['status'], d['reasons']) for n, d in sorted(by_sequence.items())]}"
        )
    if "character moved" not in " ".join(
        by_sequence[3]["reasons"]
    ) or "world configuration changed" not in " ".join(by_sequence[5]["reasons"]):
        raise RuntimeError(
            "Movement/world edits did not invalidate their pending paths"
        )
    route = by_sequence[1]
    plan = compile_route(route)
    if not any(p["y"] < -6 or p["y"] > 7 for p in plan["waypoints"]):
        raise RuntimeError("Route did not detour around the water barrier")
    if len(compile_route(by_sequence[4])["waypoints"]) != 1:
        raise RuntimeError("Already-in-reach target introduced unnecessary walking")
    preflight = json.loads((output.parent / "route-preflight-results.json").read_text())
    if (
        preflight.get("covered_target_rejected") is not True
        or preflight.get("covering_entity") != "transport-belt"
    ):
        raise RuntimeError("A selectable entity over the mineral was not rejected")
    survey_paths = list(output.glob("*-survey.json"))
    if len(survey_paths) != 1:
        raise RuntimeError("Expected one matching route survey")
    survey = json.loads(survey_paths[0].read_text())
    write_map(survey, destination / "approach.svg", map_plan(route, survey))
    (destination / "compiled-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    return {
        "receipts": by_sequence,
        "survey": survey,
        "plan": plan,
        "preflight": preflight,
    }


def verify_execution(destination):
    result = json.loads(
        (
            destination / "user-data/script-output/route-execution-results.json"
        ).read_text()
    )
    if (
        result["actual_inventory"] != 3
        or result["resource_depletion"] != 3
        or result["can_reach"] is not True
        or result["wall_preserved"] is not True
    ):
        raise RuntimeError(
            "Physical walking/mining did not collect exactly three observed ore"
        )
    if (
        result["waypoints_reached"] != result["waypoint_count"]
        or result["walking_distance"] <= 17
    ):
        raise RuntimeError("Character did not follow the detour waypoints")
    return result


def run_test(binary, destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    requested = run(
        binary,
        destination / "request",
        scenario_name="route-smoke",
        scenario_directory=HERE / "integration/route-scenario",
        ticks=1800,
        verify_result=verify_requests,
    )
    staging = destination / "execution-scenario"
    shutil.copytree(HERE / "integration/route-scenario", staging)
    plan = requested["plan"]
    instructions = {k: plan[k] for k in ("waypoints", "target", "receipt_sha256")}
    (staging / "route_plan.lua").write_text(
        "-- Python-compiled instructions for this disposable test only.\nreturn "
        + lua(instructions)
        + "\n"
    )
    executed = run(
        binary,
        destination / "execute",
        scenario_name="route-smoke",
        scenario_directory=staging,
        ticks=3000,
        verify_result=verify_execution,
    )
    if executed["receipt_sha256"] != plan["receipt_sha256"]:
        raise RuntimeError("Execution used a different route receipt")
    summary = {
        "factorio_version": requested["receipts"][1]["factorio_version"],
        "active_mods": requested["receipts"][1]["active_mods"],
        "route_outcomes": {
            str(n): d["status"] for n, d in sorted(requested["receipts"].items())
        },
        "planned_distance_tiles": plan["planned_distance_tiles"],
        "walking_distance_tiles": executed["walking_distance"],
        "actual_ore_collected": executed["actual_inventory"],
        "resource_depletion": executed["resource_depletion"],
        "can_reach": True,
        "wall_preserved": executed["wall_preserved"],
        "covered_target_rejected": requested["preflight"]["covered_target_rejected"],
        "receipt_sha256": plan["receipt_sha256"],
        "execution_ticks": executed["finished_tick"] - executed["started_tick"],
        "method": executed["method"],
    }
    (destination / "verification.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--factorio", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        run_test(args.factorio, args.out)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        parser.exit(2, f"route-smoke: {error}\n")


if __name__ == "__main__":
    main()
