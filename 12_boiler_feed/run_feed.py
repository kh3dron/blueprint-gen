#!/usr/bin/env python3
"""Connect the verified coal module to the boiler and measure useful research load."""
import argparse
from copy import deepcopy
from contextlib import contextmanager
from hashlib import sha256
import inspect
import json
import math
from pathlib import Path
import shutil
import tempfile
import time

from feed_plan import BoilerFeed
from coal_profile import CoalDriver, CoalSession
from run_coal import continue_coal
from run_power import run, save, SOURCE, bill
from run_player import GraphicalClient, configure_recording, capture_call, capture_boundary
from checkpoint import write_checkpoint, validate_bundle, restore_driver
from run_report import report

HERE = Path(__file__).resolve().parent


def prepare_feed(driver):
    continue_coal(driver)
    root = driver.root
    save(root / "coal-actions.json", driver.actions)
    driver.milestone = "automatic-boiler-fuel"
    snapshot, rules, _ = driver.observe()
    design = BoilerFeed.from_state(driver.current).document()
    save(root / "feed-design.json", design)
    science = rules.technologies["logistics"]
    if science["count"] != 20 or science["seconds"] != 15 or science["packs"] != {"automation-science-pack": 1}:
        raise ValueError("unsupported runtime research load")
    materials = bill(snapshot, rules, {**design["bill"], "automation-science-pack": science["count"]})
    save(root / "feed-materials.json", materials)
    print("Procure the boiler feed and twenty research packs from finite stock.", flush=True)
    driver.execute_bill({"construction": materials})
    driver.observe()
    save(root / "feed-opening-observation.json", driver.observations[-1])
    return design


def preparation_contract():
    return {"method": "feed-ready-v1", "prepare_sha256": sha256(inspect.getsource(prepare_feed).encode()).hexdigest()}


def continue_feed(driver, *, config, prepare_only=False, wait_speed=10):
    prepare_feed(driver)
    path = write_checkpoint(driver, driver.root / "checkpoints/feed-ready", config=config, contract=preparation_contract())
    print(json.dumps({"checkpoint_ready": str(path), "tick": driver.current["tick"]}), flush=True)
    if not prepare_only:
        execute_feed(driver, wait_speed=wait_speed)


def idle_window(driver, label, speed):
    previous = driver.session.client.call({"op": "status"})["speed"]
    if speed != previous:
        driver.session.client.call({"op": "speed", "speed": speed})
    try:
        return driver.action("wait_feed", {"ticks": 3600}, label)
    finally:
        if speed != previous:
            driver.session.client.call({"op": "speed", "speed": previous})


def execute_feed(driver, *, wait_speed=10):
    root = driver.root
    prepared = json.loads((root / "feed-design.json").read_text())
    design = BoilerFeed.from_state(driver.current).document()
    if design["bill"] != prepared["bill"]:
        raise ValueError("feed materials changed; prepare a new checkpoint")
    save(root / "feed-design.json", design)
    science = {"count": 20}
    driver.action("preflight_power", {"specs": design["placements"]}, "Check the complete belt corridor in the engine")
    baseline = driver.action("begin_feed", {}, "Record original boiler fuel and steam before automatic delivery")
    save(root / "feed-baseline.json", baseline["outcome"]["value"])
    for spec in design["placements"]:
        p = spec["position"]
        position = driver.session.client.call({"op": "status"})["position"]
        if math.hypot(position["x"]-p["x"], position["y"]-p["y"]) > 4:
            driver.action("walk_to", {"position": {"x": p["x"]+2, "y": p["y"]+3}}, "Walk beside the belt, within reach of " + spec["address"])
        driver.action("place_feed", {"spec": spec}, "Build " + spec["address"] + " with the player cursor")
    before = driver.session.client.call({"op": "status"})
    for spec in design["placements"]:
        result = driver.action("place_feed", {"spec": spec}, "Reconcile " + spec["address"])
        if result["outcome"]["value"]["added"]:
            raise ValueError("repeat deployment duplicated a feed entity")
    after = driver.session.client.call({"op": "status"})
    for key in ("inventory", "player_build_events", "cursor_placements"):
        if before[key] != after[key]:
            raise ValueError("repeat feed placement changed paid construction")
    changed = deepcopy(design["placements"][0])
    changed["direction"] = 4
    try:
        driver.action("place_feed", {"spec": changed}, "Refuse direction drift at the existing chest extractor")
    except RuntimeError as error:
        if "declarative entity drift" not in str(error):
            raise
    else:
        raise ValueError("feed direction drift was not refused")
    refused = driver.session.client.call({"op": "status"})
    keys = ("inventory", "player_build_events", "cursor_placements")
    save(root / "feed-reconciliation.json", {"before": before, "after": after,
        "drift_before": {k:after[k] for k in keys}, "drift_after": {k:refused[k] for k in keys},
        "refusal_id":driver.actions[-1]["request"]["id"]})
    idle_window(driver, "Let automatic coal delivery fill the boiler during one startup minute", wait_speed)
    lab = next(e for e in after["power_entities"] if e["address"] == "power.lab")["position"]
    driver.action("walk_to", {"position": {"x": lab["x"]+3, "y": lab["y"]+3}}, "Walk to the lab with twenty paid research packs")
    driver.action("start_feed_research", {"packs": science["count"]}, "Load twenty red science packs and start Logistics research")
    driver.milestone = "measure-automatic-boiler-fuel"
    windows = []
    for i in range(5):
        print(f"Measure automatic fuel under research load: minute {i+1}/5.", flush=True)
        result = idle_window(driver, f"Stand idle during research minute {i+1}/5", wait_speed)
        windows.append(result["outcome"]["value"])
        save(root / "feed-windows.json", windows)
    result = driver.action("research", {"technology": "logistics"}, "Observe Logistics completion in the automatically fueled lab")
    if not result["outcome"]["value"]["observed"]:
        raise ValueError("Logistics did not complete")
    driver.observe()
    save(root / "feed-final-observation.json", driver.observations[-1])
    from verify_feed import verify_directory
    report = verify_directory(root)
    save(root / "feed-verification.json", report)
    print(json.dumps({"feed_verified": report["automatic_boiler_fuel_observed"],
                      "lab_kw": report["lab_kw_by_minute"]}), flush=True)
    driver.session.client.call({"op": "save", "name": "boiler-feed"})


@contextmanager
def feed_overlay():
    with tempfile.TemporaryDirectory(prefix="blueprint-feed-overlay-") as temporary:
        overlay = Path(temporary)
        for name in ("extension", "adapter", "control"):
            target = {"extension": "coal", "adapter": "coal_adapter", "control": "coal_control"}[name]
            shutil.copy2(HERE.parent / f"11_coal_supply/integration/{name}.lua", overlay / f"{target}.lua")
        for source in (HERE / "integration").glob("*.lua"):
            shutil.copy2(source, overlay / source.name)
        yield overlay


def run_experiment(binary, out, config, speed, *, resume=None, prepare_only=False, record=False, wait_speed=10):
    started = time.perf_counter()
    start_tick, start_action = 0, 0
    if resume:
        if prepare_only:
            raise ValueError("--prepare-only cannot be combined with --resume")
        validate_bundle(resume, config=config, contract=preparation_contract())
    try:
        with feed_overlay() as overlay:
            if resume is None:
                result = run(binary, out, config, speed, scenario_overlay=overlay,
                    session_type=CoalSession, driver_type=CoalDriver, record=record,
                    continue_with=lambda d:continue_feed(d, config=config, prepare_only=prepare_only, wait_speed=wait_speed))
            else:
                session = CoalSession(binary, out, config, scenario_overlay=overlay, checkpoint=resume)
                graphics = None
                try:
                    session.start()
                    configure_recording(session, record)
                    graphics = GraphicalClient(session)
                    graphics.record = record
                    graphics.start()
                    driver = restore_driver(CoalDriver(session, graphics), resume)
                    start_tick, start_action = driver.current["tick"], len(driver.actions)
                    save(driver.root / "resume-provenance.json", {"checkpoint": str(Path(resume).resolve()),
                        "tick": start_tick, "counter": driver.counter,
                        "continuation_sources": {str(p.relative_to(HERE)):sha256(p.read_bytes()).hexdigest()
                            for p in HERE.rglob("*") if p.suffix in {".lua", ".py"}
                            and not {"out", "tests", "__pycache__"}.intersection(p.relative_to(HERE).parts)}})
                    if record:
                        first = capture_call(session, "enable")
                        graphics.wait_image(first["image"])
                    session.client.call({"op": "speed", "speed": speed})
                    execute_feed(driver, wait_speed=wait_speed)
                    capture_boundary(session, graphics)
                    result = session.root
                finally:
                    if graphics:
                        graphics.close()
                    session.close()
        summary = report(result, status="checkpoint_ready" if prepare_only else "passed",
                         wall_seconds=time.perf_counter()-started, start_tick=start_tick, start_action=start_action)
        print(json.dumps(summary), flush=True)
        return result
    except Exception as error:
        if Path(out).is_dir():
            summary = report(out, status="failed", wall_seconds=time.perf_counter()-started,
                             start_tick=start_tick, start_action=start_action, error=error)
            print(json.dumps(summary), flush=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--factorio", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=SOURCE / "config.json")
    parser.add_argument("--speed", type=int, choices=(10,40), default=10)
    parser.add_argument("--wait-speed", type=int, choices=(10,40), default=10,
                        help="speed during passive boiler-feed observation windows")
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--resume", type=Path, help="resume a sealed feed-ready checkpoint")
    parser.add_argument("--prepare-only", action="store_true", help="build the verified opening and save a feed-ready checkpoint")
    args = parser.parse_args()
    try:
        run_experiment(args.factorio, args.out, json.loads(args.config.read_text()), args.speed,
                       resume=args.resume, prepare_only=args.prepare_only, record=args.record, wait_speed=args.wait_speed)
        if args.record:
            from render_feed import build
            print(build(args.out, args.out / "recording"))
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f"boiler-feed: {error}\n")
