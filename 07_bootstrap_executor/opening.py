"""Bounded bridge from observed starter stock to a declarative, paid furnace.

Only the disposable scenario executes these instructions. Replay checkpoints are
observations of actual actions, never construction.bill's hypothetical inventory.
"""
from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "05_advisor_experiment"))
sys.path.insert(0, str(ROOT / "06_declarative_factory"))
from advisor_core.game_import import digest, import_capture, review_template
from advisor_core.planner import next_step
from advisor_core.survey import gather, distance
from factory import Asset, Factory, Module, Tile, plan


def observed_snapshot(capture, state):
    if (capture["tick"] != state["tick"] or capture["active_mods"] != state["active_mods"]
            or capture["scope"]["surface_index"] != state["surface_index"]
            or capture["scope"]["force_index"] != state["force_index"]
            or capture["scope"]["map_seed"] != state["map_seed"]
            or sorted(capture["researched"]) != sorted(state["researched"])
            or capture["crafted"]["iron-plate"] != state["produced_iron"]
            or distance(capture["player"]["position"], state["position"]) > 0.001):
        raise ValueError("actor observation and survey describe different checkpoints")
    review = review_template(capture)
    review.update(inventory=state["inventory"], supplies_per_s={}, available_power_kw=0)
    for settings in review["machines"].values():
        settings.update(connected=False, output_open=True)
    return import_capture(capture, review)


def procurement(capture, state):
    snapshot, rules = observed_snapshot(capture, state)
    if snapshot.machines or snapshot.researched or state["produced_iron"] != 0:
        raise ValueError("this experiment requires a fresh opening, without machines or research")
    action = next_step(snapshot, rules)
    if action["kind"] != "trigger" or action.get("technology") != "steam-power":
        raise ValueError("advisor did not request the supported steam-power opening")
    materials = action["construction"]
    if (materials["requires_research"] or materials["unsupported"]
            or materials["inventory_used"] != {"stone-furnace": 1}
            or materials["gather"] != {"iron-ore": 50, "coal": 4}):
        raise ValueError("opening differs from the supported starter-furnace method")
    # Coal first keeps the final standing position near the iron patch. Both
    # allocations use this real survey; only later native receipts authorize paths.
    targets = []
    for item in ("coal", "iron-ore"):
        allocated = gather(capture, {item: materials["gather"][item]})
        if allocated["unplanned"] or len(allocated["steps"]) != 1:
            raise ValueError("opening needs one accessible, sufficiently stocked tile per mineral")
        targets.append(allocated["steps"][0])
    return {"schema_version": 1, "ruleset_sha256": rules.digest,
            "capture_sha256": digest(capture), "initial_state_sha256": digest(state),
            "advisor_action": action, "materials": materials, "targets": targets,
            "routes": [], "method": "finite 50-plate opening on a disposable proving ground"}


def furnace_design(state):
    candidates = state["furnace_sites"]
    if not candidates:
        raise ValueError("no observed clear furnace site within conservative build and transfer reach")
    p = min(candidates, key=lambda p: (distance(p, state["position"]), p["x"], p["y"]))
    asset = Asset.from_module_json({"name": "starter-furnace", "width": 2, "height": 2,
                                   "entities": [{"name": "stone-furnace", "position": {"x": 1, "y": 1}}],
                                   "inputs": [], "outputs": [], "wires": []})
    design = Factory("opening", (Module("smelter", asset, Tile(p["x"] - 1, p["y"] - 1)),), ()).compile()
    change = plan(design)
    if change["conflicts"] or change["bill"] != {"stone-furnace": 1}:
        raise ValueError("declarative furnace bill is incompatible with this method")
    if state["inventory"].get("stone-furnace", 0) < change["bill"]["stone-furnace"]:
        raise ValueError("observed inventory cannot pay the declarative bill")
    return design, change


def executable(procurement_plan, state):
    result = deepcopy(procurement_plan)
    expected = {"iron-ore": 50, "coal": 4}
    if any(state["inventory"].get(k, 0) < v for k, v in expected.items()):
        raise ValueError("gathering has not been observed complete")
    design, change = furnace_design(state)
    address, entity = next(iter(design["entities"].items()))
    smelt = next(s for s in result["materials"]["steps"] if s["kind"] == "smelt")
    result.update(design=design, change=change, placement={"address": address, **entity},
                  placement_state=state, smelt=smelt)
    return result


def check_replay(stage, first, receipts):
    if stage["states"]["initial-state"] != first["states"]["initial-state"] or stage["captures"][0] != first["captures"][0]:
        raise ValueError("initial world differs between replay stages")
    for actual, expected in zip(stage["receipts"], receipts):
        if actual != expected:
            raise ValueError("fresh native route differs from replay receipt; discard run and replan")
    if len(stage["receipts"]) < len(receipts):
        raise ValueError("replay did not regenerate every consumed receipt")


def verify_result(result, instructions, initial):
    """Check conservation and the observed trigger, not just scenario success."""
    def require(ok, message):
        if not ok:
            raise ValueError(message)
    expected = dict(initial["inventory"])
    expected.pop("stone-furnace")
    expected["iron-plate"] = expected.get("iron-plate", 0) + 50
    require(result["final"]["inventory"] == expected, "final inventory does not conserve starting items and 50 new plates")
    require(result["final"]["produced_iron"] - initial["produced_iron"] == 50
            and result["furnace"]["products_finished"] == 50, "independent production counters differ")
    require("steam-power" in result["final"]["researched"], "steam-power was not observed unlocked")
    require(len(result["mining"]) == 2, "missing mining evidence")
    for actual, target, route in zip(result["mining"], instructions["targets"], instructions["routes"]):
        require(actual["item"] == target["item"] and actual["gained"] == target["quantity"]
                and actual["depleted"] == target["quantity"]
                and actual["receipt_sha256"] == route["receipt_sha256"], "mining gain/depletion/receipt mismatch")
    require(result["furnace"]["position"] == instructions["placement"]["position"]
            and result["furnace"]["address"] == instructions["placement"]["address"], "built furnace differs from declaration")
    require(result["furnace"]["input"] in ({}, []) and result["furnace"]["output"] in ({}, []), "furnace buffers were not drained")
    transfers = result["transfers"]
    require([(t["item"], t["count"]) for t in transfers] == [("iron-ore", 50), ("coal", 4), ("iron-plate", 50)], "unexpected transfer ledger")
    require(all(t["removed"] == t["inserted"] == t["count"] for t in transfers), "transfer did not conserve items")
    require(result["paid_furnaces"] == 1 and result["retained_on_repeat"] is True, "placement was free or duplicated")
    require(set(result["refusals"]) == {"out_of_reach", "collision", "missing_item", "short_transfer"}
            and all(result["refusals"].values()), "missing refusal evidence")
    require(result["smelting_ticks"] >= instructions["smelt"]["processing_seconds"] * 60 - 1, "smelting skipped game time")
    return {"factorio_version": initial["active_mods"]["base"],
            "ruleset_sha256": instructions["ruleset_sha256"],
            "initial_inventory": initial["inventory"], "final_inventory": result["final"]["inventory"],
            "new_iron_plates": 50, "mined": {m["item"]: m["gained"] for m in result["mining"]},
            "steam_power_observed": True, "furnace_position": result["furnace"]["position"],
            "paid_furnaces": 1, "retained_on_repeat": True, "refusals": result["refusals"],
            "execution_ticks": result["final"]["tick"] - initial["tick"],
            "smelting_ticks": result["smelting_ticks"], "walking_distance": result["walking_distance"],
            "trigger_wait_ticks": result["trigger_wait_ticks"],
            "goal_complete": False, "method": result["method"]}
