"""A material/power feasibility bound over observed fixed hardware.

This deliberately does not claim to simulate inserters, paths, buffers or fluids.
Excess products may leave the modeled system; actual output handling is checked
by observation, and a blocked output disables its complete recipe activity.
"""
from .linear import maximize


EPS = 1e-7


def activity_limit(machine, snapshot, rules):
    prototype = rules.machines[machine["prototype"]]
    recipe = machine.get("recipe")
    if not recipe:
        return 0.0, None
    if machine["built"] and not machine.get("active", True):
        return 0.0, "inactive"
    if machine.get("status") == "no_fuel":
        return 0.0, "out of fuel"
    for field, reason in (("built", "ghost"), ("connected", "disconnected"), ("output_open", "output blocked")):
        if not machine[field]:
            return 0.0, reason
    if prototype["electric_kw"] and not machine["powered"]:
        return 0.0, "unpowered"
    if not rules.unlocked(recipe, snapshot.researched):
        return 0.0, f"recipe locked: {recipe}"
    if not rules.unlocked(machine["prototype"], snapshot.researched):
        return 0.0, f"machine locked: {machine['prototype']}"
    return machine.get("count", 1) * prototype["speed"] / rules.recipes[recipe]["seconds"], None


def operational_labs(snapshot, rules):
    return sum(m.get("count", 1) for m in snapshot.machines if m["prototype"] == "lab"
               and all(m[k] for k in ("built", "connected", "powered", "output_open"))
               and m.get("active", True)
               and rules.unlocked("lab", snapshot.researched))


def analyze(snapshot, rules):
    d = snapshot.document
    machines = [m for m in snapshot.machines if m.get("recipe")]
    n = len(machines)
    inputs = [rules.craft_inputs(m["recipe"], m["prototype"]) for m in machines]
    outputs = [rules.recipes[m["recipe"]]["outputs"] for m in machines]
    supplies = d["supplies_per_s"]
    goals = snapshot.goals
    items = sorted(set(goals) | set(supplies) | {i for table in inputs + outputs for i in table})
    # Last variable is the common fraction of *all* requested goal rates, capped at 1.
    rows, rhs = [], []
    for item in items:
        rows.append([a.get(item, 0) - b.get(item, 0) for a, b in zip(inputs, outputs)] + [goals.get(item, 0)])
        rhs.append(supplies.get(item, 0))
    disabled, nominal = [], {}
    for i, machine in enumerate(machines):
        limit, reason = activity_limit(machine, snapshot, rules)
        nominal[machine["id"]] = limit
        rows.append([float(i == j) for j in range(n)] + [0.0])
        rhs.append(limit)
        if reason:
            disabled.append({"machine_id": machine["id"], "reason": reason})
    lab_kw = operational_labs(snapshot, rules) * rules.machines["lab"]["electric_kw"]
    craft_kj = [rules.machines[m["prototype"]]["electric_kw"] * rules.recipes[m["recipe"]]["seconds"]
                / rules.machines[m["prototype"]]["speed"] for m in machines]
    rows.append(craft_kj + [0.0])
    rhs.append(max(0, d["power"]["available_kw"] - lab_kw))
    rows.append([0.0] * n + [1.0])
    rhs.append(1.0)
    solution = maximize([0.0] * n + [1.0], rows, rhs)
    fraction = min(1.0, max(0.0, solution[-1]))
    production, consumption = {}, {}
    for i, activity in enumerate(solution[:-1]):
        for item, amount in outputs[i].items():
            production[item] = production.get(item, 0) + amount * activity
        for item, amount in inputs[i].items():
            consumption[item] = consumption.get(item, 0) + amount * activity
    net = {item: supplies.get(item, 0) + production.get(item, 0) - consumption.get(item, 0) for item in items}
    return {
        "kind": "optimistic_flow_bound",
        "goal_fraction": fraction,
        "goal_delivery_per_min": {item: value * fraction * 60 for item, value in goals.items()},
        "crafts_per_s": {m["id"]: solution[i] for i, m in enumerate(machines)},
        "activity_limits_per_s": nominal,
        "production_per_s": production,
        "consumption_per_s": consumption,
        "net_per_s": net,
        "electric_kw": lab_kw + sum(kj * x for kj, x in zip(craft_kj, solution)),
        "lab_kw": lab_kw,
        "lab_power_shortfall_kw": max(0, lab_kw - d["power"]["available_kw"]),
        "disabled": disabled,
        "assumptions": [
            "Supplies are net delivery rates at the modeled factory boundary; finite inventory is excluded.",
            "Connected production shares one material pool and one electric network.",
            "Surplus outputs can leave the system; transport, inserter rates and fluid behavior are not simulated.",
            "Electricity uses active crafting load plus powered labs; idle drain is omitted.",
        ],
    }


def completion(snapshot, rules, analysis=None):
    analysis = analysis or analyze(snapshot, rules)
    d = snapshot.document
    reasons = list(d.get("observation_gaps", []))
    if analysis["goal_fraction"] < 1 - EPS:
        reasons.append("current hardware, supply and power cannot sustain every requested rate")
    if analysis["lab_power_shortfall_kw"] > EPS:
        reasons.append("available power does not cover the recorded powered labs")
    if d["require_lab"] and not operational_labs(snapshot, rules):
        reasons.append("no built, connected, powered lab is observed")
    if d["power"].get("required", True) and d["power"]["available_kw"] <= 0:
        reasons.append("no available electricity is observed")
    eligible = [o for o in d["observations"] if o.get("revision") == d["revision"]
                and o.get("source") == "automated"
                and (o["end_tick"] - o["start_tick"]) / 60 >= d["goal_window_seconds"]
                and (d["tick"] - o["end_tick"]) / 60 <= d["max_observation_age_seconds"]]
    latest = max(eligible, key=lambda o: o["end_tick"], default=None)
    measured = {}
    if latest is None:
        reasons.append("no fresh automated-production measurement covers the goal window for this revision")
    else:
        minutes = (latest["end_tick"] - latest["start_tick"]) / 3600
        measured = {item: latest.get("produced", {}).get(item, 0) / minutes for item in snapshot.goals}
        for item, target in d["goals_per_min"].items():
            if measured[item] < target - EPS:
                reasons.append(f"measured {item} is {measured[item]:g}/min, below {target:g}/min")
    return {"complete": not reasons, "reasons": reasons, "measured_per_min": measured,
            "window_seconds": d["goal_window_seconds"]}
