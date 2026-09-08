#!/usr/bin/env python3
"""Validate resource surveys and direct connections in an isolated Factorio profile."""

import argparse
import json
import subprocess

from run_observer_smoke import HERE, run
from advisor_core.game_import import import_capture
from advisor_core.survey import gather, inspect, write_map


def verify(destination):
    output = destination / "user-data/script-output"
    paths = sorted((output / "blueprint-gen-observer").glob("*-survey.json"))
    if len(paths) != 2:
        raise RuntimeError(f"Expected two survey captures, found {len(paths)}")
    first, removed = [json.loads(p.read_text()) for p in paths]
    facts = json.loads((output / "survey-smoke-results.json").read_text())

    def check(value, message):
        if not value:
            raise RuntimeError(message)

    report = inspect(first)
    plan = gather(first, {"iron-ore": 50, "coal": 4})
    check(plan["all_quantities_located"], "Finite mineral request was not located")
    totals = {}
    for step in plan["steps"]:
        totals[step["item"]] = totals.get(step["item"], 0) + step["quantity"]
        check(
            step["position"] != facts["blocked_resource_position"],
            "Blocked ore selected for hand-mining",
        )
        check(
            step["quantity"] <= step["observed_resource_units"],
            "Resource tile oversubscribed",
        )
    check(totals == {"iron-ore": 50, "coal": 4}, "Finite gathering quantities differ")
    check(
        len([s for s in plan["steps"] if s["item"] == "iron-ore"]) == 2,
        "Small adjacent ore deposits not allocated independently",
    )
    check(
        any(
            p["resource"] == "iron-ore"
            and p["units_observed"] == 55
            and p["tiles"] == 2
            for p in report["patches"]
        ),
        "Adjacent ore tiles did not form a 55-unit patch",
    )
    check(
        report["water_tile_count"] == 19,
        "Water survey differs from the 19-tile fixture",
    )
    by_id = {e["id"]: e for e in first["survey"]["infrastructure"]}
    inserter = by_id[facts["inserter_id"]]
    check(
        inserter.get("pickup_target", {}).get("id") == facts["chest_id"],
        "Inserter source did not match actual chest",
    )
    check(
        inserter.get("drop_target", {}).get("id") == facts["assembler_id"],
        "Inserter destination did not match assembler",
    )
    a, b, isolated = (by_id[facts[k]] for k in ("pole1_id", "pole2_id", "isolated_id"))
    check(
        a["electric_network_id"]
        == b["electric_network_id"]
        != isolated["electric_network_id"],
        "Pole network membership differs",
    )
    check(
        any(n["id"] == b["id"] for n in a["copper_neighbours"]),
        "Actual copper wire was not exported",
    )
    changed = inspect(removed)
    check(
        any(
            d["entity_id"] == inserter["id"] and d["status"] == "no_pickup_entity"
            for d in changed["diagnostics"]
        ),
        "Removed chest was not diagnosed",
    )
    check(
        any(
            d["entity_id"] == facts["drill_id"] and d["status"] == "no_fuel"
            for d in report["diagnostics"]
        ),
        "Unfueled drill was not diagnosed",
    )
    snapshot, _ = import_capture(first)
    check(
        snapshot.document["power"]["available_kw"] == 0
        and not snapshot.document["supplies_per_s"],
        "Survey incorrectly inferred supply or generation",
    )
    write_map(first, destination / "survey.svg", plan)
    summary = {
        "factorio_version": first["factorio_version"],
        "active_mods": first["active_mods"],
        "capture_ticks": [first["tick"], removed["tick"]],
        "gathered_quantities_planned": totals,
        "mining_targets": len(plan["steps"]),
        "blocked_ore_excluded": True,
        "water_tiles": report["water_tile_count"],
        "copper_membership_checked": True,
        "removed_source_diagnosed": True,
        "unfueled_drill_diagnosed": True,
        "supply_and_generation_still_unknown": True,
    }
    (destination / "verification.json").write_text(json.dumps(summary, indent=2) + "\n")
    (destination / "gather-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--factorio", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        run(
            args.factorio,
            args.out,
            scenario_name="survey-smoke",
            scenario_directory=HERE / "integration/survey-scenario",
            ticks=125,
            verify_result=verify,
        )
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        parser.exit(2, f"survey-smoke: {error}\n")


if __name__ == "__main__":
    main()
