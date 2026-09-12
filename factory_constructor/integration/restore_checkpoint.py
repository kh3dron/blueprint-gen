#!/usr/bin/env python3
"""Recheck a sealed science proof, then restore its exact paused world once.

This harness never compiles, builds, walks, crafts, or advances simulation.
It starts an isolated server and graphical peer only when main() is invoked.
"""
import argparse
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--factorio", required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo.resolve()))
    from factory_constructor import checkpoints
    from factory_constructor.catalog import ScienceDriver, ScienceSession
    from factory_constructor.deployment import refresh
    from factory_constructor.integration import science_overlay
    from factory_constructor.legacy import GraphicalClient, SOURCE, configure_recording, restore_driver
    from factory_constructor.program import digest, save, validate
    from factory_constructor.verify_science import all_entities, verify

    bundle = args.checkpoint.resolve()
    config = json.loads((SOURCE / "config.json").read_text())
    manifest = checkpoints.validate(bundle, config=config)
    if manifest["stage"] != "constructor-idle":
        raise ValueError("restore proof needs the completed factory-idle checkpoint")
    read = lambda name: json.loads((bundle / "evidence" / name).read_text())
    program, execution = read("program.json"), read("execution.json")
    validate(program)
    if (program["goal"]["item"] != "automation-science-pack"
            or execution["status"] != "observed-complete"
            or execution["program_sha256"] != program["sha256"]):
        raise ValueError("checkpoint is not a completed declared science program")
    opening, final = read("constructor-opening.json"), read("constructor-final.json")
    if (digest(opening["capture"]) != program["binding"]["capture_sha256"]
            or digest(opening["state"]) != program["binding"]["state_sha256"]):
        raise ValueError("sealed program and opening observations differ")
    actions = [a for a in read("actions.json") if a["request"]["revision"] >= opening["state"]["revision"]]
    events = [json.loads(line) for line in (bundle / "evidence/player-crafts.jsonl").read_text().splitlines()]
    checked = verify(final, opening, program["design"], program["deployment"], actions,
                     read("constructor-sample.json"), read("constructor-baseline.json"), events,
                     reconciliation=read("constructor-reconciliation.json"))
    if checked != read("constructor-verification.json") or not checked["goal_complete"]:
        raise ValueError("sealed native evidence no longer reproduces its science proof")
    deployment = read("deployment.json")
    refresh(deployment, final)
    saved = json.loads((bundle / "driver.json").read_text())
    session = graphics = None
    try:
        with science_overlay() as overlay:
            session = ScienceSession(args.factorio, args.out, config, scenario_overlay=overlay, checkpoint=bundle)
        session.start()
        configure_recording(session, False)
        graphics = GraphicalClient(session)
        graphics.record = False
        graphics.start()
        # This compares the entire checkpoint_state RPC, including native
        # world state and command ledger, before restoring any driver metadata.
        driver = restore_driver(ScienceDriver(session, graphics), bundle)
        actual = session.client.call({"op": "checkpoint_state"})
        if actual != saved["game"] or not actual["state"]["paused"]:
            raise ValueError("restored world or ledger changed across read-only checks")
        if actual["state"]["tick"] != manifest["tick"]:
            raise ValueError("restored world advanced beyond its sealed tick")
        refresh(deployment, {"state": actual["state"]})
        if driver.actions != read("actions.json") or driver.counter != saved["counter"]:
            raise ValueError("restored driver action history differs from sealed evidence")
        png_count = len(list(session.root.rglob("*.png")))
        if png_count:
            raise ValueError("restore-only validation unexpectedly captured screenshots")
        report = {"restored_exact_world_and_ledger": True, "native_science_proof_replayed": True,
                  "tick": actual["state"]["tick"], "revision": actual["state"]["revision"],
                  "last_command_id": actual["last_command_id"], "actions": len(driver.actions),
                  "entities": len(all_entities(actual["state"]["science"])),
                  "checkpoint_state_sha256": digest(actual), "source_game_sha256": manifest["files"]["game.zip"],
                  "science_per_minute": checked["science_per_minute"], "server_starts": session.starts,
                  "png_count": png_count, "simulation_ticks_advanced": 0}
        save(session.root / "restore-verification.json", report)
        print(json.dumps(report), flush=True)
    finally:
        if graphics:
            graphics.close()
        if session:
            session.close()


if __name__ == "__main__":
    main()
