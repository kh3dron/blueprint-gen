import base64
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import zlib

from factory_constructor.planning_artifacts import blueprint, site_svg, write_progression
from factory_constructor.planning_transport import validate_transport
from factory_constructor.planning_world import PlanningWorld
from factory_constructor.production_graph import production_graph_many
from factory_constructor.program import Automate, Executor
from factory_constructor.progression import (compile_progression, DEFAULT_OBSERVATION,
                                            GREEN, PROFILE, Progression, RED)


class ProgressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.opening = json.loads(DEFAULT_OBSERVATION.read_text())
        cls.plan = compile_progression(cls.opening)

    def planner(self):
        return Progression(deepcopy(self.opening), 10, 10, json.loads(PROFILE.read_text()))

    def test_fresh_start_triggers_precede_science_and_assemblers(self):
        stages = self.plan["stages"]
        self.assertEqual(stages[0]["state_after"]["researched"], ["electronics", "steam-power"])
        self.assertIn(RED, stages[1]["state_after"]["researched"])
        self.assertNotIn("automation", stages[1]["state_after"]["researched"])
        self.assertEqual(stages[2]["events"][0]["packs_consumed"], {RED: 10})
        self.assertAlmostEqual(stages[2]["events"][0]["duration_lower_bound_minutes"], 100 / 60)
        self.assertFalse(any(e["name"] == "assembling-machine-1" for s in stages[:3] for e in s["additions"]))
        self.assertNotIn(GREEN, stages[3]["state_after"]["researched"])
        self.assertEqual(stages[4]["events"][0]["packs_consumed"], {RED: 75})
        self.assertEqual(stages[4]["events"][0]["duration_lower_bound_minutes"], 7.5)
        self.assertEqual(stages[4]["state_after"]["inventory"][RED], 0)
        self.assertIn("logistics", stages[2]["state_after"]["researched"])
        self.assertEqual(stages[2]["events"][1]["packs_consumed"], {RED: 20})

    def test_inventory_does_not_pay_crafting_trigger_or_sustained_rate(self):
        first = self.plan["stages"][0]
        batches = first["procurement"]
        self.assertEqual(next(p for p in batches if p["requested"] == {"iron-plate": 50})["gather"]["iron-ore"], 50)
        rich = deepcopy(self.opening)
        rich["state"]["inventory"]["iron-plate"] = 10000
        result = compile_progression(rich)
        self.assertEqual(result["final_graph"], self.plan["final_graph"])
        self.assertEqual(result["stages"][-1]["placements"], self.plan["stages"][-1]["placements"])

    def test_shared_demand_and_recipe_batch_yields(self):
        nodes = self.plan["final_graph"]["nodes"]
        expected = {RED: 10, GREEN: 10, "iron-plate": 75, "copper-plate": 25,
                    "iron-gear-wheel": 25, "copper-cable": 30, "electronic-circuit": 10,
                    "transport-belt": 10, "inserter": 10}
        self.assertEqual({k: nodes[k]["required_per_minute"] for k in expected}, expected)
        self.assertEqual(nodes["transport-belt"]["crafts_per_minute"], 5)
        self.assertEqual(nodes["copper-cable"]["crafts_per_minute"], 15)
        self.assertEqual(nodes[GREEN]["count"], 2)
        self.assertEqual(nodes["iron-plate"]["count"], 4)
        self.assertEqual(self.plan["stages"][-1]["state_after"]["conditional_services_per_minute"], {RED: 10, GREEN: 10})

    def test_multi_goal_supply_is_allocated_once(self):
        planner = self.planner()
        graph = production_graph_many([Automate(RED, 10), Automate(RED, 5)], planner.rules,
                                      {"automation", RED, "electronics", "steam-power"}, available={"iron-plate": 25})
        iron = graph["nodes"]["iron-plate"]
        self.assertEqual(iron["required_per_minute"], 30)
        self.assertEqual(iron["reused_per_minute"], 25)
        self.assertEqual(iron["crafts_per_minute"], 5)

    def test_fuel_includes_coal_extraction_and_all_shared_load(self):
        budget = self.plan["final_utility_budget"]
        coal = sum(budget[k] for k in ("smelting_coal_per_minute", "ore_mining_coal_per_minute",
                                      "power_coal_per_minute", "coal_mining_coal_per_minute"))
        self.assertAlmostEqual(coal, budget["raw_per_minute"]["coal"])
        self.assertEqual(budget["miners"], {"iron-ore": 5, "copper-ore": 2, "coal": 4})
        self.assertLessEqual(budget["electric_kw"], budget["engines"] * 900)

    def test_stage_geometry_is_additive_and_bills_match(self):
        previous = []
        for index, stage in enumerate(self.plan["stages"]):
            self.assertEqual(stage["requires"], [self.plan["stages"][index-1]["id"]] if index else [])
            self.assertEqual(stage["placements"], previous + stage["additions"])
            self.assertEqual(stage["retained_count"], len(previous))
            self.assertEqual(stage["construction_bill"], dict(Counter(e["name"] for e in stage["additions"])))
            previous = stage["placements"]
        self.assertEqual(len({e["address"] for e in previous}), len(previous))
        self.assertTrue(all(q >= 0 for s in self.plan["stages"] for q in s["state_after"]["inventory"].values()))

    def test_full_footprints_are_dry_clear_and_surveyed(self):
        world = PlanningWorld(self.opening)
        for entity in self.plan["stages"][-1]["placements"]:
            self.assertTrue(world.clear(entity), entity["address"])
            if entity["name"] == "burner-mining-drill":
                tiles = {(int(r["position"]["x"]-.5), int(r["position"]["y"]-.5))
                         for r in world.resource(entity["service"])}
                self.assertLessEqual(world.cells(entity), tiles)
            world.add(entity)

    def test_terrain_changes_relocate_sites_without_moving_retained_entities(self):
        changed = deepcopy(self.opening)
        first = self.plan["stages"][0]["placements"][0]
        x, y = next(iter(PlanningWorld.cells(first)))
        changed["capture"]["survey"]["obstacles"].append({"entity_type": "cliff", "prototype": "cliff",
            "id": "new-cliff", "position": {"x": x+.5, "y": y+.5},
            "bounding_box": {"left_top": {"x": x, "y": y}, "right_bottom": {"x": x+1, "y": y+1}}})
        result = compile_progression(changed)
        relocated = result["stages"][0]["placements"][0]
        self.assertNotEqual(relocated["position"], first["position"])
        self.assertEqual(relocated, result["stages"][-1]["placements"][0])

    def test_rates_and_runtime_recipe_changes_change_machine_counts(self):
        small = compile_progression(self.opening, 6, 5)
        self.assertEqual(small["final_graph"]["nodes"][RED]["count"], 1)
        self.assertEqual(small["final_graph"]["nodes"][GREEN]["count"], 1)
        self.assertLess(len(small["stages"][-1]["placements"]), len(self.plan["stages"][-1]["placements"]))
        changed = deepcopy(self.opening)
        changed["capture"]["resolved_rules"]["recipes"][GREEN] = {
            "categories": ["crafting"], "seconds": 3, "enabled": False,
            "inputs": [{"name": "inserter", "amount": 1}, {"name": "transport-belt", "amount": 1}],
            "outputs": [{"name": GREEN, "amount": 1}]}
        result = compile_progression(changed)
        self.assertNotIn(GREEN, result["source"]["supplemented_recipes"])
        self.assertEqual(result["final_graph"]["nodes"][GREEN]["count"], 1)

    def test_invalid_rates_worlds_and_shortages_fail_before_export(self):
        for rate in (0, -1, True, float("nan"), float("inf")):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                compile_progression(self.opening, 10, rate)
        for mutate, message in (
            (lambda o: o["state"].update(researched=["automation"]), "empty factory"),
            (lambda o: o["capture"]["active_mods"].update(base="2.2.0"), "profile"),
            (lambda o: o["capture"]["survey"].update(water_tiles=[]), "water"),
            (lambda o: o["capture"]["survey"].update(resources=[r for r in o["capture"]["survey"]["resources"] if r["prototype"] != "copper-ore"]), "resource"),
        ):
            changed = deepcopy(self.opening)
            mutate(changed)
            with self.assertRaisesRegex(ValueError, message):
                compile_progression(changed)
        depleted = deepcopy(self.opening)
        for r in depleted["capture"]["survey"]["resources"]:
            r["amount"] = 1
        with self.assertRaisesRegex(ValueError, "resource stock"):
            compile_progression(depleted)

    def test_research_requires_supply_and_services_require_capacity(self):
        planner = self.planner()
        planner.world.power()
        planner.snapshot.document["researched"] = ["steam-power", "electronics", RED]
        with self.assertRaisesRegex(ValueError, "no science supply"):
            planner.research("automation")
        with self.assertRaisesRegex(ValueError, "insufficient installed"):
            planner.enable([Automate(RED, 10)])
        with self.assertRaisesRegex(ValueError, "research prerequisites"):
            self.planner().research(GREEN)

    def test_deterministic_immutable_artifacts_and_blueprint_roundtrip(self):
        before = deepcopy(self.opening)
        self.assertEqual(compile_progression(self.opening), self.plan)
        self.assertEqual(self.opening, before)
        with tempfile.TemporaryDirectory() as directory:
            viewer = write_progression(self.plan, directory)
            text = (Path(directory)/"blueprint-book.txt").read_text().strip()
            decoded = json.loads(zlib.decompress(base64.b64decode(text[1:])))
            entries = decoded["blueprint_book"]["blueprints"]
            self.assertEqual(len(entries), len(self.plan["stages"]))
            for stage, entry in zip(self.plan["stages"], entries):
                self.assertEqual(len(stage["placements"]), len(entry["blueprint"]["entities"]))
                self.assertTrue(all("recipe" not in e for e in entry["blueprint"]["entities"] if e["name"] == "stone-furnace"))
                self.assertIn("build plan", entry["blueprint"]["label"])
            self.assertIn('id="data"', viewer.read_text())
            self.assertNotIn("__PLAN_DATA__", viewer.read_text())
            self.assertEqual(json.loads((Path(directory)/"plan.json").read_text()), self.plan)

    def test_hypothetical_state_cannot_be_used_as_executor_evidence(self):
        self.assertFalse(self.plan["execution_ready"])
        self.assertFalse(self.plan["goal_verified"])
        self.assertTrue(self.plan["unresolved"])
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            Executor(self.plan, None, directory).run()

    def test_transport_is_staged_costed_and_visible(self):
        self.assertFalse(any(e["name"] == "inserter" for e in self.plan["stages"][2]["placements"]))
        for stage in self.plan["stages"][3:]:
            svg = site_svg(self.plan, stage)
            for name in ("transport-belt", "underground-belt", "inserter"):
                self.assertIn(f'data-entity="{name}"', svg)
            self.assertEqual(stage["transport_validation"]["status"], "passed")
            ids = {e["address"] for e in stage["placements"]}
            self.assertTrue(all(c["from"] in ids and c["to"] in ids for c in stage["connections"]))
        bill = self.plan["stages"][3]["construction_bill"]
        for name in ("transport-belt", "underground-belt", "splitter", "inserter", "small-electric-pole"):
            self.assertGreater(bill[name], 0)
        arms = sum(e["name"] == "inserter" for e in self.plan["stages"][-1]["placements"])
        self.assertGreaterEqual(self.plan["final_utility_budget"]["transport_reserve_kw"], 13 * arms)

    def test_blueprint_preserves_tunnels_splitter_priority_and_wires(self):
        stage = self.plan["stages"][-1]
        result = blueprint(stage, self.plan["source"]["factorio_version"])["blueprint"]
        for spec, exported in zip(stage["placements"], result["entities"]):
            if spec["name"] == "underground-belt":
                self.assertEqual(exported["type"], spec["type"])
            if spec.get("output_priority"):
                self.assertEqual(exported["output_priority"], spec["output_priority"])
        self.assertTrue(any(e.get("output_priority") for e in result["entities"]))
        self.assertEqual(len(result["wires"]), sum(c["kind"] == "wire" for c in stage["connections"]))
        self.assertGreater(len(result["wires"]), 0)
        for a, connector_a, b, connector_b in result["wires"]:
            self.assertEqual((connector_a, connector_b), (5, 5))
            self.assertEqual(result["entities"][a-1]["name"], "small-electric-pole")
            self.assertEqual(result["entities"][b-1]["name"], "small-electric-pole")

    def test_validator_rejects_broken_physical_connections(self):
        stage = self.plan["stages"][-1]
        routes = self.plan["transport"]["routes"]
        for name, message in (("transport-belt", "belt"), ("inserter", "inserter"),
                              ("underground-belt", "belt")):
            placements = deepcopy(stage["placements"])
            entity = next(e for e in placements if e["name"] == name)
            entity["direction"] = (entity["direction"] + 8) % 16
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, message):
                validate_transport(placements, stage["connections"], routes)
        for kind, message in (("wire", "disconnected"), ("power", "disconnected"),
                              ("direct-mining", "unreachable")):
            connections = deepcopy(stage["connections"])
            target = next(c for c in connections if c["kind"] == kind and
                          (kind != "power" or ".input." in c["to"]))
            connections.remove(target)
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, message):
                validate_transport(stage["placements"], connections, routes)


if __name__ == "__main__":
    unittest.main()
