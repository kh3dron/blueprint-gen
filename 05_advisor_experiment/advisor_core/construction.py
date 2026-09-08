"""Finite-inventory procurement for the opening's handcrafting and stone smelting.

Batch rounding and surplus are accounted for across the whole bill. This is a
checklist, not an execution engine; its hypothetical stock is never a snapshot.
"""
from collections import defaultdict
import math


def bill(snapshot, rules, requested, *, force_craft=False):
    stock = dict(snapshot.document["inventory"])
    used, gathered = defaultdict(int), defaultdict(int)
    initial = dict(stock)
    steps, locks, unsupported = [], set(), []
    stations = {m["prototype"] for m in snapshot.machines if m["built"]}
    hand_seconds = 0.0
    process_seconds = 0.0

    def take(item, amount):
        available = min(stock.get(item, 0), amount)
        stock[item] = stock.get(item, 0) - available
        from_initial = min(initial.get(item, 0), available)
        initial[item] = initial.get(item, 0) - from_initial
        used[item] += from_initial
        return amount - available

    def ensure(item, amount, path=(), force=False):
        nonlocal hand_seconds, process_seconds
        if item not in rules.items or amount <= 0 or int(amount) != amount:
            raise ValueError(f"construction requests require a known item and positive integer count: {item}={amount}")
        missing = amount if force else take(item, amount)
        if missing == 0:
            return
        if item in path:
            raise ValueError(f"construction recipe cycle at {item}; starting catalysts require a separate plan")
        recipe = rules.recipe_for(item, snapshot.document["selected_recipes"])
        if recipe is None:
            gathered[item] += missing
            action = "gather" if item in rules.document["hand_collectable"] else "supply"
            steps.append({"kind": action, "item": item, "quantity": missing})
            return
        r = rules.recipes[recipe]
        if not rules.unlocked(recipe, snapshot.researched):
            locks.update(rules.unlock_path(recipe, snapshot.researched))
        if r["category"] not in ("crafting", "smelting") or any(
            rules.document["items"][i] == "fluid" for i in r["inputs"]
        ):
            unsupported.append(f"construction of {item} via {recipe} needs an unsupported process")
            return
        if item in r["inputs"]:
            raise ValueError(f"construction of {item} requires starting catalyst inventory")
        count = math.ceil(missing / r["outputs"][item])
        for ingredient, quantity in r["inputs"].items():
            ensure(ingredient, count * quantity, path + (item,))
        if r["category"] == "smelting":
            station = "stone-furnace"
            if station not in stations:
                ensure(station, 1, path + (item,))
                stations.add(station)
                steps.append({"kind": "place", "item": station, "quantity": 1,
                              "check": "Place on clear ground within reach; record its position before loading."})
            seconds = count * r["seconds"] / rules.machines[station]["speed"]
            fuel = math.ceil(rules.machines[station]["fuel_kw"] * seconds / rules.document["fuel_kj"]["coal"])
            ensure("coal", fuel, path + (item,))
            process_seconds += seconds
            step = {"kind": "smelt", "recipe": recipe, "crafts": count, "machine": station,
                    "coal": fuel, "processing_seconds": seconds}
        else:
            seconds = count * r["seconds"]
            hand_seconds += seconds
            step = {"kind": "handcraft", "recipe": recipe, "crafts": count, "crafting_seconds": seconds}
        step["inputs"] = {i: q * count for i, q in r["inputs"].items()}
        step["outputs"] = {i: q * count for i, q in r["outputs"].items()}
        if not rules.unlocked(recipe, snapshot.researched):
            step["requires_research"] = rules.unlock_path(recipe, snapshot.researched)
        steps.append(step)
        for product, quantity in r["outputs"].items():
            stock[product] = stock.get(product, 0) + count * quantity
        # Requested outputs are reserved for their parent job, not reusable inventory.
        if stock.get(item, 0) < missing:
            raise ValueError(f"recipe {recipe} does not cover its construction request")
        stock[item] -= missing

    for item, quantity in requested.items():
        ensure(item, quantity, force=force_craft)
    return {
        "requested": requested,
        "force_new_crafts": force_craft,
        "inventory_used": {i: q for i, q in used.items() if q},
        "gather": dict(gathered),
        "steps": steps,
        "requires_research": sorted(locks),
        "unsupported": unsupported,
        "remaining_inventory": {i: q for i, q in stock.items() if q},
        "handcraft_seconds": hand_seconds,
        "smelting_machine_seconds": process_seconds,
        "note": "Times exclude gathering, movement, placement and transfers; furnace time may overlap handcrafting.",
    }
