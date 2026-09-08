#!/usr/bin/env python3
"""Compile observed opening checkpoints and replay them in disposable Factorio profiles."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from opening import ROOT, procurement, executable, observed_snapshot, verify_result, check_replay

sys.path.insert(0, str(ROOT / "05_advisor_experiment/tools"))
from build_observer import lua
from run_observer_smoke import run
from proving_ground import SOURCE, build
from advisor_core.game_import import digest
from advisor_core.routes import compile_route
from advisor_core.planner import next_step
from advisor_core.production import completion
from factory import blueprint

HERE = Path(__file__).resolve().parent


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def read_stage(destination):
    output = destination / "user-data/script-output"
    states = {p.stem: json.loads(p.read_text()) for p in output.glob("*.json")}
    observed = output / "blueprint-gen-observer"
    captures = sorted((json.loads(p.read_text()) for p in observed.glob("*-survey.json")), key=lambda d: d["tick"])
    receipts = sorted((json.loads(p.read_text()) for p in observed.glob("route-*.json")), key=lambda d: d["sequence"])
    if not captures or "initial-state" not in states:
        raise RuntimeError("missing initial observations")
    return {"states": states, "captures": captures, "receipts": receipts}


def run_test(binary, destination, config):
    started = time.perf_counter()
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    performance = []

    def stage(label, instructions, ticks):
        directory = destination / label
        scenario = build(config, directory / "scenario")
        for source in (HERE / "integration").glob("*.lua"):
            shutil.copy2(source, scenario / source.name)
        (scenario / "plan.lua").write_text("-- Python instructions for this isolated replay only.\nreturn " + lua(instructions) + "\n")
        result = run(binary, directory / "engine", scenario_name="opening-smoke", scenario_directory=scenario,
                     ticks=ticks, verify_result=read_stage)
        performance.append({"stage": label, **json.loads((directory / "engine/performance.json").read_text())})
        return result

    first = stage("00-observe", {}, 125)
    initial = first["states"]["initial-state"]
    instructions = procurement(first["captures"][0], initial)
    save(destination / "procurement.json", instructions)
    receipts = []
    for index, target in enumerate(instructions["targets"]):
        probe = stage(f"0{index + 1}-route", instructions, 8000)
        check_replay(probe, first, receipts)
        if len(probe["receipts"]) != index + 1:
            raise ValueError("missing sequential native route receipt")
        receipt = probe["receipts"][-1]
        checkpoint = probe["states"][f"checkpoint-{index + 1}"]
        if (receipt["target"]["position"] != target["position"]
                or receipt["target"]["quantity"] != target["quantity"]
                or receipt["target"]["item"] != target["item"]
                or receipt["start"] != checkpoint["position"]
                or receipt["requested_tick"] != checkpoint["tick"]):
            raise ValueError("route differs from the requested checkpoint")
        compiled = compile_route(receipt, current_tick=receipt["completed_tick"] + 1)
        if compiled["kind"] != "walk_then_mine":
            raise ValueError(f"route requires observation: {compiled.get('reasons')}")
        compiled["requested_tick"] = receipt["requested_tick"]
        instructions["routes"].append(compiled)
        receipts.append(receipt)
    gathered = stage("03-gather", instructions, 8000)
    check_replay(gathered, first, receipts)
    state = gathered["states"].get("placement-state")
    if state is None:
        raise ValueError("gathering did not reach the placement checkpoint")
    # Validate that this is a real matched survey/inventory, not a predicted bill result.
    observed_snapshot(gathered["captures"][-1], state)
    instructions = executable(instructions, state)
    save(destination / "instructions.json", instructions)
    (destination / "furnace.blueprint.txt").write_text(blueprint(instructions["design"]) + "\n")
    lines = ["Finite opening: produce 50 new iron plates", ""]
    for route in instructions["routes"]:
        lines.extend(route["instructions"])
    p = instructions["placement"]["position"]
    lines.extend([f"Place the starter stone furnace centered at ({p['x']}, {p['y']}).",
                  "Transfer 50 iron ore into its input and 4 coal into its fuel slot.",
                  "Wait for 50 furnace crafts (160 simulated seconds); collect the 50 plates.",
                  "Observe steam-power researched. The 10 red science/min goal is still outstanding."])
    (destination / "instructions.txt").write_text("\n".join(lines) + "\n")
    final = stage("04-smelt", instructions, state["tick"] + 9800)
    check_replay(final, first, receipts)
    if final["states"].get("placement-state") != state:
        raise ValueError("actual placement state changed between stages")
    result = final["states"].get("execution")
    if result is None:
        raise ValueError("engine did not finish the opening within its tick budget")
    report = verify_result(result, instructions, initial)
    snapshot, rules = observed_snapshot(final["captures"][-1], result["final"])
    if (len(snapshot.machines) != 1 or snapshot.machines[0]["prototype"] != "stone-furnace"
            or snapshot.machines[0]["position"] != instructions["placement"]["position"]):
        raise ValueError("independent observer does not match the built declaration")
    if completion(snapshot, rules)["complete"]:
        raise ValueError("finite plate batch incorrectly completed the science goal")
    snapshot.save(destination / "final-snapshot.json")
    save(destination / "next-action.json", next_step(snapshot, rules))
    report["instructions_sha256"] = digest(instructions)
    save(destination / "verification.json", report)
    save(destination / "performance.json", {"stages": performance,
         "total_experiment_seconds": time.perf_counter() - started,
         "note": "Stages replay earlier actions; sum of simulated seconds is not unique gameplay progress."})
    print(json.dumps(report, indent=2), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--factorio", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=SOURCE / "config.json")
    args = parser.parse_args()
    try:
        run_test(args.factorio, args.out, json.loads(args.config.read_text()))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        parser.exit(2, f"opening-smoke: {error}\n")
