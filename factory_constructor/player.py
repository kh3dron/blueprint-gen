"""Translate program capabilities to the paid player primitives and check observations."""
from collections import Counter
from copy import deepcopy
import json
import math

from .legacy import verify_iron
from .program import digest, save
from .deployment import entities


class BoundClient:
    """Bind legacy action receipts to the actual declaration and running stack leaf."""
    def __init__(self, client, goal):
        self.client, self.goal, self.node = client, goal, None

    def __getattr__(self, key):
        return getattr(self.client, key)

    def call(self, request):
        if "goal" in request:
            request["goal"] = f"Automate {self.goal['per_minute']:g} {self.goal['item']}/min"
            request["program_node"] = self.node
        return self.client.call(request)


class PlayerPort:
    capabilities = {"preflight": "sites_clear", "gather": "inventory_gain", "process": "inventory_recipe_delta",
        "inventory": "inventory_at_least", "begin_measurement": "empty_baseline", "place": "paid_entity",
        "retain": "entity_retained", "mark_reconciliation": "boundary_recorded",
        "finish_reconciliation": "inventory_unchanged", "idle": "idle_window", "verify_service": "connected_service"}
    capabilities.update(refresh_deployment="deployment_matches", extend_measurement="deployment_baseline")

    def __init__(self, driver, program, *, wait_speed=40):
        self.driver, self.program, self.wait_speed = driver, program, wait_speed
        self.root = driver.root
        self.opening = deepcopy(driver.observations[-1])
        self.samples, self.warmup = [], []
        self.baseline = self.reconciliation = self.verification = None

    def status(self):
        return self.driver.session.client.call({"op": "status"})

    def validate(self, program):
        for node in program["nodes"]:
            if node["operation"] and self.capabilities.get(node["operation"]) != node["check"]:
                raise ValueError("unsupported player capability or completion predicate")
        binding, state = program["binding"], self.status()
        if (digest(self.opening["capture"]) != binding["capture_sha256"]
                or digest(self.opening["state"]) != binding["state_sha256"]
                or any(state[k] != binding[k] for k in ("tick", "revision", "character_id", "surface_index", "force_index", "map_seed", "active_mods"))
                or state["inventory"] != self.opening["state"]["inventory"] or not state["paused"]):
            raise ValueError("stale initial observation; compile against the current idle world")
        self.driver.session.client = BoundClient(self.driver.session.client, program["goal"])
        save(self.root / "constructor-opening.json", self.opening)

    def action(self, op, args, title):
        return self.driver.action(op, args, title)

    def perform(self, node):
        self.driver.session.client.node = node["id"]
        self.driver.milestone = node["parent"]
        op, args = node["operation"], node["inputs"]
        before = self.status()
        retained=self.program.get("change", {}).get("retained", {})
        actual=entities(before) if retained else {}
        for address, expected in retained.items():
            if actual.get(address) != expected:
                raise ValueError("retained deployment changed before " + node["id"])
        start = len(self.driver.actions)
        value = None
        if op == "refresh_deployment":
            pass
        elif op == "preflight":
            value = self.action("preflight_power", args, "Check declared construction sites")["outcome"]["value"]
        elif op == "gather":
            self.driver.mine(args["item"], args["quantity"])
        elif op == "process":
            self.driver.execute_bill({"construction": {"requires_research": [], "unsupported": [], "gather": {}, "steps": [args]}})
        elif op == "inventory":
            pass
        elif op in ("begin_measurement", "extend_measurement"):
            value = self.action("begin_iron" if op=="begin_measurement" else "begin_iron_update", args,
                                "Observe deposits and deployment baseline")["outcome"]["value"]
            self.baseline = value
            save(self.root / "constructor-baseline.json", value)
        elif op in ("place", "retain"):
            spec = args["spec"]
            if op == "place":
                p, position = spec["position"], before["position"]
                reach = min(before["build_distance"], before["reach_distance"]) - 1.25
                half = 1 if spec["name"] in {"stone-furnace", "burner-mining-drill"} else .5
                inside = all(abs(position[k] - p[k]) < half + .4 for k in ("x", "y"))
                if inside or math.dist([position[k] for k in ("x", "y")], [p[k] for k in ("x", "y")]) > reach:
                    command = '/silent-command rcon.print(helpers.table_to_json(remote.call("iron-supply-dev","approach",' + str(p["x"]) + ',' + str(p["y"]) + ')))'
                    approach = json.loads(self.driver.session.client.execute(command))
                    self.action("walk_to", {"position": approach}, "Walk within reach of " + spec["address"])
            value = self.action("place_iron", args, ("Build " if op == "place" else "Retain ") + spec["address"])["outcome"]["value"]
        elif op == "mark_reconciliation":
            self.reconciliation = {"before": before}
        elif op == "finish_reconciliation":
            keys = ("inventory", "cursor_placements", "player_build_events")
            self.reconciliation.update(after=before, refusal_id=None,
                drift_before={k: before[k] for k in keys}, drift_after={k: before[k] for k in keys})
            save(self.root / "constructor-reconciliation.json", self.reconciliation)
        elif op == "idle":
            self.driver.session.client.call({"op": "speed", "speed": self.wait_speed})
            try:
                value = self.action("wait_iron", {"ticks": args["ticks"]}, "Observe " + args["phase"] + " minute")["outcome"]["value"]
            finally:
                self.driver.session.client.call({"op": "speed", "speed": before["speed"]})
            collection = self.warmup if args["phase"] == "warmup" else self.samples
            collection.append(value)
            save(self.root / ("constructor-" + args["phase"] + ".json"), collection)
        elif op == "verify_service":
            self.driver.observe()
            final = self.driver.observations[-1]
            save(self.root / "constructor-final.json", final)
            events = self.driver.session.output / "player-crafts.jsonl"
            # Each declaration has its own revision boundary, even in one live session.
            actions=[a for a in self.driver.actions if a["request"]["revision"]>=self.opening["state"]["revision"]]
            self.verification = verify_iron(final, self.opening, self.program["design"],
                json.loads((self.root / "feed-design.json").read_text()),
                json.loads((self.root / "coal-design.json").read_text()), actions,
                self.samples, self.baseline, self.reconciliation,
                [json.loads(line) for line in events.read_text().splitlines()], require_refusal=False,
                previous_design=(self.program.get("deployment") or {}).get("design"))
            save(self.root / "constructor-verification.json", self.verification)
        else:
            raise ValueError("unsupported operation: " + op)
        return {"before": before, "after": self.status(), "value": value,
                "actions": self.driver.actions[start:]}

    def check(self, node, receipt):
        op, args = node["operation"], node["inputs"]
        before, after, value = receipt["before"], receipt["after"], receipt["value"]
        ok = all(a["outcome"]["status"] == "done" for a in receipt["actions"])
        if op == "refresh_deployment":
            ok &= entities(after)==args["expected"]
        elif op == "gather":
            ok &= after["inventory"].get(args["item"], 0) - before["inventory"].get(args["item"], 0) >= args["quantity"]
        elif op == "process":
            expected = Counter(before["inventory"])
            expected.subtract(args["inputs"])
            if args["kind"] == "smelt":
                expected.subtract({"coal": args["coal"]})
            expected.update(args["outputs"])
            ok &= all(v >= 0 for v in expected.values()) and +expected == Counter(after["inventory"])
        elif op == "inventory":
            ok &= all(after["inventory"].get(k, 0) >= v for k, v in args["items"].items())
        elif op == "begin_measurement":
            ok &= not value["entities"] and len(value["deposits"]) == 4 * len(args["mining_areas"])
        elif op == "extend_measurement":
            ok &= entities({"iron":value})==args["expected"] and len(value["deposits"])==4*len(args["mining_areas"])
        elif op in ("place", "retain"):
            spec = args["spec"]
            entity = next((e for e in after["iron"]["entities"] if e["address"] == spec["address"]), {})
            ok &= all(entity.get(k) == spec[k] for k in ("name", "position", "direction"))
            if op == "retain":
                ok &= value["added"] is False and all(before[k] == after[k] for k in ("inventory", "player_build_events", "cursor_placements"))
            else:
                expected = Counter(before["inventory"])
                expected.subtract({spec["name"]: 1})
                events = [e for e in after["player_build_events"] if e["id"] == value["id"]]
                ok &= (value["added"] is True and all(v >= 0 for v in expected.values())
                       and +expected == Counter(after["inventory"]) and len(events) == 1)
        elif op == "finish_reconciliation":
            ok &= all(self.reconciliation["before"][k] == after[k] for k in ("inventory", "player_build_events", "cursor_placements"))
        elif op == "idle":
            ok &= (value["player_idle"] is True and value["idle_ticks"] == args["ticks"]
                   and value["after"]["tick"] - value["before"]["tick"] == args["ticks"]
                   and value["inventory_before"] == value["inventory_after"]
                   and value["position_before"] == value["position_after"])
        elif op == "verify_service":
            ok &= (self.verification["automatic_iron_supply_observed"] is True
                   and min(self.verification["plates_per_minute"]) >= args["per_minute"])
        elif op == "preflight":
            ok &= bool(receipt["actions"])
        return {"observed_complete": bool(ok), "predicate": node["check"],
                "action_ids": [a["request"]["id"] for a in receipt["actions"]],
                "tick": after["tick"], "revision": after["revision"]}
