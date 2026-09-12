"""Offline research and material planning for a fresh surveyed red/green opening.

This abstract interpreter costs staged build plans. It never creates deployment
evidence or submits actions to the player executor.
"""
from collections import Counter
from copy import deepcopy
import json
import math
from pathlib import Path

from .legacy import ROOT, bill
from advisor_core.model import Snapshot, number
from advisor_core.rules import Rules
from .planning_world import PlanningWorld
from .production_graph import production_graph_many
from .program import Automate, digest

RED = "automation-science-pack"
GREEN = "logistic-science-pack"
DEFAULT_OBSERVATION = ROOT / "09_player_capture/integration/fixtures/initial-observation.json"
PROFILE = Path(__file__).with_name("planning_profile.json")


def amounts(entries):
    if isinstance(entries, dict):
        entries = [{"name": name, "amount": value} for name, value in entries.items()]
    result = Counter()
    for entry in entries:
        if entry.get("probability", 1) != 1 or "amount_min" in entry or "amount_max" in entry:
            raise ValueError("offline recipe planning requires deterministic amounts")
        result[entry["name"]] += number(entry["amount"], "recipe amount", positive=True)
    return dict(result)


def planning_rules(observation, profile):
    capture = observation["capture"]
    if capture["active_mods"] != {"base": profile["base_version"], "blueprint-gen-observer": "0.3.0"}:
        raise ValueError("offline assumptions require the reviewed base 2.1.17 observer profile")
    raw = capture["resolved_rules"]
    technologies = deepcopy(raw["technologies"])
    for tech in technologies.values():
        tech["prerequisites"] = list(tech["prerequisites"])
        tech["packs"] = amounts(tech["packs"])
        trigger = tech.get("trigger")
        if trigger and isinstance(trigger.get("item"), dict):
            if set(trigger["item"]) != {"name"}:
                raise ValueError("unsupported research item filter")
            trigger["item"] = trigger["item"]["name"]
    recipes = {}
    for name, recipe in raw["recipes"].items():
        category = next((c for c in ("crafting", "smelting") if c in recipe["categories"]), recipe["categories"][0])
        recipes[name] = {"category": category, "seconds": recipe["seconds"],
                         "enabled": recipe["enabled"], "inputs": amounts(recipe["inputs"]),
                         "outputs": amounts(recipe["outputs"]),
                         "unlocked_by": sorted(t for t, v in technologies.items() if name in v["unlocks"])}
    supplements = []
    for name, recipe in profile["recipes"].items():
        if name not in recipes:
            recipes[name] = deepcopy(recipe)
            supplements.append(name)
    machines = deepcopy(raw["machines"])
    for machine in machines.values():
        if machine["fuel_kw"]:
            machine["fuel"] = "coal"
    document = {"id": "offline-opening-v1", "recipes": recipes, "technologies": technologies,
                "machines": machines, "items": dict(raw["items"], **{name: "item" for name in profile["recipes"]}),
                "fuel_kj": raw["fuel_kj"],
                "default_recipes": {name: name for name, recipe in recipes.items() if name in recipe["outputs"]},
                "default_machines": {"crafting": "assembling-machine-1", "smelting": "stone-furnace"},
                "hand_collectable": ["coal", "iron-ore", "copper-ore", "stone", "wood"]}
    return Rules(document, digest(document)), supplements


class Progression:
    def __init__(self, observation, red, green, profile, *, schedule=None):
        self.goals = [Automate(RED, red), Automate(GREEN, green)]
        self.observation = deepcopy(observation)
        self.profile = deepcopy(profile)
        for key in ("burner_mining_speed", "burner_mining_kw", "steam_engine_kw", "boiler_kw",
                    "steam_efficiency", "resource_horizon_minutes"):
            number(profile[key], key, positive=True)
        number(profile["transport_reserve_kw"], "transport_reserve_kw")
        if observation["state"]["researched"] or observation["capture"]["survey"]["infrastructure"]:
            raise ValueError("fresh-start planning requires an empty factory with no research")
        if any(e["entity_type"] not in {"character", "tree", "simple-entity", "cliff"}
               for e in observation["capture"]["survey"]["obstacles"]):
            raise ValueError("fresh-start survey contains existing structures")
        self.rules, self.supplements = planning_rules(observation, profile)
        for recipe in self.rules.recipes.values():
            number(recipe["seconds"], "recipe seconds", positive=True)
        for machine in self.rules.machines.values():
            number(machine["speed"], "machine speed", positive=True)
        capture, state = observation["capture"], observation["state"]
        if (capture["tick"] != state["tick"] or capture["active_mods"] != state["active_mods"]
                or capture["scope"]["map_seed"] != state["map_seed"] or capture["researched"]):
            raise ValueError("fresh-start capture and state do not describe the same opening")
        self.world = PlanningWorld(observation)
        self.snapshot = Snapshot({"inventory": deepcopy(observation["state"]["inventory"]),
                                  "researched": [], "machines": [], "selected_recipes": {}})
        self.crafted = Counter()
        self.resources_used = Counter()
        self.services = {}
        self.stages = []
        self.events = []
        self.materials = []
        self.schedule = schedule

    def install(self, stage, fallback):
        before = len(self.world.entities)
        if self.schedule is None:
            fallback()
        else:
            for spec in self.schedule[stage]:
                self.world.add(spec)
        self.built(before)
        if self.schedule is not None:
            drills = [e for e in self.world.entities[before:] if e["name"] == "burner-mining-drill"]
            if drills:
                self.procure({"coal": 5 * len(drills)})
                self.events.append({"kind": "commission", "item": "coal", "count": 5 * len(drills),
                    "targets": [e["address"] for e in drills], "instruction": "Seed each new drill with five coal while the fuel belts fill."})

    def triggers(self):
        changed = True
        while changed:
            changed = False
            for name, tech in self.rules.technologies.items():
                trigger = tech.get("trigger")
                if name in self.snapshot.researched or not trigger:
                    continue
                if not set(tech["prerequisites"]) <= self.snapshot.researched:
                    continue
                if trigger["type"] == "craft-item" and self.crafted[trigger["item"]] >= trigger.get("count", 1):
                    self.snapshot.document["researched"].append(name)
                    self.events.append({"kind": "trigger", "technology": name,
                                        "item": trigger["item"], "count": trigger.get("count", 1)})
                    changed = True

    def procure(self, requested, *, keep=False, fresh=False):
        if not requested:
            return
        result = bill(self.snapshot, self.rules, requested, force_craft=fresh)
        if result["requires_research"] or result["unsupported"]:
            raise ValueError("procurement prerequisite unresolved: " + str(result["requires_research"] + result["unsupported"]))
        if any(step["kind"] in {"place", "supply"} for step in result["steps"]):
            raise ValueError("procurement requires an unplanned station or external supply")
        self.snapshot.document["inventory"] = result["remaining_inventory"]
        if keep:
            for item, count in requested.items():
                stock = self.snapshot.document["inventory"]
                stock[item] = stock.get(item, 0) + count
        self.resources_used.update(result["gather"])
        for step in result["steps"]:
            self.crafted.update(step.get("outputs", {}))
        self.materials.append(result)
        self.triggers()

    def built(self, before):
        for entity in self.world.entities[before:]:
            recipe = entity.get("recipe")
            for item in (entity["name"], recipe):
                if item and not self.rules.unlocked(item, self.snapshot.researched):
                    raise ValueError("build before research: " + item)
        self.procure(self.world.bill_since(before))
        self.snapshot.document["machines"] = [
            {"prototype": e["name"], "built": True} for e in self.world.entities]

    def graph(self, goals):
        return production_graph_many(goals, self.rules, self.snapshot.researched)

    def utility_budget(self, graph):
        nodes = graph["nodes"]
        p = self.profile
        fuel = self.rules.document["fuel_kj"]["coal"]
        mining_rate = 60 * p["burner_mining_speed"]
        mining_fuel_per_item = p["burner_mining_kw"] / p["burner_mining_speed"] / fuel
        if mining_fuel_per_item >= 1:
            raise ValueError("coal mining consumes its entire output")
        electric = graph["active_electric_kw"] + graph["idle_electric_kw"] + self.rules.machines["lab"]["electric_kw"]
        electric += p["transport_reserve_kw"]
        ore = {item: n["required_per_minute"] for item, n in nodes.items()
               if n.get("method") == "extraction" and item != "coal"}
        smelting_coal = nodes.get("coal", {}).get("required_per_minute", 0)
        mining_coal = sum(ore.values()) * mining_fuel_per_item
        power_coal = electric * 60 / (fuel * p["steam_efficiency"])
        coal = (smelting_coal + mining_coal + power_coal) / (1 - mining_fuel_per_item)
        raw = dict(ore, coal=coal)
        return {"electric_kw": electric, "transport_reserve_kw": p["transport_reserve_kw"],
                "engines": math.ceil(electric / p["steam_engine_kw"]),
                "smelting_coal_per_minute": smelting_coal, "ore_mining_coal_per_minute": mining_coal,
                "power_coal_per_minute": power_coal, "coal_mining_coal_per_minute": coal * mining_fuel_per_item,
                "raw_per_minute": raw, "mining_capacity_per_drill": mining_rate,
                "miners": {item: math.ceil(rate / mining_rate - 1e-9) for item, rate in raw.items()},
                "assumption": "Average recipe load plus one active lab and a reserved transport load; coal includes its own mining fuel."}

    def support(self, graph):
        budget = self.utility_budget(graph)
        if budget["electric_kw"] > self.profile["boiler_kw"]:
            raise ValueError("required power exceeds the one-boiler planning method")
        self.world.power(budget["engines"])
        for item, count in budget["miners"].items():
            self.world.miners(item, count)
        self.world.processes(graph, {"iron-plate", "copper-plate"})

    def enable(self, goals):
        graph = self.graph(goals)
        budget = self.utility_budget(graph)
        for item, node in graph["nodes"].items():
            if node.get("method") == "recipe" and self.world.count(item, node["machine"]) < node["count"]:
                raise ValueError("insufficient installed process capacity for " + item)
        for item, count in budget["miners"].items():
            if self.world.count(item, "burner-mining-drill") < count:
                raise ValueError("insufficient installed mining capacity for " + item)
        engines = sum(e["name"] == "steam-engine" for e in self.world.entities)
        if engines < budget["engines"]:
            raise ValueError("insufficient installed generation")
        self.services = {g.item: g.per_minute for g in goals}

    def research(self, technology):
        tech = self.rules.technologies[technology]
        if tech.get("trigger") or not set(tech["prerequisites"]) <= self.snapshot.researched:
            raise ValueError("research prerequisites missing for " + technology)
        if not any(e["name"] == "lab" for e in self.world.entities):
            raise ValueError("research needs a planned powered lab")
        stock = self.snapshot.document["inventory"]
        cost = {item: tech["count"] * count for item, count in tech["packs"].items()}
        supply_minutes = 0
        for item, count in cost.items():
            deficit = max(0, count - stock.get(item, 0))
            if deficit and not self.services.get(item):
                raise ValueError("research has no science supply: " + item)
            if deficit:
                supply_minutes = max(supply_minutes, deficit / self.services[item])
        lab_minutes = tech["count"] * tech["seconds"] / self.rules.machines["lab"]["speed"] / 60
        minutes = max(supply_minutes, lab_minutes)
        if self.services:
            graph = self.graph([Automate(item, rate) for item, rate in self.services.items()])
            for item, rate in self.utility_budget(graph)["raw_per_minute"].items():
                self.resources_used[item] += rate * minutes
            for item, rate in self.services.items():
                stock[item] = stock.get(item, 0) + rate * minutes
        else:
            self.resources_used["coal"] += (lab_minutes * 60 * self.rules.machines["lab"]["electric_kw"]
                                            / self.rules.document["fuel_kj"]["coal"])
        for item, count in cost.items():
            stock[item] = stock.get(item, 0) - count
        self.snapshot.document["researched"].append(technology)
        self.events.append({"kind": "research", "technology": technology, "packs_consumed": cost,
                            "lab_minutes": lab_minutes, "supply_minutes": supply_minutes,
                            "duration_lower_bound_minutes": minutes,
                            "timing_scope": "Ideal continuous flow; excludes startup, travel, construction and packet timing."})

    def stage(self, ident, title, instruction, action):
        before = len(self.world.entities)
        self.events, self.materials = [], []
        action()
        graph = self.graph([Automate(item, rate) for item, rate in self.services.items()])
        stage = {"id": ident, "title": title, "instruction": instruction,
                 "requires": [self.stages[-1]["id"]] if self.stages else [],
                 "additions": deepcopy(self.world.entities[before:]), "retained_count": before,
                 "placements": deepcopy(self.world.entities), "construction_bill": self.world.bill_since(before),
                 "procurement": deepcopy(self.materials), "events": deepcopy(self.events),
                 "state_after": {"researched": sorted(self.snapshot.researched),
                                 "inventory": deepcopy(self.snapshot.document["inventory"]),
                                 "conditional_services_per_minute": dict(self.services),
                                 "resources_used": dict(self.resources_used)},
                 "production_graph": graph,
                 "status": "estimated", "execution_ready": False}
        if self.services:
            stage["utility_budget"] = self.utility_budget(graph)
        self.stages.append(stage)

    def compile(self):
        red, green = self.goals

        def starter():
            self.install("starter", lambda: self.world.site("iron-plate", "stone-furnace", 0, (-9, -5), recipe="iron-plate"))
            # Force new production for trigger counts; initial plates do not count.
            for tech in ("steam-power", "electronics"):
                trigger = self.rules.technologies[tech]["trigger"]
                self.procure({trigger["item"]: trigger.get("count", 1)}, keep=True, fresh=True)

        self.stage("starter", "Starter smelting", "Place the starter furnace. Mine fuel and ore by hand; smelt the trigger batches. Reuse the furnace for both metals.", starter)

        def power():
            self.install("power", self.world.power)
            if self.schedule is not None:
                self.procure({"coal": 20})
                self.events.append({"kind": "commission", "item": "coal", "count": 20,
                                    "target": "power.boiler", "instruction": "Manually seed the boiler for initial power."})

        self.stage("power", "Steam power and a lab", "Build the surveyed shoreline power island. Crafting the lab makes red science available. Feed the boiler by hand during bootstrap.", power)

        def automation():
            for name in ("automation", "logistics"):
                tech = self.rules.technologies[name]
                self.procure({item: tech["count"] * count for item, count in tech["packs"].items()}, keep=True)
                self.research(name)

        self.stage("automation", "Automation and Logistics", "Handcraft red packs for Automation and Logistics. The factory uses assemblers and underground belts for crossings.", automation)

        def red_factory():
            graph = self.graph([red])
            def layout():
                self.support(graph)
                self.world.processes(graph)
            self.install("red", layout)
            self.enable([red])

        self.stage("red", f"Red science at {red.per_minute:g}/min", "Add mining, smelting, gears and red science assembly with the shown belts, inserters and power poles. Seed the drills while the fuel belts fill.", red_factory)
        self.stage("green-research", "Research green science", "Use the red science service to supply the lab. Existing machinery stays in place.", lambda: self.research(GREEN))
        final_graph = self.graph(self.goals)

        def expand():
            self.install("expand", lambda: self.support(final_graph))

        self.stage("expand", "Expand shared metal and fuel supply", "Size the shared supply for both science outputs at once. Retain the red science factory.", expand)

        def intermediates():
            self.install("intermediates", lambda: self.world.processes(final_graph,
                {"iron-gear-wheel", "copper-cable", "electronic-circuit", "transport-belt", "inserter"}))

        self.stage("intermediates", "Belts, inserters and circuits", "Add cable, circuit, belt and inserter assembly. Reserve shared gear and plate capacity for both science chains.", intermediates)

        def finish():
            self.install("red-green", lambda: self.world.processes(final_graph))
            self.enable(self.goals)

        self.stage("red-green", f"Red {red.per_minute:g}/min + green {green.per_minute:g}/min", "Add green science assembly and connect its belt and inserter inputs. Keep both declared science outputs supplied concurrently.", finish)
        budget = self.utility_budget(final_graph)
        resource_check = {}
        for item in sorted(set(self.resources_used) | set(budget["raw_per_minute"])):
            if item == "wood":
                continue  # Tree yields are absent from this observer's survey.
            available = sum(r["amount"] for r in self.world.resource(item))
            horizon = budget["raw_per_minute"].get(item, 0) * self.profile["resource_horizon_minutes"]
            required = self.resources_used[item] + horizon
            if required > available:
                raise ValueError("surveyed resource stock cannot fund the plan and horizon: " + item)
            resource_check[item] = {"surveyed": available, "finite_work": self.resources_used[item],
                                    "final_horizon": horizon, "remaining": available - required}
        return {"schema_version": 1, "artifact_kind": "offline-blueprint-sequence",
                "goal": {g.item: g.per_minute for g in self.goals}, "status": "site-plans-generated",
                "execution_ready": False, "goal_verified": False,
                "source": {"observation_sha256": digest(self.observation), "rules_sha256": self.rules.digest,
                           "profile_sha256": digest(self.profile), "map_seed": self.observation["state"]["map_seed"],
                           "factorio_version": self.observation["capture"]["factorio_version"],
                           "supplemented_recipes": self.supplements},
                "assumptions": deepcopy(self.profile), "initial_inventory": self.observation["state"]["inventory"],
                "survey": self.world.survey, "stages": self.stages, "final_graph": final_graph,
                "final_utility_budget": budget, "resource_check": resource_check,
                "unresolved": ["Route belts, inserters and automatic burner fuel between machine sites; their construction bill is not included.",
                               "Route poles from the steam island and check transport stays within the reserved power budget.",
                               "Check tree yields for the finite wood bill and reachable construction approaches.",
                               "Validate startup, belt flow, discrete crafts and sustained output in the game before marking the goal verified."],
                "model": "Recipe-rate and research state simulation with cumulative machine footprints. Services assume connected inputs and outputs; no engine ticks are simulated."}


def compile_progression(observation, red_per_minute=10, green_per_minute=10, *, profile=None):
    profile = json.loads(PROFILE.read_text()) if profile is None else deepcopy(profile)
    from .planning_transport import TransportLayout, inserter_count, validate_transport
    # Size generation and coal extraction against the actual number of arms.
    # Added coal miners themselves add refuelling arms, so solve that small fixed point.
    for _ in range(8):
        skeleton = Progression(observation, red_per_minute, green_per_minute, profile).compile()
        required = inserter_count(skeleton) * profile["inserter_max_kw"]
        if required <= profile["transport_reserve_kw"]:
            break
        profile["transport_reserve_kw"] = required
    else:
        raise ValueError("transport power and coal sizing did not converge")
    errors = []
    for strategy, length in (("dense-first",18), ("resources-first",18), ("dense-first",24),
                             ("resources-first",24), ("assembly-first",18), ("assembly-first",24)):
        try:
            schedule, transport = TransportLayout(skeleton, observation, strategy=strategy, corridor_length=length).compile()
            break
        except ValueError as error:
            errors.append(str(error))
    else:
        raise ValueError("transport layout search exhausted: " + errors[-1])
    result = Progression(observation, red_per_minute, green_per_minute, profile, schedule=schedule).compile()
    for index, stage in enumerate(result["stages"]):
        ids = {e["address"] for e in stage["placements"]}
        stage["connections"] = [e for e in transport["connections"] if e["from"] in ids and e["to"] in ids]
        routes = {item: dict(route, ports=[p for p in route["ports"] if p["machine"] in ids])
                  for item, route in transport["routes"].items() if route["stage"] <= index}
        stage["transport_validation"] = validate_transport(stage["placements"], stage["connections"], routes)
    result.update(status="routed-plans-generated", transport=transport,
        unresolved=["Check startup, inserter throughput and sustained output in the game before marking the goal verified.",
                    "Check tree yields for the finite wood bill and reachable construction approaches.",
                    "Supervise initial fuel seeding until automatic refuelling has filled its buffers."],
        model="Cumulative factory plans with belts, inserters, splitter branches, underground crossings and wired power. Static geometry and connectivity pass; production rates remain estimates until a game run.")
    return result
