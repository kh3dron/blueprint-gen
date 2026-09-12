"""Reusable, bounded construction knowledge. Goals and observations supply parameters."""
from copy import deepcopy
from collections import Counter
import json
import math

from .program import digest
from .legacy import Asset, IronSupply, ROOT, SIZES, bill
from .deployment import additions, refresh


def capacity_evidence(observation, rules):
    """Use each line's measured collection, capped by the live smelting recipe.

    This evidence supplies a planning estimate. The new deployment always needs
    its own connected production test, including the previously untested one-line case.
    """
    root = ROOT / "13_iron_supply/integration/fixtures"
    reference = json.loads((root / "iron-opening-observation.json").read_text())
    windows = json.loads((root / "iron-windows.json").read_text())
    if (observation["state"]["active_mods"] != reference["state"]["active_mods"]
            or observation["capture"]["resolved_rules"] != reference["capture"]["resolved_rules"]):
        raise ValueError("method capacity evidence needs the same engine profile and resolved mechanics")
    samples = []
    for window in windows:
        before = {e["address"]: e for e in window["before"]["entities"]}
        after = {e["address"]: e for e in window["after"]["entities"]}
        seconds = (window["after"]["tick"] - window["before"]["tick"]) / 60
        for key, entity in after.items():
            if entity["name"] == "wooden-chest":
                samples.append(((entity["contents"] or {}).get("iron-plate", 0)
                                - (before[key]["contents"] or {}).get("iron-plate", 0)) * 60 / seconds)
    recipe = rules.recipes["iron-plate"]
    furnace_rate = 60 * rules.machines["stone-furnace"]["speed"] * recipe["outputs"]["iron-plate"] / recipe["seconds"]
    rate = min(furnace_rate, min(samples))
    if rate <= 0:
        raise ValueError("method has no demonstrated positive capacity")
    return {"per_line_per_minute": rate, "furnace_limit_per_minute": furnace_rate,
            "basis": "minimum per-line chest collection in the five-window connected iron fixture",
            "windows_sha256": digest(windows), "mechanics_sha256": digest(reference["capture"]["resolved_rules"])}


def validate_geometry(design):
    """Reuse the declarative library's typed entity geometry without its old profile stamp."""
    specs = design["placements"]
    # The old asset vocabulary lacks burner inserters; both occupy one tile.
    # This alias is only for geometry validation, never for the paid entity bill.
    geometry_name = lambda s: "inserter" if s["name"] == "burner-inserter" else s["name"]
    left = math.floor(min(s["position"]["x"] - SIZES[geometry_name(s)][0] / 2 for s in specs))
    top = math.floor(min(s["position"]["y"] - SIZES[geometry_name(s)][1] / 2 for s in specs))
    right = math.ceil(max(s["position"]["x"] + SIZES[geometry_name(s)][0] / 2 for s in specs))
    bottom = math.ceil(max(s["position"]["y"] + SIZES[geometry_name(s)][1] / 2 for s in specs))
    entities = [{"name": geometry_name(s), "direction": s["direction"],
                 "position": {"x": s["position"]["x"] - left, "y": s["position"]["y"] - top}} for s in specs]
    Asset.from_module_json({"name": "ore-smelting", "width": right-left, "height": bottom-top,
                            "entities": entities, "inputs": [], "outputs": [], "wires": []})


class IronPlateMethod:
    output = "iron-plate"
    source = "factory_constructor.methods:IronPlateMethod/v2"

    def lower(self, goal, observation, snapshot, rules, builder, *, deployment=None):
        if observation["state"].get("iron") and deployment is None:
            raise ValueError("incremental migration needs the previous verified deployment record")
        retained=refresh(deployment, observation) if deployment else {}
        evidence = capacity_evidence(observation, rules)
        count = math.ceil(goal.per_minute / evidence["per_line_per_minute"])
        existing_count=len(deployment["design"]["mining_areas"]) if deployment else 0
        count=max(count,existing_count)
        if count > 2:
            raise ValueError(f"goal requires {count} lines; this method supports at most two")
        if deployment:
            design=IronSupply.extend(observation["capture"],observation["state"],deployment["design"],
                                    lines=count,minimum_per_min=goal.per_minute).document()
        else:
            design = IronSupply.from_observation(observation["capture"], observation["state"],
                                                 lines=count, minimum_per_min=goal.per_minute).document()
        validate_geometry(design)
        added=additions(design,retained)
        incremental_bill=dict(Counter(p["name"] for p in added))
        materials = bill(snapshot, rules, incremental_bill)
        if materials["requires_research"] or materials["unsupported"]:
            raise ValueError("procurement has unresolved prerequisites: " + str(materials["requires_research"] + materials["unsupported"]))
        if any(s["kind"] not in {"gather", "handcraft", "smelt"} for s in materials["steps"]):
            raise ValueError("this player procurement adapter requires an existing starter furnace")
        builder.document.update(method={"id": self.source, "count": count, "capacity_evidence": evidence,
                                       "existing_count":existing_count,"additional_count":count-existing_count},
                                design=design, materials=materials,
                                deployment=deepcopy(deployment),
                                change={"retained":retained,"add":added,"bill":incremental_bill},
                                boundary={"coal": design["source"], "electricity": design["power"],
                                    "contract": "reuse the connected coal/boiler checkpoint; verify all connected fuel stocks under the new load",
                                    "output": "iron plate collection chests; consumer routing requires a separate method"})
        builder.group("goal/supply", "goal", f"Establish {goal.per_minute:g} iron plates/min", self.source)
        for name, title in (("procure", "Acquire construction items"), ("build", "Construct and connect the module"),
                            ("reconcile", "Verify retained native builds"), ("measure", "Observe sustained output")):
            builder.group("goal/supply/" + name, "goal/supply", title, self.source)

        def step(name, parent, op, inputs, predicate):
            builder.step("goal/supply/" + name, "goal/supply/" + parent, op, inputs, predicate, self.source)

        if retained:
            step("refresh", "build", "refresh_deployment", {"expected":retained}, "deployment_matches")
        if added:
            step("preflight", "build", "preflight", {"specs": added}, "sites_clear")
        for i, (item, quantity) in enumerate(sorted(materials["gather"].items(), key=lambda p: (p[0] != "coal", p[0]))):
            step(f"procure/gather-{i}", "procure", "gather", {"item": item, "quantity": quantity}, "inventory_gain")
        for i, process in enumerate(materials["steps"]):
            if process["kind"] != "gather":
                step(f"procure/process-{i}", "procure", "process", deepcopy(process), "inventory_recipe_delta")
        step("procure/items", "procure", "inventory", {"items": incremental_bill}, "inventory_at_least")
        if retained:
            step("begin", "build", "extend_measurement", {"mining_areas":design["mining_areas"],"expected":retained}, "deployment_baseline")
        else:
            step("begin", "build", "begin_measurement", {"mining_areas": design["mining_areas"]}, "empty_baseline")
        for spec in added:
            step("build/" + spec["address"], "build", "place", {"spec": spec}, "paid_entity")
        step("reconcile/before", "reconcile", "mark_reconciliation", {}, "boundary_recorded")
        for spec in design["placements"]:
            step("reconcile/" + spec["address"], "reconcile", "retain", {"spec": spec}, "entity_retained")
        step("reconcile/after", "reconcile", "finish_reconciliation", {}, "inventory_unchanged")
        policy = design["measurement"]
        for phase, windows in (("warmup", policy["warmup_ticks"] // policy["window_ticks"]), ("sample", policy["windows"])):
            for i in range(windows):
                step(f"measure/{phase}-{i}", "measure", "idle", {"ticks": policy["window_ticks"], "phase": phase}, "idle_window")
        step("measure/service", "measure", "verify_service", {"item": goal.item, "per_minute": goal.per_minute}, "connected_service")
