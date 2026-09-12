#!/usr/bin/env python3
"""Continue the paid powered-lab opening through a measured self-fueling coal supply."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from coal_profile import CoalSession, CoalDriver
from coal_plan import CoalLoop
from run_power import run, save, SOURCE, bill

HERE = Path(__file__).resolve().parent


def continue_coal(driver):
    root = driver.root
    save(root / "power-actions.json", driver.actions)
    driver.milestone = "self-fueling-coal"
    snapshot, rules, capture = driver.observe()
    design = CoalLoop.from_survey(capture).document()
    save(root / "coal-design.json", design)
    materials = bill(snapshot, rules, design["bill"])
    save(root / "coal-materials.json", materials)
    print("Harvest wood and procure the coal loop from the observed runtime bill.", flush=True)
    driver.execute_bill({"construction": materials})
    driver.mine("coal", sum(design["seed"].values()))
    driver.action("preflight_power", {"specs": design["placements"]}, "Check the coal loop against the actual terrain")
    driver.action("walk_to", {"position": design["staging"]}, "Walk to the coal module construction position")
    for spec in design["placements"]:
        driver.action("place_coal", {"spec": spec}, f"Place {spec['name']} at {spec['position']}")
    before = driver.session.client.call({"op": "status"})
    for spec in design["placements"]:
        result = driver.action("place_coal", {"spec": spec}, "Reconcile " + spec["address"] + "; retain the existing entity")
        if result["outcome"]["value"]["added"]:
            raise ValueError("reconciliation duplicated a coal entity")
    after = driver.session.client.call({"op": "status"})
    for key in ("inventory", "player_build_events", "cursor_placements"):
        if before[key] != after[key]:
            raise ValueError("reconciliation changed items or construction")
    changed = deepcopy(design["placements"][0])
    changed["direction"] = 4
    try:
        driver.action("place_coal", {"spec": changed}, "Refuse a direction change at an existing module address")
    except RuntimeError as error:
        if "declarative entity drift" not in str(error):
            raise
    else:
        raise ValueError("direction drift was not refused")
    refused = driver.session.client.call({"op": "status"})
    keys = ("inventory", "player_build_events", "cursor_placements", "coal")
    # Status/fuel do not change here: all burners are still idle and unseeded.
    save(root / "coal-reconciliation.json", {"before": before, "after": after,
        "drift_before": {k: after[k] for k in keys if k != "coal"},
        "drift_after": {k: refused[k] for k in keys if k != "coal"},
        "refusal_id": driver.actions[-1]["request"]["id"]})
    driver.action("seed_coal", {"mining_area": design["mining_area"]}, "Seed each burner with one paid coal")
    driver.milestone = "coal-startup"
    warmup = driver.action("wait_coal", {"ticks": design["measurement"]["warmup_ticks"], "phase": "warmup"},
                           "Stand idle for one startup minute while the drill fills its fuel reserve")
    save(root / "coal-warmup.json", warmup["outcome"]["value"])
    windows = []
    driver.milestone = "measure-coal-delivery"
    for i in range(design["measurement"]["windows"]):
        print(f"Observe idle coal delivery: minute {i+1}/5.", flush=True)
        result = driver.action("wait_coal", {"ticks": design["measurement"]["window_ticks"]},
                               f"Stand idle for minute {i+1}/5; measure coal delivered to the chest")
        windows.append(result["outcome"]["value"])
        save(root / "coal-windows.json", windows)
    driver.observe()
    save(root / "coal-final-observation.json", driver.observations[-1])
    from verify_coal import verify_directory
    verified = verify_directory(root)
    save(root / "coal-verification.json", verified)
    print(json.dumps({"coal_verified": verified["self_fueling_observed"],
                      "coal_per_min": verified["delivered_per_minute"]}), flush=True)
    driver.session.client.call({"op": "save", "name": "coal-supply"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--factorio", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=SOURCE / "config.json")
    parser.add_argument("--speed", type=int, choices=(10, 40), default=10)
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    try:
        run(args.factorio, args.out, json.loads(args.config.read_text()), args.speed,
            scenario_overlay=HERE / "integration", session_type=CoalSession,
            driver_type=CoalDriver, continue_with=continue_coal, record=args.record)
        if args.record:
            from render_coal import build
            print(build(args.out, args.out / "recording"))
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f"coal-supply: {error}\n")
