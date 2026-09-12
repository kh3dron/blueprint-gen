"""Verify bounded delivery, actual fuel return, and paid native construction."""
from collections import Counter
import json
from pathlib import Path


def entities(sample):
    return {e["address"]: e for e in sample["entities"]}


def stock(sample):
    count = 0
    for e in sample["entities"]:
        count += (e.get("fuel") or {}).get("coal", 0) + (e.get("contents") or {}).get("coal", 0)
        if e.get("held") and e["held"]["name"] == "coal":
            count += e["held"]["count"]
        count += sum((lane or {}).get("coal", 0) for lane in e.get("lanes", []))
    if count != sample["loose_coal"]:
        raise ValueError("coal inventory aggregate differs from observed buffers")
    return count


def check_sample(sample, design, ids=None, *, connected=True):
    found = entities(sample)
    specs = {s["address"]: s for s in design["placements"]}
    if len(found) != len(sample["entities"]) or found.keys() != specs.keys():
        raise ValueError("missing or duplicate coal entities")
    for address, spec in specs.items():
        e = found[address]
        if (any(e[k] != spec[k] for k in ("name", "position", "direction"))
                or (e["name"] in ("burner-mining-drill", "burner-inserter") and not e["active"])):
            raise ValueError("coal entity drift")
        if ids is not None and e["id"] != ids[address]:
            raise ValueError("coal entity was replaced")
    if sample["deposit_remaining"] != sum(r["amount"] for r in sample["deposits"]):
        raise ValueError("coal deposit accounting differs")
    if any(r["amount"] <= 0 for r in sample["deposits"]) or len(sample["deposits"]) != 4:
        raise ValueError("coal deposit exhausted or missing")
    stock(sample)
    result = {address: e["id"] for address, e in found.items()}
    # An unpowered, newly placed drill does not resolve its drop target until
    # normal simulation runs. Verify those endpoints after startup.
    if not connected:
        return result
    if found["coal.drill"].get("drop_target") != found["coal.belt.0"]["id"]:
        raise ValueError("drill output does not feed its belt")
    for i in range(6):
        if found[f"coal.belt.{i+1}"]["id"] not in found[f"coal.belt.{i}"]["outputs"]:
            raise ValueError("coal belt path is disconnected")
    for address, pickup, drop in (("coal.refuel", "coal.belt.4", "coal.drill"),
                                  ("coal.export", "coal.belt.6", "coal.chest")):
        e = found[address]
        if e.get("pickup_target") != found[pickup]["id"] or e.get("drop_target") != found[drop]["id"]:
            raise ValueError("coal inserter endpoints are disconnected")
    return result


def verify(final, actions, design, windows, reconciliation, warmup, opening, craft_events):
    state = final["state"]
    seed = state["coal_seed"]
    if seed["coal"] != 3 or stock(seed["before"]) != 0 or stock(seed["after"]) != 3:
        raise ValueError("seed coal was not exactly three items into an empty loop")
    ids = check_sample(seed["after"], design, connected=False)
    if len(windows) != design["measurement"]["windows"] or len(windows) < 5:
        raise ValueError("need five complete idle windows")
    rates, mined = [], 0
    previous = None
    wait_actions = [a for a in actions if a["request"]["op"] == "wait_coal"]
    if [a["outcome"]["value"] for a in wait_actions] != [warmup, *windows]:
        raise ValueError("window receipts differ from the action ledger")
    for i, (window, action) in enumerate(zip([warmup, *windows], wait_actions)):
        before, after = window["before"], window["after"]
        check_sample(before, design, ids, connected=i>0)
        check_sample(after, design, ids)
        if previous is not None and previous != before:
            raise ValueError("idle measurement windows are not contiguous")
        previous = after
        ticks = after["tick"]-before["tick"]
        if ticks != window["idle_ticks"] or ticks != design["measurement"]["window_ticks"]:
            raise ValueError("idle window skipped game time")
        if (not window["player_idle"] or window["inventory_before"] != window["inventory_after"]
                or window["position_before"] != window["position_after"]):
            raise ValueError("player intervened during measurement")
        start, finish = action["outcome"]["started_tick"], action["outcome"]["finished_tick"]
        if (start, finish) != (before["tick"], after["tick"]):
            raise ValueError("action and window ticks differ")
        if any(start < t["tick"] <= finish for t in final["transfers"]):
            raise ValueError("inventory transfer during the idle window")
        if any(start < e["tick"] <= finish for e in state["player_build_events"] + state["tree_events"]):
            raise ValueError("player action during the idle window")
        produced = after["produced"]-before["produced"]
        if produced != before["deposit_remaining"]-after["deposit_remaining"] or produced <= 0:
            raise ValueError("production does not match coal deposit depletion")
        if i > 0:
            mined += produced
        delivered = ((entities(after)["coal.chest"].get("contents") or {}).get("coal", 0))
        delivered -= ((entities(before)["coal.chest"].get("contents") or {}).get("coal", 0))
        rate = delivered*3600/ticks
        if i > 0:
            rates.append(rate)
        if i > 0 and rate < design["output"]["minimum_per_min"]:
            raise ValueError("coal delivery fell below the required rate")
    last = windows[-1]["after"]
    if state["coal"] != last:
        raise ValueError("final observation does not match the last idle window")
    # Whole items disappear only when burners start consuming them. Count all
    # lanes, held stacks, fuel inventories and the output chest independently.
    consumed_items = stock(seed["after"]) + last["produced"]-seed["after"]["produced"] - stock(last)
    if consumed_items <= seed["coal"]:
        raise ValueError("seed fuel alone could explain this run")
    # A conservative bound from runtime drill consumption and all seed energy,
    # including the game's native initial wood in the two burner inserters.
    initial_energy = seed["coal"]*last["coal_fuel_value_j"] + sum(e.get("burning_j", 0) for e in seed["before"]["entities"])
    drill = entities(last)["coal.drill"]
    seed_seconds = initial_energy / (drill["energy_usage_j_per_tick"]*60)
    seconds = (last["tick"]-seed["tick"])/60
    if seconds <= seed_seconds or drill["burning_j"] <= 0:
        raise ValueError("no operating drill beyond the total seed-energy bound")
    placements = [p for p in state["cursor_placements"] if p["address"].startswith("coal.")]
    if len(placements) != len(ids):
        raise ValueError("missing paid cursor construction")
    for p in placements:
        before = Counter(p["before"]); before.subtract({p["name"]: 1})
        if +before != Counter(p["after"]) or p["id"] != ids[p["address"]]:
            raise ValueError("cursor debit or entity identity differs")
        events = [e for e in state["player_build_events"] if e["id"] == p["id"]]
        if len(events) != 1 or any(events[0][k] != p[k] for k in ("tick", "id", "name", "position", "player_index")):
            raise ValueError("cursor build lacks its native event")
    for k in ("inventory", "cursor_placements", "player_build_events"):
        if reconciliation["before"][k] != reconciliation["after"][k]:
            raise ValueError("repeat deployment changed construction or items")
    if reconciliation["drift_before"] != reconciliation["drift_after"]:
        raise ValueError("refused drift changed construction or items")
    refusal = next(a for a in actions if a["request"]["id"] == reconciliation["refusal_id"])
    if refusal["outcome"]["status"] != "failed" or "declarative entity drift" not in refusal["outcome"]["error"]:
        raise ValueError("missing direction drift refusal")
    trees = [a for a in actions if a["request"]["op"] == "harvest_tree"]
    if not trees or len(trees) != len(state["tree_events"]):
        raise ValueError("missing native tree harvest")
    for job, event in zip(trees, state["tree_events"]):
        value = job["outcome"]["value"]
        if (value["id"] != event["id"] or value["gained"] != event["products"].get("wood")
                or not value["removed"] or not job["outcome"]["started_tick"] < event["tick"] <= job["outcome"]["finished_tick"]):
            raise ValueError("tree yield does not match the native mining event")
    # Reconstruct every new player item from the verified powered-lab checkpoint.
    # Native recipe exports determine costs, including batches and surplus belts.
    inventory = Counter(opening["state"]["inventory"])
    gathered, smelted, crafts = Counter(), Counter(), Counter()
    start_tick = opening["state"]["tick"]
    recipes = final["capture"]["resolved_rules"]["recipes"]
    for action in actions:
        req, out = action["request"], action["outcome"]
        if out["started_tick"] < start_tick:
            continue
        if out["status"] != "done":
            if req["id"] == reconciliation["refusal_id"]:
                continue
            raise ValueError("unexpected failed continuation action")
        op, args, value = req["op"], req["args"], out["value"]
        if op in ("mine", "harvest_tree"):
            if value["gained"] <= 0 or (op == "mine" and value["gained"] != value["depleted"]):
                raise ValueError("gathering does not conserve resources")
            inventory[value["item"]] += value["gained"]
            gathered[value["item"]] += value["gained"]
        elif op in ("smelt", "handcraft"):
            recipe = recipes[args["recipe"]]
            for p in recipe["inputs"]:
                inventory[p["name"]] -= p["amount"]*args["crafts"]
            for p in recipe["outputs"]:
                inventory[p["name"]] += p["amount"]*args["crafts"]
            if op == "smelt":
                inventory["coal"] -= args["coal"]
                smelted.update(value["outputs"])
            else:
                crafts[args["recipe"]] += args["crafts"]
                matching = [e for e in craft_events if out["started_tick"] < e["tick"] <= out["finished_tick"]]
                actual = Counter()
                for event in matching:
                    if event["recipe"] != args["recipe"] or event["player_index"] != placements[0]["player_index"]:
                        raise ValueError("native crafting event does not match its job")
                    actual[event["item"]] += event["count"]
                expected = Counter({p["name"]: p["amount"]*args["crafts"] for p in recipe["outputs"]})
                if len(matching) != args["crafts"] or actual != expected:
                    raise ValueError("native crafting outputs differ from runtime recipe")
        elif op == "place_coal" and value["added"]:
            receipt = next(p for p in placements if p["address"] == args["spec"]["address"])
            if +inventory != Counter(receipt["before"]):
                raise ValueError("construction inventory differs from paid procurement")
            inventory[args["spec"]["name"]] -= 1
        elif op == "seed_coal":
            inventory["coal"] -= seed["coal"]
        if any(n < 0 for n in inventory.values()):
            raise ValueError("continuation spent unavailable inventory")
    if +inventory != Counter(state["inventory"]):
        raise ValueError("final player inventory does not conserve the continuation")
    for transfer in final["transfers"]:
        if transfer["count"] != transfer["removed"] or transfer["count"] != transfer["inserted"]:
            raise ValueError("inventory transfer did not conserve items")
    return {"factorio_version": state["active_mods"]["base"], "seed_coal": 3,
            "additional_gathered": dict(gathered), "additional_smelted": dict(smelted),
            "native_handcraft_batches_added": sum(crafts.values()), "final_inventory": state["inventory"],
            "native_cursor_builds_added": len(placements), "wood_harvested": sum(t["outcome"]["value"]["gained"] for t in trees),
            "idle_seconds": sum(w["idle_ticks"] for w in windows)/60,
            "startup_seconds": warmup["idle_ticks"]/60,
            "startup_chest_coal": (entities(warmup["after"])["coal.chest"].get("contents") or {}).get("coal", 0),
            "delivered_per_minute": rates, "minimum_observed_per_min": min(rates),
            "coal_mined_while_idle": mined, "chest_coal": entities(last)["coal.chest"]["contents"]["coal"],
            "coal_items_started_burning": consumed_items, "total_seed_energy_drill_seconds_bound": seed_seconds,
            "deposit_remaining": last["deposit_remaining"], "player_interventions_during_measurement": 0,
            "self_fueling_observed": True, "repeat_deployment_retained": True, "direction_drift_refused": True,
            "goal_complete": False, "scope": "five measured minutes of net coal delivery into finite storage",
            "next_work": "route coal to boiler and ore smelters; automate ore and science production"}


def verify_directory(root):
    root = Path(root)
    def read(name): return json.loads((root / name).read_text())
    events = [json.loads(s) for s in (root / "user-data/script-output/player-crafts.jsonl").read_text().splitlines()]
    return verify(read("coal-final-observation.json"), read("actions.json"), read("coal-design.json"),
                  read("coal-windows.json"), read("coal-reconciliation.json"), read("coal-warmup.json"),
                  read("final-observation.json"), events)
