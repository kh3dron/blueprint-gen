#!/usr/bin/env python3
"""Continue iron/copper smelting and lab crafting in one world, recording actual trigger outcomes."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

from session import Session, ROOT

sys.path.insert(0, str(ROOT / "07_bootstrap_executor"))
from opening import observed_snapshot, furnace_design
from advisor_core.planner import next_step
from advisor_core.production import completion
from advisor_core.routes import compile_route
from advisor_core.survey import gather
from advisor_core.game_import import digest
from proving_ground import SOURCE


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


class Driver:
    def __init__(self, session):
        self.session = session
        self.root = session.root
        self.counter = 0
        self.observations = []
        self.actions = []
        self.milestone = "opening"

    def observe(self):
        observed = self.session.client.call({"op": "observe"})
        capture_path = self.session.artifact(observed["capture_path"])
        capture = json.loads(capture_path.read_text())
        snapshot, rules = observed_snapshot(capture, observed["state"])
        record = {**observed, "capture": capture}
        self.observations.append(record)
        directory = self.root / "observations"
        directory.mkdir(exist_ok=True)
        save(directory / f"{len(self.observations):03}.json", record)
        self.current = observed["state"]
        return snapshot, rules, capture

    def action(self, op, args, label):
        current = self.session.client.call({"op": "status"})
        self.counter += 1
        request = {"id": f"action-{self.counter:03}", "op": op, "args": args,
                   "tick": current["tick"], "revision": current["revision"],
                   "goal": "Produce 10 red science per minute", "milestone": self.milestone, "label": label}
        started = time.perf_counter()
        result = self.session.client.call(request)
        deadline = time.monotonic() + 40
        while result["status"] == "running" and time.monotonic() < deadline:
            time.sleep(.025)
            result = self.session.client.call({"op": "status", "id": request["id"]})
        record = {"request": request, "outcome": result, "wall_seconds": time.perf_counter() - started}
        self.actions.append(record)
        save(self.root / "actions.json", self.actions)
        if result["status"] != "done":
            raise RuntimeError(f"{label}: {result.get('error') or 'wall-time deadline exceeded'}")
        return record

    def mine(self, item, quantity):
        _, _, capture = self.observe()
        allocated = gather(capture, {item: quantity})
        if allocated["unplanned"]:
            raise ValueError("required minerals are not in the observed area")
        for target in allocated["steps"]:
            requested = self.action("route", {"target": target}, f"Find a walking route to {target['quantity']} {item}")
            result = requested["outcome"]["value"]
            filename = f"route-character-{result['character_id']}-request-{result['sequence']}.json"
            receipt = json.loads(self.session.artifact("blueprint-gen-observer/" + filename).read_text())
            now = self.session.client.call({"op": "status"})
            compiled = compile_route(receipt, current_tick=now["tick"])
            if compiled["kind"] != "walk_then_mine":
                raise ValueError(f"Native route requires replanning: {compiled.get('reasons')}")
            save(self.root / f"route-{result['sequence']:03}.json", {"receipt": receipt, "instructions": compiled})
            self.action("mine", {"sequence": result["sequence"], "receipt_sha256": digest(receipt)},
                        f"Walk, then hand-mine {target['quantity']} {item} at ({target['position']['x']}, {target['position']['y']})")

    def execute_bill(self, action):
        bill = action["construction"]
        if bill["requires_research"] or bill["unsupported"]:
            raise ValueError("construction bill has unresolved prerequisites")
        if any(step["kind"] not in {"gather", "place", "smelt", "handcraft"} for step in bill["steps"]):
            raise ValueError("construction bill requires an unsupported action")
        # Procure this finite job before processing. The next job gets a fresh
        # snapshot, so prior crafts and inventory are never silently counted twice.
        for item, quantity in sorted(bill["gather"].items(), key=lambda kv: (kv[0] != "coal", kv[0])):
            self.mine(item, quantity)
        for step in bill["steps"]:
            if step["kind"] == "gather":
                continue
            if step["kind"] == "place":
                if step["item"] != "stone-furnace" or step["quantity"] != 1:
                    raise ValueError("only the starter furnace placement adapter is supported")
                self.observe()
                design, change = furnace_design(self.current)
                address, entity = next(iter(design["entities"].items()))
                save(self.root / "furnace-design.json", {"design": design, "change": change})
                record = self.action("place", {"spec": {"address": address, **entity}}, f"Place starter furnace at {entity['position']}")
                self.placement_request = record["request"]
            elif step["kind"] == "smelt":
                self.observe()
                stations = self.current["built"]
                if len(stations) != 1:
                    raise ValueError("expected one observed managed furnace")
                address = stations[0]["address"]
                self.action("approach", {"address": address}, "Walk within reach of the existing furnace")
                self.action("smelt", {"address": address, "recipe": step["recipe"], "crafts": step["crafts"], "coal": step["coal"]},
                            f"Load ore and {step['coal']} coal; smelt and collect {step['outputs']}")
            else:
                self.action("handcraft", {"recipe": step["recipe"], "crafts": step["crafts"]},
                            f"Handcraft {step['crafts']} batches of {step['recipe']}")


def verify(driver, milestones, restart):
    initial = driver.observations[0]["state"]
    final = driver.observations[-1]["state"]
    if [m["technology"] for m in milestones] != ["steam-power", "electronics", "automation-science-pack"]:
        raise ValueError("did not complete the three expected observed triggers")
    if not {"steam-power", "electronics"} <= set(final["researched"]):
        raise ValueError("smelting research not present in final observation")
    if final["paid_furnaces"] != 1 or len(final["built"]) != 1:
        raise ValueError("furnace was replaced or built without paying its item")
    furnace_id = restart["before"]["built"][0]["id"]
    if (final["built"][0]["id"] != furnace_id
            or final["built"][0]["position"] != restart["before"]["built"][0]["position"]
            or final["built"][0]["crafts"] != 65):
        raise ValueError("the furnace identity did not survive reuse/restart")
    if final["crafted"]["iron-plate"] != 50 or final["crafted"]["copper-plate"] != 15 or final["crafted"]["lab"] not in (0, 1):
        raise ValueError("unexpected force production totals")
    # Whole-inventory conservation is independently checked by each native craft
    # and paired transfer; additionally pin this complete finite opening's result.
    if final["inventory"] != {"iron-plate": 22, "wood": 1, "burner-mining-drill": 1, "lab": 1}:
        raise ValueError(f"unexpected final finite inventory: {final['inventory']}")
    mined, smelted, handcrafted = Counter(), Counter(), Counter()
    for action in driver.actions:
        result = action["outcome"]
        if result["status"] != "done":
            raise ValueError("action did not finish")
        request, value = action["request"], result["value"]
        if request["op"] == "mine":
            if value["gained"] != value["depleted"] or value["gained"] <= 0:
                raise ValueError("mining ledger does not conserve resources")
            mined[value["item"]] += value["gained"]
        elif request["op"] == "smelt":
            if value["station_id"] != furnace_id:
                raise ValueError("smelting switched stations")
            smelted.update(value["outputs"])
        elif request["op"] == "handcraft":
            handcrafted[value["recipe"]] += value["crafts"]
    if mined != {"coal": 6, "iron-ore": 50, "copper-ore": 15} or smelted != {"iron-plate": 50, "copper-plate": 15} or handcrafted["lab"] != 1:
        raise ValueError("action ledger does not match the finite opening")
    for transfer in driver.observations[-1]["transfers"]:
        if transfer["count"] != transfer["removed"] or transfer["count"] != transfer["inserted"]:
            raise ValueError("transfer ledger does not conserve inventory")
    if not equal_checkpoint(restart["before"], restart["after"]):
        raise ValueError("checkpoint changed across save/restart")
    if restart["duplicate_ignored"] is not True or restart["stale_rejected"] is not True:
        raise ValueError("missing idempotence or stale-request refusal evidence")
    snapshot, rules = observed_snapshot(driver.observations[-1]["capture"], final)
    lab_research = "automation-science-pack" in final["researched"]
    if not lab_research:
        # The native standalone-character crafting queue produced a paid lab but
        # this engine did not credit its force counter. Preserve that discrepancy
        # as an observation gap; do not keep making labs or grant research.
        snapshot.document["observation_gaps"].append(
            "The standalone character crafted a lab, but its research trigger was not credited. "
            "Check player-attributed crafting before producing another lab.")
    if completion(snapshot, rules)["complete"]:
        raise ValueError("finite crafting incorrectly established sustained red science")
    return {"active_mods": final["active_mods"], "initial_inventory": initial["inventory"],
            "final_inventory": final["inventory"], "produced": final["crafted"], "researched": final["researched"],
            "mined": dict(mined),
            "furnace_id": furnace_id, "furnace_position": final["built"][0]["position"],
            "furnace_crafts": final["built"][0]["crafts"], "paid_furnaces": final["paid_furnaces"],
            "simulation_ticks": final["tick"] - initial["tick"], "command_count": len(driver.actions),
            "server_starts": driver.session.starts, "checkpoint_preserved": True, "duplicate_after_restart_ignored": restart["duplicate_ignored"],
            "stale_command_rejected": restart["stale_rejected"], "goal_complete": False,
            "lab_handcrafted": True, "lab_research_observed": lab_research,
            "research_attribution_gap": not lab_research,
            "next_action": next_step(snapshot, rules)}


def equal_checkpoint(a, b):
    return a == b


def run(binary, destination, config, speed):
    started = time.perf_counter()
    session = Session(binary, destination, config)
    driver = Driver(session)
    milestones = []
    try:
        session.start()
        session.client.call({"op": "speed", "speed": speed})
        driver.observe()
        initial_tick = driver.current["tick"]
        for technology in ("steam-power", "electronics", "automation-science-pack"):
            snapshot, rules, _ = driver.observe()
            action = next_step(snapshot, rules)
            if action["kind"] != "trigger" or action["technology"] != technology:
                raise ValueError(f"unexpected advisor instruction: {action['title']}")
            driver.milestone = technology
            save(session.root / f"plan-{technology}.json", action)
            print(action["title"], flush=True)
            driver.execute_bill(action)
            result = driver.action("research", {"technology": technology}, f"Check whether {technology} unlocked")
            driver.observe()
            milestones.append({"technology": technology, "observed": result["outcome"]["value"]["observed"],
                               "tick": driver.current["tick"], "state": driver.current})
            if not milestones[-1]["observed"] and technology != "automation-science-pack":
                raise ValueError(f"required research was not observed: {technology}")
            if technology == "steam-power":
                before = session.client.call({"op": "status"})
                session.client.call({"op": "save", "name": "after-steam-power"})
                checkpoint = session.root / "user-data/saves/after-steam-power.zip"
                deadline = time.monotonic() + 10
                while not checkpoint.exists() and time.monotonic() < deadline:
                    time.sleep(.05)
                if not checkpoint.exists():
                    raise RuntimeError("checkpoint save was not written")
                session.close()
                session.start(checkpoint)
                after = session.client.call({"op": "status"})
                if not equal_checkpoint(before, after):
                    raise ValueError("reloaded checkpoint differs from saved world")
                old = driver.placement_request
                reply = session.client.call(old)
                unchanged = session.client.call({"op": "status"})
                duplicate_ignored = reply["status"] == "done" and unchanged == after
                stale = {**old, "id": "stale-probe"}
                try:
                    session.client.call(stale)
                except RuntimeError as error:
                    stale_rejected = "stale checkpoint" in str(error)
                else:
                    stale_rejected = False
                if not duplicate_ignored or not stale_rejected or session.client.call({"op": "status"}) != after:
                    raise ValueError("idempotence/stale-request checks did not preserve state")
                restart = {"before": before, "after": after, "duplicate_ignored": duplicate_ignored, "stale_rejected": stale_rejected}
                save(session.root / "restart.json", restart)
        driver.observe()
        report = verify(driver, milestones, restart)
        save(session.root / "milestones.json", milestones)
        save(session.root / "verification.json", report)
        save(session.root / "next-action.json", report["next_action"])
        session.client.call({"op": "save", "name": "after-lab"})
        wall = time.perf_counter() - started
        save(session.root / "performance.json", {"requested_speed": speed, "total_wall_seconds": wall,
            "simulated_seconds": (driver.current["tick"] - initial_tick) / 60,
            "overall_speed_vs_realtime": (driver.current["tick"] - initial_tick) / 60 / wall,
            "includes": "map conversion, two server starts, real saved-state continuation, pauses for planning, verification"})
        print(json.dumps({k: v for k, v in report.items() if k != "next_action"}, indent=2), flush=True)
        return report
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--factorio", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=SOURCE / "config.json")
    parser.add_argument("--speed", type=int, choices=(1, 10, 40), default=40)
    parser.add_argument("--record", action="store_true", help="render a recorded-state GIF/MP4 after the run (requires Pillow)")
    args = parser.parse_args()
    try:
        run(args.factorio, args.out, json.loads(args.config.read_text()), args.speed)
        if args.record:
            from render_trace import build as render_recording
            print(render_recording(args.out, args.out / "recording"))
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f"live-opening: {error}\n")
