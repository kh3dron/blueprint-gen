"""Compile production declarations or execute them through the connected player."""
import argparse
import json
from pathlib import Path
import time

from .compiler import compile_goal
from .legacy import (CoalDriver, CoalSession, GraphicalClient, SOURCE, configure_recording,
                     contract, execute_feed, feed_contract, iron_overlay, restore_driver,
                     validate_bundle, validate_iron_checkpoint)
from .methods import IronPlateMethod
from .player import PlayerPort
from .program import Automate, Executor, save
from .deployment import record
from . import checkpoints


def compile_observation(goal, observation, deployment=None):
    snapshot, rules = CoalDriver.snapshot(observation["capture"], observation["state"])
    return compile_goal(goal, observation, snapshot, rules, [IronPlateMethod()],deployment=deployment)


def summary(program):
    return {"goal": program["goal"], "blockers": program["blockers"],
            "lines": program.get("method", {}).get("count"),
            "entities": len(program.get("design", {}).get("placements", [])),
            "retained_entities":len(program.get("change",{}).get("retained",{})),
            "added_entities":len(program.get("change",{}).get("add",[])),
            "gather": program.get("materials", {}).get("gather", {}),
            "program_nodes": len(program["nodes"])}


def apply(goal, checkpoint, out, binary, from_feed=False):
    config = json.loads((SOURCE / "config.json").read_text())
    stage=json.loads((checkpoint/"checkpoint.json").read_text())["stage"]
    if stage=="constructor-idle":
        if from_feed:raise ValueError("--from-feed cannot apply to a constructor deployment")
        checkpoints.validate(checkpoint,config=config)
    elif from_feed:
        validate_bundle(checkpoint, config=config, contract=feed_contract())
    else:
        validate_iron_checkpoint(checkpoint, config=config, contract=contract())
    session = graphics = None
    started = time.perf_counter()
    try:
        with iron_overlay() as overlay:
            session = CoalSession(binary, out, config, scenario_overlay=overlay, checkpoint=checkpoint)
        session.start()
        configure_recording(session, False)
        graphics = GraphicalClient(session)
        graphics.record = False
        graphics.start()
        driver = restore_driver(CoalDriver(session, graphics), checkpoint)
        session.client.call({"op": "speed", "speed": 10})
        if from_feed:
            # Explicit test-world prerequisite; it is outside the constructor's proof scope.
            execute_feed(driver, wait_speed=40)
        driver.observe()
        deployment=json.loads((checkpoint/"evidence/deployment.json").read_text()) if stage=="constructor-idle" else None
        program = compile_observation(goal, driver.observations[-1], deployment)
        save(out / "program.json", program)
        print(json.dumps(summary(program)), flush=True)
        # The interpreter receives only serialized data, with no live compiler closures.
        program = json.loads((out / "program.json").read_text())
        port = PlayerPort(driver, program)
        execution = Executor(program, port, out).run()
        save(out/"deployment.json",record(program,driver.observations[-1],port.verification))
        saved=checkpoints.write(driver,out/"checkpoints/factory-idle",config=config)
        report = {**summary(program), "status": execution["status"],
                  "measured_per_minute": port.verification["plates_per_minute"],
                  "coal_buffer_gain": port.verification["coal_buffer_gain"],
                  "native_builds": port.verification["native_cursor_builds_added"],
                  "checkpoint":str(saved),
                  "wall_seconds": round(time.perf_counter()-started, 3),
                  "png_count": len(list(out.rglob("*.png"))),
                  "goal_complete": True, "science_goal_complete": False}
        save(out / "run-summary.json", report)
        print(json.dumps(report), flush=True)
    except Exception as error:
        if out.exists():
            save(out / "run-summary.json", {"status": "failed", "error": str(error)})
        raise
    finally:
        if graphics:
            print("Closing the test game; disconnect confirmation can take about five seconds.", flush=True)
            graphics.close()
        if session:
            session.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--observation", required=True, type=Path)
    plan.add_argument("--deployment",type=Path)
    run = sub.add_parser("apply")
    run.add_argument("--checkpoint", required=True, type=Path)
    run.add_argument("--factorio", required=True)
    run.add_argument("--from-feed", action="store_true")
    for child in (plan, run):
        child.add_argument("--item", required=True)
        child.add_argument("--per-minute", required=True, type=float)
        child.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    goal = Automate(args.item, args.per_minute)
    if args.command == "plan":
        program = compile_observation(goal, json.loads(args.observation.read_text()),
            json.loads(args.deployment.read_text()) if args.deployment else None)
        save(args.out, program)
        print(json.dumps(summary(program)))
    else:
        apply(goal, args.checkpoint, args.out, args.factorio, args.from_feed)


if __name__ == "__main__":
    main()
