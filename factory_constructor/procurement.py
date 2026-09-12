"""Refine material requirements into bounded, serialized player operations."""
from copy import deepcopy
import math


def refine(materials, rules, *, gather_limit=100, duration_limit_seconds=240, smelt_input_limit=50):
    """Split procurement before execution and pay for per-batch fuel rounding.

    Handcraft time uses the opening character's crafting speed of one. Smelting
    uses the selected machine's runtime speed and fuel usage. Recipe craft counts
    remain integral, and process ordering preserves all ingredient dependencies.
    ``smelt_input_limit`` is the supported player adapter's per-ingredient furnace
    transfer capacity; it is independent of the duration limit.
    """
    if type(gather_limit) is not int or gather_limit <= 0:
        raise ValueError("gather batch limit must be a positive integer")
    if type(smelt_input_limit) is not int or smelt_input_limit <= 0:
        raise ValueError("smelting input capacity must be a positive integer")
    if (isinstance(duration_limit_seconds, bool) or not isinstance(duration_limit_seconds, (int, float))
            or not math.isfinite(duration_limit_seconds) or duration_limit_seconds <= 0):
        raise ValueError("process batch duration must be positive and finite")
    document = rules.document if hasattr(rules, "document") else rules
    result = deepcopy(materials)
    processes, extra_coal = [], 0
    for original in materials["steps"]:
        kind = original["kind"]
        if kind == "gather":
            continue
        if kind not in {"handcraft", "smelt"}:
            raise ValueError("procurement batching requires gather, handcraft or smelt operations")
        recipe = document["recipes"][original["recipe"]]
        crafts = original["crafts"]
        if isinstance(crafts, bool) or not isinstance(crafts, (int, float)) or int(crafts) != crafts or crafts <= 0:
            raise ValueError("procurement batches require positive integer recipe crafts")
        machine = document["machines"][original["machine"]] if kind == "smelt" else None
        seconds_per_craft = recipe["seconds"] / machine["speed"] if machine else recipe["seconds"]
        if not math.isfinite(seconds_per_craft) or seconds_per_craft <= 0:
            raise ValueError("procurement recipe duration must be positive and finite")
        limit = math.floor(duration_limit_seconds / seconds_per_craft)
        if limit < 1:
            raise ValueError("one recipe craft exceeds the player process duration limit: " + original["recipe"])
        if kind == "smelt":
            limit = min(limit, *(math.floor(smelt_input_limit/quantity) for quantity in recipe["inputs"].values()))
            if limit < 1:
                raise ValueError("one recipe craft exceeds the player smelting input capacity: " + original["recipe"])
        remaining, coal_total = int(crafts), 0
        while remaining:
            count = min(remaining, limit)
            batch = deepcopy(original)
            seconds = count * seconds_per_craft
            batch.update(crafts=count,
                inputs={item: quantity*count for item, quantity in recipe["inputs"].items()},
                outputs={item: quantity*count for item, quantity in recipe["outputs"].items()})
            if kind == "smelt":
                coal = math.ceil(machine["fuel_kw"] * seconds / document["fuel_kj"]["coal"])
                batch.update(coal=coal, processing_seconds=seconds)
                coal_total += coal
            else:
                batch["crafting_seconds"] = seconds
            processes.append(batch)
            remaining -= count
        if kind == "smelt":
            delta = coal_total-original["coal"]
            if delta < 0:
                raise ValueError("procurement bill fuel differs from the current runtime rules")
            extra_coal += delta
    if extra_coal:
        result["gather"]["coal"] = result["gather"].get("coal", 0)+extra_coal
    gathers = []
    for item, quantity in sorted(result["gather"].items(), key=lambda pair: (pair[0] != "coal", pair[0])):
        if isinstance(quantity, bool) or not isinstance(quantity, (int, float)) or int(quantity) != quantity or quantity < 0:
            raise ValueError("procurement gathering requires nonnegative integer quantities")
        remaining = int(quantity)
        while remaining:
            count = min(remaining, gather_limit)
            gathers.append({"kind": "gather", "item": item, "quantity": count})
            remaining -= count
    result.update(gather_batches=gathers, steps=gathers+processes,
                  handcraft_seconds=sum(p["crafting_seconds"] for p in processes if p["kind"] == "handcraft"),
                  smelting_machine_seconds=sum(p["processing_seconds"] for p in processes if p["kind"] == "smelt"),
                  refinement={"gather_limit": gather_limit, "duration_limit_seconds": duration_limit_seconds,
                              "smelt_input_limit": smelt_input_limit, "additional_coal": extra_coal})
    return result
