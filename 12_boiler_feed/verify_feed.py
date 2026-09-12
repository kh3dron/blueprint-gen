"""Verify paid construction, connected delivery, reserves, and useful power output."""
from collections import Counter
import json
from pathlib import Path

from feed_plan import BoilerFeed
from verify_coal import check_sample as check_coal, stock as coal_stock


def indexed(rows):
    result = {e["address"]: e for e in rows}
    if len(result) != len(rows):
        raise ValueError("duplicate entity address")
    return result


def loose_coal(sample):
    result = coal_stock(sample["coal"])
    for e in sample["entities"] + [indexed(sample["power_entities"])["power.boiler"]]:
        result += (e.get("fuel") or {}).get("coal", 0)
        result += sum((lane or {}).get("coal", 0) for lane in e.get("lanes", []))
        if e.get("held"):
            if e["held"]["name"] != "coal":
                raise ValueError("unexpected transported item")
            result += e["held"]["count"]
    return result


def check_connections(sample, design, coal_design, ids=None):
    check_coal(sample["coal"], coal_design)
    found = indexed(sample["entities"])
    specs = indexed(design["placements"])
    if found.keys() != specs.keys():
        raise ValueError("missing feed entity")
    actual_ids = {k:e["id"] for k,e in found.items()}
    if ids is not None and actual_ids != ids:
        raise ValueError("feed entity was replaced")
    for address, e in found.items():
        if any(e[k] != specs[address][k] for k in ("name", "position", "direction")):
            raise ValueError("feed entity drift")
        if e["name"] == "burner-inserter" and not e["active"]:
            raise ValueError("inactive feed inserter")
    belts = [s["address"] for s in design["placements"] if s["name"] == "transport-belt"]
    for a,b in zip(belts, belts[1:]):
        if found[b]["id"] not in found[a]["outputs"]:
            raise ValueError("feed belt path is disconnected")
    chest = indexed(sample["coal"]["entities"])["coal.chest"]
    boiler = indexed(sample["power_entities"])["power.boiler"]
    if chest["id"] != design["source"]["id"] or boiler["id"] != design["consumer"]["id"]:
        raise ValueError("service endpoint identity changed")
    for address, pickup, drop in (("feed.extract", chest["id"], found[belts[0]]["id"]),
                                  ("feed.insert", found[belts[-1]]["id"], boiler["id"])):
        if (found[address].get("pickup_target"), found[address].get("drop_target")) != (pickup,drop):
            raise ValueError("feed inserter endpoints are disconnected")
    return actual_ids


def verify(final, actions, design, coal_design, windows, baseline, opening, reconciliation, events):
    state = final["state"]
    if BoilerFeed.from_state(opening["state"]).document() != design:
        raise ValueError("design does not match observed endpoints")
    waits = [a for a in actions if a["request"]["op"] == "wait_feed"]
    if len(windows) != 5 or len(waits) != 6 or [a["outcome"]["value"] for a in waits[1:]] != windows:
        raise ValueError("five window receipts must match the action ledger after startup")
    baselines = [a for a in actions if a["request"]["op"] == "begin_feed"]
    if len(baselines) != 1 or baselines[0]["outcome"]["value"] != baseline:
        raise ValueError("baseline differs from the action ledger")
    source_ids = {e["address"]:e["id"] for e in opening["state"]["coal"]["entities"]}
    power_ids = {e["address"]:e["id"] for e in opening["state"]["power_entities"]}
    ids, previous, rates, mined, delivered = None, None, [], 0, 0
    for window, action in zip(windows, waits[1:]):
        before, after = window["before"], window["after"]
        for sample in (before,after):
            ids = check_connections(sample, design, coal_design, ids)
            if {e["address"]:e["id"] for e in sample["coal"]["entities"]} != source_ids:
                raise ValueError("source entity replaced")
            if {e["address"]:e["id"] for e in sample["power_entities"]} != power_ids:
                raise ValueError("power entity replaced")
        if previous is not None and before != previous:
            raise ValueError("measurement windows are not contiguous")
        previous = after
        start, finish = before["tick"], after["tick"]
        if (finish-start != 3600 or window["idle_ticks"] != 3600
                or (action["outcome"]["started_tick"], action["outcome"]["finished_tick"]) != (start,finish)):
            raise ValueError("measurement window skipped game time")
        if (not window["player_idle"] or window["inventory_before"] != window["inventory_after"]
                or window["position_before"] != window["position_after"]):
            raise ValueError("player intervened during measurement")
        if any(start < e["tick"] <= finish for e in final["transfers"] + state["player_build_events"] + state["tree_events"] + events):
            raise ValueError("player action during measurement")
        produced = after["coal"]["produced"]-before["coal"]["produced"]
        if produced <= 0 or produced != before["coal"]["deposit_remaining"]-after["coal"]["deposit_remaining"]:
            raise ValueError("coal production does not match deposit depletion")
        mined += produced
        a,b = indexed(before["power_entities"]), indexed(after["power_entities"])
        received = after["delivered"]-before["delivered"]
        burned = after["started_burning"]-before["started_burning"]
        fuel_delta = b["power.boiler"].get("fuel", {}).get("coal",0)-a["power.boiler"].get("fuel",{}).get("coal",0)
        if received < 0 or burned < 0 or received != fuel_delta+burned:
            raise ValueError("boiler fuel meter does not conserve items")
        delivered += received
        consumed = loose_coal(before)+produced-loose_coal(after)
        if consumed < burned:
            raise ValueError("coal buffers contain unaccounted fuel")
        generated = b["power.pole"]["generated_j"]-a["power.pole"]["generated_j"]
        used = b["power.pole"]["lab_consumed_j"]-a["power.pole"]["lab_consumed_j"]
        rates.append(used/60/1000)
        if used < 59_000*60 or generated < 59_000*60 or after["research_progress"]-before["research_progress"] < .196:
            raise ValueError("research load was not sustained for the full window")
    first,last = windows[0]["before"],windows[-1]["after"]
    if loose_coal(last) < loose_coal(first):
        raise ValueError("fuel buffers drained during measurement")
    if delivered <= 0:
        raise ValueError("no new coal reached the boiler under load")
    generated = indexed(last["power_entities"])["power.pole"]["generated_j"]-indexed(baseline["power_entities"])["power.pole"]["generated_j"]
    if generated <= baseline["power_reserve_j"]:
        raise ValueError("original boiler fuel and steam could explain generated power")
    if not state["feed"]["researched"] or "logistics" not in state["researched"]:
        raise ValueError("Logistics research did not complete")
    check_connections(state["feed"], design, coal_design, ids)
    if indexed(state["power_entities"])["power.lab"]["science"]:
        raise ValueError("research packs were not consumed")
    if any(t["tick"] >= baseline["tick"] and t["item"] == "coal" for t in final["transfers"]):
        raise ValueError("player transferred fuel after automatic feed began")
    for key in ("inventory", "cursor_placements", "player_build_events"):
        if reconciliation["before"][key] != reconciliation["after"][key]:
            raise ValueError("repeat deployment changed construction or inventory")
    if reconciliation["drift_before"] != reconciliation["drift_after"]:
        raise ValueError("refused direction drift changed construction")
    refusal = next(a for a in actions if a["request"]["id"] == reconciliation["refusal_id"])
    if refusal["outcome"]["status"] != "failed" or "declarative entity drift" not in refusal["outcome"]["error"]:
        raise ValueError("missing direction drift refusal")
    placements = [p for p in state["cursor_placements"] if p["address"].startswith("feed.")]
    if len(placements) != len(ids):
        raise ValueError("missing paid feed placements")
    for p in placements:
        expected = Counter(p["before"]);expected.subtract({p["name"]:1})
        matching = [e for e in state["player_build_events"] if e["id"] == p["id"]]
        if (+expected != Counter(p["after"]) or p["id"] != ids[p["address"]]
                or len(matching) != 1 or any(matching[0][k] != p[k] for k in ("tick", "name", "position", "player_index"))):
            raise ValueError("feed placement lacks paid inventory or native build event")
    # Reconstruct the continuation from the verified coal checkpoint. Runtime
    # recipes and native craft events establish every item used in the extension.
    inventory, gathered = Counter(opening["state"]["inventory"]), Counter()
    recipes = final["capture"]["resolved_rules"]["recipes"]
    for action in actions:
        req,out = action["request"],action["outcome"]
        if out["started_tick"] < opening["state"]["tick"]:
            continue
        if out["status"] != "done":
            if req["id"] == reconciliation["refusal_id"]:
                continue
            raise ValueError("failed feed continuation action")
        op,args,value = req["op"],req["args"],out["value"]
        if op in ("mine", "harvest_tree"):
            if value["gained"] <= 0 or (op == "mine" and value["gained"] != value["depleted"]):
                raise ValueError("unaccounted gathering")
            inventory[value["item"]] += value["gained"];gathered[value["item"]] += value["gained"]
        elif op in ("smelt", "handcraft"):
            r = recipes[args["recipe"]]
            for p in r["inputs"]: inventory[p["name"]] -= p["amount"]*args["crafts"]
            for p in r["outputs"]: inventory[p["name"]] += p["amount"]*args["crafts"]
            if op == "smelt": inventory["coal"] -= args["coal"]
            else:
                matching = [e for e in events if out["started_tick"] < e["tick"] <= out["finished_tick"]]
                outputs = Counter()
                for e in matching:
                    if e["recipe"] != args["recipe"] or e["player_index"] != placements[0]["player_index"]:
                        raise ValueError("native craft event does not match its job")
                    outputs[e["item"]] += e["count"]
                if len(matching) != args["crafts"] or outputs != Counter({p["name"]:p["amount"]*args["crafts"] for p in r["outputs"]}):
                    raise ValueError("missing native crafting outputs")
        elif op == "place_feed" and value["added"]:
            p = next(p for p in placements if p["address"] == args["spec"]["address"])
            if +inventory != Counter(p["before"]):
                raise ValueError("feed procurement differs from placement inventory")
            inventory[p["name"]] -= 1
        elif op == "start_feed_research": inventory["automation-science-pack"] -= args["packs"]
        if any(n < 0 for n in inventory.values()):
            raise ValueError("feed continuation spent unavailable items")
    if +inventory != Counter(state["inventory"]):
        raise ValueError("final inventory does not conserve the continuation")
    if any(t["count"] != t["removed"] or t["count"] != t["inserted"] for t in final["transfers"]):
        raise ValueError("transfer did not conserve items")
    return {"factorio_version":state["active_mods"]["base"], "automatic_boiler_fuel_observed":True,
            "idle_seconds":300, "lab_kw_by_minute":rates, "coal_mined_during_measurement":mined,
            "coal_delivered_to_boiler_during_measurement":delivered,
            "coal_buffer_gain":loose_coal(last)-loose_coal(first),
            "generated_j_since_connection":generated, "original_power_reserve_j":baseline["power_reserve_j"],
            "native_cursor_builds_added":len(placements), "additional_gathered":dict(gathered),
            "researched":"logistics", "science_packs_consumed":20, "final_inventory":state["inventory"],
            "goal_complete":False, "scope":"automatic coal delivery supporting five minutes of finite research",
            "next_work":"automated ore extraction, smelting, and sustained science assembly"}


def verify_directory(root):
    root=Path(root)
    def read(name): return json.loads((root/name).read_text())
    event_path=root/"user-data/script-output/player-crafts.jsonl"
    if not event_path.exists(): event_path=root/"player-crafts.jsonl"
    events=[json.loads(s) for s in event_path.read_text().splitlines()]
    return verify(read("feed-final-observation.json"),read("actions.json"),read("feed-design.json"),
                  read("coal-design.json"),read("feed-windows.json"),read("feed-baseline.json"),
                  read("coal-final-observation.json"),read("feed-reconciliation.json"),events)
