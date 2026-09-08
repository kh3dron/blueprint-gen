#!/usr/bin/env python3
"""Build a finite steam-powered lab with native player cursor placement and research automation."""
import argparse
import json
from pathlib import Path
import shutil
import secrets
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "09_player_capture"))
from run_player import PlayerSession, GraphicalClient, RecordedDriver, capture_call, save, next_step, SOURCE
from verify_player import verify as verify_opening
from advisor_core.construction import bill
from power_plan import PowerIsland


def read_events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def inspect_run(binary, source, destination):
    """Read electric statistics from an existing paused experimental save."""
    source, root = Path(source).resolve(), Path(destination).resolve()
    root.mkdir(parents=True, exist_ok=False)
    session = PlayerSession.__new__(PlayerSession)
    session.root, session.process, session.client, session.log = root, None, None, None
    session.starts, session.password = 0, secrets.token_hex(16)
    config = (source / "config.ini").read_text()
    read_data = next(s for s in config.splitlines() if s.startswith("read-data="))
    (root / "config.ini").write_text(f"[path]\n{read_data}\nwrite-data={root / 'user-data'}\n")
    shutil.copy2(source / "server-settings.json", root / "server-settings.json")
    session.prefix = [str(binary), "--config", str(root / "config.ini"), "--mod-directory", str(source / "mods")]
    session.save = source / "user-data/saves/blueprint-gen-observer/live-opening.zip"
    try:
        session.start()
        result = session.client.execute('''/silent-command local e=game.surfaces.nauvis.find_entities_filtered{name="small-electric-pole"}[1]; local s=e.electric_network_statistics; rcon.print(helpers.table_to_json{input=s.input_counts,output=s.output_counts,input_quality=s.input_quality_counts,output_quality=s.output_quality_counts,current_in=s.current_input_quality_samples,current_out=s.current_output_quality_samples,engine_per_tick=s.get_flow_count{name={name="steam-engine",quality="normal"},category="output",precision_index=defines.flow_precision_index.five_seconds},lab_per_tick=s.get_flow_count{name={name="lab",quality="normal"},category="input",precision_index=defines.flow_precision_index.five_seconds}})''')
        save(root / "electric-statistics.json", json.loads(result))
        print(result, flush=True)
    finally:
        session.close()


def refusals(driver):
    results = []
    state = driver.session.client.call({"op": "status"})
    furnace = state["built"][0]["position"]
    probes = [
        ("out_of_reach", {"name": "lab", "position": {"x": 9999.5, "y": 9999.5}}),
        ("missing_item", {"name": "steam-engine", "position": {"x": -.5, "y": -9.5}}),
        ("cursor_build_blocked", {"name": "lab", "position": {"x": furnace["x"]+.5, "y": furnace["y"]+.5}}),
    ]
    for reason, spec in probes:
        before = driver.session.client.call({"op": "status"})
        try:
            driver.action("place_power", {"spec": {"address": "probe."+reason, "direction": 0, **spec}}, "Check refusal: " + reason)
        except RuntimeError as error:
            if reason not in str(error):
                raise
        else:
            raise ValueError("invalid placement unexpectedly succeeded")
        after = driver.session.client.call({"op": "status"})
        for key in ("inventory", "built", "power_entities", "cursor_placements", "player_build_events"):
            if before[key] != after[key]:
                raise ValueError("placement refusal changed inventory or entities")
        keys = ("inventory", "built", "power_entities", "cursor_placements", "player_build_events")
        results.append({"reason": reason, "request_id": driver.actions[-1]["request"]["id"], "unchanged": True,
                        "before": {k: before[k] for k in keys}, "after": {k: after[k] for k in keys}})
    save(driver.root / "refusals.json", results)


def run(binary, destination, config, speed):
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="blueprint-power-overlay-") as temporary:
        overlay = Path(temporary)
        for source in (HERE / "integration").glob("*.lua"):
            shutil.copy2(source, overlay / source.name)
        shutil.copy2(ROOT / "09_player_capture/integration/control.lua", overlay / "capture.lua")
        shutil.copy2(ROOT / "07_bootstrap_executor/integration/adapter.lua", overlay / "transfers.lua")
        session = PlayerSession(binary, destination, config, scenario_overlay=overlay)
    graphics = None
    try:
        session.start()
        graphics = GraphicalClient(session)
        print("Starting isolated player for native construction and powered research…", flush=True)
        attachment = graphics.start()
        save(session.root / "attachment.json", attachment)
        first = capture_call(session, "enable")
        graphics.wait_image(first["image"])
        session.client.call({"op": "speed", "speed": speed})
        driver = RecordedDriver(session, graphics)
        driver.observe()
        milestones = []
        for technology in ("steam-power", "electronics", "automation-science-pack"):
            snapshot, rules, _ = driver.observe()
            action = next_step(snapshot, rules)
            if action["kind"] != "trigger" or action["technology"] != technology:
                raise ValueError("unexpected opening instruction")
            driver.milestone = technology
            print(action["title"], flush=True)
            save(session.root / f"plan-{technology}.json", action)
            driver.execute_bill(action)
            result = driver.action("research", {"technology": technology}, "Observe " + technology)
            milestones.append(result["outcome"]["value"])
        driver.observe()
        save(session.root / "opening-final-observation.json", driver.observations[-1])
        opening = verify_opening(attachment, driver.observations[0], driver.observations[-1], driver.actions,
            read_events(session.output / "player-crafts.jsonl"), milestones)
        save(session.root / "opening-verification.json", opening)
        driver.milestone = "powered-lab"
        refusals(driver)
        snapshot, rules, capture = driver.observe()
        if next_step(snapshot, rules)["kind"] != "prepare_lab":
            raise ValueError("advisor did not request a powered lab")
        design = PowerIsland.from_survey(capture).document()
        save(session.root / "power-design.json", design)
        materials = bill(snapshot, rules, design["bill"])
        save(session.root / "power-materials.json", materials)
        print("Procure the steam power island from finite stock.", flush=True)
        driver.execute_bill({"construction": materials})
        driver.mine("coal", 3)
        driver.action("preflight_power", {"specs": design["placements"]}, "Check the proposed power island against the actual terrain")
        driver.action("walk_to", {"position": design["staging"]}, "Walk to the power island construction position")
        for spec in design["placements"]:
            driver.action("place_power", {"spec": spec}, f"Place {spec['name']} at {spec['position']} using the player cursor")
        before = session.client.call({"op": "status"})
        duplicate = driver.action("place_power", {"spec": design["placements"][-1]}, "Reconcile the lab again; retain the existing entity")
        after = session.client.call({"op": "status"})
        if duplicate["outcome"]["value"]["added"] or before["inventory"] != after["inventory"] or before["player_build_events"] != after["player_build_events"]:
            raise ValueError("repeat placement changed the deployment")
        driver.action("fuel_power", {"coal": 3}, "Load three paid coal into the boiler")
        snapshot, rules, _ = driver.observe()
        tech = rules.technologies["automation"]
        science = {name: count*tech["count"] for name,count in tech["packs"].items()}
        materials = bill(snapshot, rules, science)
        save(session.root / "research-materials.json", {"technology": "automation", "science": science, "construction": materials})
        driver.milestone = "automation-research"
        print("Craft ten red science packs, then research automation in the steam-powered lab.", flush=True)
        driver.execute_bill({"construction": materials})
        driver.action("walk_to", {"position": design["staging"]}, "Return within reach of the powered lab")
        driver.action("research_lab", {"technology": "automation", "packs": science["automation-science-pack"]},
                      "Load ten red science packs; let the steam-powered lab research automation")
        driver.observe()
        save(session.root / "final-observation.json", driver.observations[-1])
        save(session.root / "next-action.json", next_step(*driver.observe()[:2]))
        from verify_power import verify_directory
        save(session.root / "verification.json", verify_directory(session.root))
        last = capture_call(session, "capture")
        graphics.wait_image(last["image"])
        save(session.root / "performance.json", {"requested_speed": speed,
            "wall_seconds_before_encoding": time.perf_counter()-started,
            "simulation_ticks": driver.current["tick"]-driver.observations[0]["state"]["tick"]})
        print(json.dumps({"inventory": driver.current["inventory"], "researched": driver.current["researched"],
                          "power": driver.current["power_entities"]}, indent=2), flush=True)
        return session.root
    finally:
        if graphics:
            graphics.close()
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--factorio", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=SOURCE / "config.json")
    parser.add_argument("--speed", type=int, choices=(1, 10, 40), default=10)
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--inspect-run", type=Path, help="read electric statistics from an existing experiment's paused save")
    args = parser.parse_args()
    try:
        if args.inspect_run:
            inspect_run(args.factorio, args.inspect_run, args.out)
        else:
            run(args.factorio, args.out, json.loads(args.config.read_text()), args.speed)
        if args.record and not args.inspect_run:
            from render_power import build
            print(build(args.out, args.out / "recording"))
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f"powered-lab: {error}\n")
