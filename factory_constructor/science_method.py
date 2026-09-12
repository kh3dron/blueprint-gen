"""Lower a red-science recipe graph into paid, observed player capabilities."""
from collections import Counter
from copy import deepcopy

from .deployment import refresh, placements
from .legacy import bill
from .production_graph import production_graph
from .procurement import refine
from .science_layout import layout


class ScienceMethod:
    output = "automation-science-pack"
    source = "factory_constructor.science_method:ScienceMethod/v1"

    def lower(self, goal, observation, snapshot, rules, builder, *, deployment=None):
        if not deployment or deployment["service"]["item"] != "iron-plate":
            raise ValueError("science construction needs a verified iron deployment checkpoint")
        retained = refresh(deployment, observation)
        graph = production_graph(goal, rules, snapshot.researched,
            available={"iron-plate": deployment["service"]["minimum_per_minute"]},
            machine_metadata=observation["capture"]["resolved_rules"]["machines"])
        design = layout(observation, deployment, rules, goal.per_minute)
        design["measurement"]["stabilization"] = {"minimum_windows": 5, "maximum_windows": 30, "stable_windows": 3}
        design["retained_placements"] = deepcopy(placements(deployment["design"]))
        for item, count in design["counts"]["selected"].items():
            if graph["nodes"][item]["count"] != count:
                raise ValueError("recipe graph and machine layout disagree: " + item)
        added = design["placements"]
        requested = dict(Counter(p["name"] for p in added))
        materials = bill(snapshot, rules, requested)
        if materials["requires_research"] or materials["unsupported"]:
            raise ValueError("procurement has unresolved prerequisites: " + str(materials["requires_research"] + materials["unsupported"]))
        if any(s["kind"] not in {"gather", "handcraft", "smelt"} for s in materials["steps"]):
            raise ValueError("science procurement needs an existing starter furnace")
        materials = refine(materials, rules)
        generation = sum(e.get("prototype_max_generation_kw", 0)
            for e in observation["capture"]["survey"]["infrastructure"])
        # Budget all new inserters at their full rated load, plus recipe work and idle drain.
        inserter_kw = 13 * sum(p["name"] == "inserter" for p in added)
        required_kw = graph["active_electric_kw"] + graph["idle_electric_kw"] + inserter_kw
        if generation < required_kw:
            raise ValueError("observed electrical generation cannot serve the additional recipe and transport load")
        builder.document.update(method={"id": self.source, "count": graph["nodes"][goal.item]["count"]},
            production_graph=graph, design=design, materials=materials, deployment=deepcopy(deployment),
            change={"retained": retained, "add": added, "bill": requested},
            boundary={"iron": deepcopy(deployment["service"]), "electricity": {"generation_kw": generation,
                "additional_budget_kw": required_kw}, "coal": design["source"],
                "contract": "verify fresh iron/copper/gear/science production and the entire connected fuel network"})
        for name, title in (("procure", "Acquire construction items"), ("build", "Establish production services"),
                            ("reconcile", "Verify paid native builds"), ("measure", "Observe sustained science output")):
            builder.group("goal/" + name, "goal", title, self.source)
        for item, addresses in design["components"].items():
            rate = graph["nodes"].get(item, {}).get("required_per_minute")
            title = f"Establish {rate:g} {item}/min" if rate else "Connect " + item
            builder.group("goal/build/" + item, "goal/build", title, self.source)

        def step(name, parent, op, inputs, check):
            builder.step("goal/" + name, "goal/" + parent, op, inputs, check, self.source)

        step("refresh", "build", "refresh_deployment", {"expected": retained}, "deployment_matches")
        step("preflight", "build", "preflight", {"specs": added}, "sites_clear")
        for i, batch in enumerate(materials["gather_batches"]):
            step(f"procure/gather-{i}", "procure", "gather",
                 {"item": batch["item"], "quantity": batch["quantity"]}, "inventory_gain")
        if materials["gather_batches"]:
            step("procure/raw-materials", "procure", "inventory",
                 {"items": materials["gather"], "boundary": "raw-materials"}, "inventory_at_least")
        for i, process in enumerate(materials["steps"]):
            if process["kind"] != "gather":
                step(f"procure/process-{i}", "procure", "process", deepcopy(process), "inventory_recipe_delta")
        step("procure/items", "procure", "inventory", {"items": requested}, "inventory_at_least")
        step("begin", "build", "begin_science", {"mining_areas": design["mining_areas"]}, "science_baseline")
        owners = {address: item for item, addresses in design["components"].items() for address in addresses}
        if set(owners) != {p["address"] for p in added}:
            raise ValueError("every placement must belong to a production service")
        for spec in added:
            step("build/" + spec["address"], "build/" + owners[spec["address"]], "place", {"spec": spec}, "paid_entity")
        step("reconcile/before", "reconcile", "mark_reconciliation", {}, "boundary_recorded")
        for spec in added:
            step("reconcile/" + spec["address"], "reconcile", "retain", {"spec": spec}, "entity_retained")
        step("reconcile/after", "reconcile", "finish_reconciliation", {}, "inventory_unchanged")
        policy = design["measurement"]
        step("measure/stabilize", "measure", "stabilize",
             {**policy["stabilization"], "window_ticks": policy["window_ticks"]}, "balanced_service")
        for i in range(policy["windows"]):
            step(f"measure/sample-{i}", "measure", "idle", {"ticks": policy["window_ticks"], "phase": "sample"}, "idle_window")
        step("measure/service", "measure", "verify_service", {"item": goal.item, "per_minute": goal.per_minute}, "connected_service")
