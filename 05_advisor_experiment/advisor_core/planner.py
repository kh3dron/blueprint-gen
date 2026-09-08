"""Read-only next steps for the opening, with explicit scope boundaries."""
from collections import defaultdict
import math

from .construction import bill
from .production import analyze, completion, operational_labs


EPS = 1e-7


def requirements(snapshot, rules):
    """Expand single-product opening recipes, sharing external supply across all goals.

    The LP handles coproducts, but constructing a new coproduct/cyclic factory is
    intentionally outside this first planning policy instead of silently choosing
    an inconsistent tree expansion.
    """
    remaining_supply = dict(snapshot.document["supplies_per_s"])
    crafts, raw = defaultdict(float), defaultdict(float)

    def expand(item, rate, path=()):
        covered = min(remaining_supply.get(item, 0), rate)
        remaining_supply[item] = remaining_supply.get(item, 0) - covered
        rate -= covered
        if rate <= EPS:
            return
        if item in path:
            raise ValueError(f"construction planning for cycle {item!r} is not implemented")
        recipe = rules.recipe_for(item, snapshot.document["selected_recipes"])
        if recipe is None:
            if item not in rules.document["raw_items"]:
                raise ValueError(f"no supported construction route for {item!r} in this small ruleset")
            raw[item] += rate
            return
        r = rules.recipes[recipe]
        if len(r["outputs"]) != 1:
            raise ValueError(f"coproduct flow analysis is supported; construction planning for {recipe!r} is not yet")
        machine = rules.machine_for(recipe)
        activity = rate / r["outputs"][item]
        crafts[recipe] += activity
        for ingredient, amount in rules.craft_inputs(recipe, machine).items():
            expand(ingredient, activity * amount, path + (item,))

    for item, rate in snapshot.goals.items():
        expand(item, rate)
    return dict(crafts), dict(raw)


def next_step(snapshot, rules):
    d = snapshot.document
    analysis = analyze(snapshot, rules)
    verified = completion(snapshot, rules, analysis)

    def action(kind, title, why, check, **extra):
        return {"kind": kind, "title": title, "why": why, "completion_check": check,
                "snapshot_revision": d["revision"], "snapshot_tick": d["tick"],
                "changes_snapshot": False, **extra}

    def research(name):
        t = rules.technologies[name]
        trigger = t.get("trigger")
        if trigger:
            if trigger["type"] != "craft-item":
                return action("trigger", f"Complete the {name} trigger", str(trigger),
                              f"A fresh snapshot lists {name} in researched.", trigger=trigger)
            item = trigger["item"]
            needed = max(0, trigger.get("count", 1) - d["crafted"].get(item, 0))
            if not needed:
                return action("observe", f"Check whether {name} unlocked",
                              "The recorded crafting counter meets its trigger; research is not yet observed.",
                              f"Import the game's actual research state; do not infer that {name} is complete.")
            return action("trigger", f"Produce {needed:g} additional {item} for {name}",
                          "This technology is unlocked by crafting, before the target factory can be built.",
                          f"Observe {name} researched; existing inventory alone does not satisfy a crafting trigger.",
                          technology=name, construction=bill(snapshot, rules, {item: needed}, force_craft=True))
        if not operational_labs(snapshot, rules):
            existing = any(m["prototype"] == "lab" and m["built"] for m in snapshot.machines)
            requested = {} if existing else {"lab": 1}
            return action("prepare_lab", f"Prepare a powered lab for {name}",
                          "Science packs need a built lab connected to available electricity.",
                          "Observe a built, connected, powered lab and sufficient electricity in a new snapshot.",
                          construction=bill(snapshot, rules, requested), requires_power_kw=rules.machines["lab"]["electric_kw"],
                          placement_pending=True)
        lab_kw = operational_labs(snapshot, rules) * rules.machines["lab"]["electric_kw"]
        if d["power"]["available_kw"] < lab_kw:
            return action("power", f"Restore lab power before researching {name}",
                          "The lab's recorded powered flag is inconsistent with the available power budget.",
                          f"Observe at least {lab_kw:g} kW available for the labs, plus the rest of the active factory.")
        completed = d.get("research_units_completed", {}).get(name, 0)
        remaining = max(0, t["count"] - completed)
        if not remaining:
            return action("observe", f"Check whether {name} finished", "All research units are recorded.",
                          f"Observe {name} in the actual researched technology list.")
        packs = {p: q * remaining for p, q in t["packs"].items()}
        return action("research", f"Research {name}: {remaining:g} units remaining",
                      "Its prerequisites are observed and a powered lab is present.",
                      f"Load the listed science into the lab and observe {name} researched.",
                      technology=name, science_required=packs,
                      lab_seconds=remaining * t["seconds"] / (operational_labs(snapshot, rules) * rules.machines["lab"]["speed"]),
                      construction=bill(snapshot, rules, packs))

    if d.get("observation_gaps"):
        return action("observe", "Resolve the missing observations before planning a change",
                      "The game export does not yet establish all inputs needed for a reliable recommendation.",
                      "Confirm the listed facts for this capture and import it with the completed review.",
                      observation_gaps=d["observation_gaps"])
    if verified["complete"]:
        return action("done", "The configured production milestone is observed",
                      "A fresh automated-production window meets every goal and the flow bound supports it.",
                      "Continue observing; changing the factory or losing supply can invalidate this milestone.",
                      measured_per_min=verified["measured_per_min"])

    # Research the goal recipe first, including actual trigger/bootstrap work.
    for item in snapshot.goals:
        recipe = rules.recipe_for(item, d["selected_recipes"])
        if recipe and not rules.unlocked(recipe, snapshot.researched):
            return research(rules.unlock_path(recipe, snapshot.researched)[0])
    try:
        crafts, raw = requirements(snapshot, rules)
    except ValueError as error:
        if analysis["goal_fraction"] >= 1 - EPS:
            return action("verify", "Measure the installed factory's output", str(error),
                          "Record a fresh automated-production window; this planner cannot yet construct this process.",
                          remaining_checks=verified["reasons"])
        return action("unsupported", "This target needs a new planning method", str(error),
                      "Add a supported construction method or provide an observed installed factory for flow analysis.")

    for recipe in crafts:
        for required in (recipe, rules.machine_for(recipe)):
            if not rules.unlocked(required, snapshot.researched):
                return research(rules.unlock_path(required, snapshot.researched)[0])

    relevant = set(crafts)
    for disabled in analysis["disabled"]:
        machine = next(m for m in snapshot.machines if m["id"] == disabled["machine_id"])
        if machine["recipe"] not in relevant or disabled["reason"] == "ghost":
            continue
        return action("repair", f"Restore {machine['id']}: {disabled['reason']}",
                      "Existing hardware cannot contribute until this observed problem is resolved.",
                      "Observe the repaired connection, power or output path, then measure production again.",
                      machine_id=machine["id"], position=machine.get("position"))

    if analysis["goal_fraction"] < 1 - EPS:
        # Supply requests are absolute boundary targets, not repeated additions.
        if raw:
            item = next(iter(raw))
            target = (d["supplies_per_s"].get(item, 0) + raw[item]) * 60
            return action("supply", f"Establish {item} delivery of at least {target:.4g}/min",
                          "Installed production cannot create this missing input; inventory is only a finite buffer.",
                          "Measure net delivery at the factory input and update supplies_per_s in a fresh snapshot.",
                          item=item, target_per_min=target, additional_per_min=raw[item] * 60,
                          extraction_plan_pending=True)
        # Walk leaves first so producers are installed before their consumers.
        for recipe, needed in reversed(list(crafts.items())):
            r = rules.recipes[recipe]
            existing = [m for m in snapshot.machines if m.get("recipe") == recipe and m["built"]]
            capacity = sum(m.get("count", 1) * rules.machines[m["prototype"]]["speed"] / r["seconds"]
                           for m in existing)
            if capacity < needed - EPS:
                machine = rules.machine_for(recipe)
                count = math.ceil((needed - capacity - EPS) * r["seconds"] / rules.machines[machine]["speed"])
                return action("build", f"Install {count} additional {machine} for {recipe}",
                              f"The required {needed:.4g} crafts/s exceeds installed capacity {capacity:.4g} crafts/s.",
                              "Observe these machines built with the named recipe, connected inputs, fuel/power and open outputs.",
                              recipe=recipe, prototype=machine, count=count,
                              construction=bill(snapshot, rules, {machine: count}),
                              placement_pending=True)
        ideal_kw = 0.0
        for recipe, activity in crafts.items():
            # Use the installed tiers' actual energy per craft. The starter-tier
            # estimate can understate demand after a machine upgrade.
            choices = []
            for machine in snapshot.machines:
                if machine.get("recipe") == recipe and machine["built"]:
                    prototype = rules.machines[machine["prototype"]]
                    time = rules.recipes[recipe]["seconds"] / prototype["speed"]
                    choices.append((prototype["electric_kw"] * time, machine.get("count", 1) / time))
            remaining = activity
            for kj, capacity in sorted(choices):
                allocated = min(remaining, capacity)
                ideal_kw += allocated * kj
                remaining -= allocated
        ideal_kw += max(operational_labs(snapshot, rules), int(d["require_lab"])) * rules.machines["lab"]["electric_kw"]
        if d["power"]["available_kw"] < ideal_kw - EPS:
            return action("power", f"Provide at least {ideal_kw:.4g} kW for the modeled active load",
                          "The material and machine capacities are sufficient but the power budget limits output.",
                          "Observe available power above this lower bound, including extra load from inserters and idle drain.",
                          active_load_lower_bound_kw=ideal_kw, placement_pending=True)
        return action("inspect", "Inspect the remaining production constraint",
                      "The flow bound is below the goal; this opening policy has no justified build or supply fix.",
                      "Inspect the flow report and collect machine/input status before changing the factory.")

    if d["require_lab"] and not operational_labs(snapshot, rules):
        existing = any(m["prototype"] == "lab" and m["built"] for m in snapshot.machines)
        return action("prepare_lab", "Build or reconnect the milestone's lab",
                      "Production is feasible, but this milestone also requires an observed powered lab.",
                      "Observe a built, connected, powered lab with sufficient power.",
                      construction=bill(snapshot, rules, {} if existing else {"lab": 1}),
                      placement_pending=True)
    if analysis["lab_power_shortfall_kw"] > EPS or (d["power"].get("required", True) and d["power"]["available_kw"] <= 0):
        return action("power", "Restore the milestone's electricity supply",
                      "The observed power budget does not meet the milestone's power/lab conditions.",
                      "Observe available electricity sufficient for the powered labs and active factory.")
    return action("verify", f"Measure automated production for {d['goal_window_seconds']:g} seconds",
                  "The flow bound supports the target; a prediction does not establish in-game output.",
                  "Import fresh production counts from this factory revision; exclude handcrafting and old buffers.",
                  remaining_checks=verified["reasons"])
