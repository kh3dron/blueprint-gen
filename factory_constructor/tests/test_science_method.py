from collections import Counter
from copy import deepcopy
import gzip
import json
from pathlib import Path
import unittest

from factory_constructor.__main__ import compile_observation
from factory_constructor.deployment import record
from factory_constructor.legacy import CoalDriver
from factory_constructor.production_graph import production_graph
from factory_constructor.program import Automate, digest, validate


FIXTURE = Path(__file__).resolve().parents[1]/"integration/fixtures/iron-20.json.gz"


class ScienceCompilerTest(unittest.TestCase):
    def setUp(self):
        evidence = json.loads(gzip.decompress(FIXTURE.read_bytes()))
        self.observation = evidence["inputs"]["final"]
        self.deployment = record(evidence["program"], self.observation, evidence["verification"])

    def compile(self, rate=10):
        return compile_observation(Automate("automation-science-pack", rate), self.observation, self.deployment)

    def test_goal_backchains_recipe_rates_and_reuses_verified_iron(self):
        program = self.compile()
        self.assertEqual(program["blockers"], [])
        graph = program["production_graph"]["nodes"]
        self.assertEqual({item: graph[item]["required_per_minute"] for item in
                          ("automation-science-pack", "iron-gear-wheel", "iron-plate", "copper-plate", "copper-ore")},
                         {"automation-science-pack": 10, "iron-gear-wheel": 10,
                          "iron-plate": 20, "copper-plate": 10, "copper-ore": 10})
        self.assertEqual(graph["iron-plate"]["method"], "reuse")
        self.assertEqual(graph["iron-plate"]["reused_per_minute"], 20)
        self.assertEqual(graph["iron-plate"]["count"], 0)
        self.assertNotIn("iron-ore", graph)
        self.assertEqual(graph["copper-ore"]["method"], "extraction")
        self.assertEqual(graph["automation-science-pack"]["count"], 2)
        self.assertEqual(graph["iron-gear-wheel"]["count"], 1)
        self.assertEqual(program["change"]["retained"], self.deployment["entities"])
        self.assertEqual(program["design"]["retained_placements"], self.deployment["design"]["placements"])

    def test_service_groups_own_all_and_only_their_paid_builds(self):
        program = self.compile()
        components = program["design"]["components"]
        owner = {address: item for item, addresses in components.items() for address in addresses}
        builds = [n for n in program["nodes"] if n["operation"] == "place"]
        additions = program["change"]["add"]
        self.assertEqual({n["inputs"]["spec"]["address"] for n in builds}, set(owner))
        self.assertEqual([n["inputs"]["spec"] for n in builds], additions)
        for node in builds:
            address = node["inputs"]["spec"]["address"]
            self.assertEqual(node["parent"], "goal/build/"+owner[address])
            self.assertEqual(node["check"], "paid_entity")
            self.assertNotIn(address, self.deployment["entities"])
        paid_bill = dict(Counter(s["name"] for s in additions))
        self.assertEqual(program["change"]["bill"], paid_bill)
        self.assertEqual(program["materials"]["requested"], paid_bill)
        self.assertEqual(paid_bill["stone-furnace"], 1)
        self.assertEqual(paid_bill["burner-mining-drill"], 2)
        self.assertEqual(paid_bill["assembling-machine-1"], 3)

    def test_procurement_batches_are_explicit_bounded_program_nodes(self):
        program = self.compile()
        self.assertEqual(program["blockers"], [])
        gathered = Counter()
        for node in program["nodes"]:
            if node["operation"] == "gather":
                self.assertLessEqual(node["inputs"]["quantity"], 100)
                gathered[node["inputs"]["item"]] += node["inputs"]["quantity"]
            elif node["operation"] == "process":
                step = node["inputs"]
                self.assertLessEqual(step.get("processing_seconds", step.get("crafting_seconds")), 240)
                if step["kind"] == "smelt":
                    self.assertTrue(all(quantity <= 50 for quantity in step["inputs"].values()))
        self.assertEqual(dict(gathered), program["materials"]["gather"])
        self.assertEqual(len([n for n in program["nodes"] if n["operation"] == "gather"]),
                         len(program["materials"]["gather_batches"]))
        validate(json.loads(json.dumps(program)))

    def test_funding_changes_procurement_without_changing_generated_factory(self):
        original = self.compile()
        self.observation["state"]["inventory"].update(original["change"]["bill"])
        funded = self.compile()
        self.assertEqual(funded["blockers"], [])
        self.assertEqual(funded["materials"]["gather"], {})
        self.assertEqual(funded["design"], original["design"])
        self.assertEqual(funded["production_graph"], original["production_graph"])

    def test_serialized_program_retains_prerequisites_and_measured_completion(self):
        program = json.loads(json.dumps(self.compile()))
        nodes, leaves = validate(program)
        previous = None
        for node in program["nodes"]:
            if node["operation"]:
                self.assertEqual(node["requires"], [previous] if previous else [])
                previous = node["id"]
        self.assertEqual(leaves[previous]["operation"], "verify_service")
        self.assertEqual(leaves[previous]["inputs"], {"item": "automation-science-pack", "per_minute": 10})
        self.assertEqual(leaves[previous]["check"], "connected_service")
        warmup = [n for n in leaves.values() if n["operation"] == "stabilize"]
        measured = [n for n in leaves.values() if n["operation"] == "idle" and n["inputs"]["phase"] == "sample"]
        self.assertEqual(len(warmup), 1)
        self.assertEqual(warmup[0]["check"], "balanced_service")
        self.assertEqual(warmup[0]["inputs"], {"minimum_windows": 5, "maximum_windows": 30,
                                            "stable_windows": 3, "window_ticks": 3600})
        self.assertEqual(measured[0]["requires"], [warmup[0]["id"]])
        self.assertEqual(len(measured), 5)
        self.assertIn("compilation is not completion", program["completion"])
        program["design"]["placements"][0]["direction"] = 4
        with self.assertRaisesRegex(ValueError, "changed"):
            validate(program)

    def test_missing_iron_service_and_power_capacity_block_without_actions(self):
        self.deployment["service"]["minimum_per_minute"] = 19
        self.deployment["sha256"] = digest({k: v for k, v in self.deployment.items() if k != "sha256"})
        insufficient = self.compile()
        self.assertIn("verified iron service", insufficient["blockers"][0])
        self.assertFalse(any(n["operation"] for n in insufficient["nodes"]))
        self.setUp()
        for entity in self.observation["capture"]["survey"]["infrastructure"]:
            if "prototype_max_generation_kw" in entity:
                entity["prototype_max_generation_kw"] = 1
        insufficient = self.compile()
        self.assertIn("electrical generation", insufficient["blockers"][0])
        self.assertFalse(any(n["operation"] for n in insufficient["nodes"]))

    def test_goal_and_runtime_changes_recompile_machine_counts_and_rates(self):
        six, ten = self.compile(6), self.compile(10)
        self.assertEqual(six["blockers"], [])
        self.assertEqual(ten["blockers"], [])
        self.assertEqual(six["method"]["count"], 1)
        self.assertEqual(ten["method"]["count"], 2)
        self.assertEqual(six["production_graph"]["nodes"]["iron-plate"]["required_per_minute"], 12)
        self.assertLess(len(six["change"]["add"]), len(ten["change"]["add"]))
        self.observation["capture"]["resolved_rules"]["recipes"]["automation-science-pack"]["seconds"] = 3
        faster = self.compile()
        self.assertEqual(faster["blockers"], [])
        self.assertEqual(faster["method"]["count"], 1)
        self.assertEqual(faster["design"]["counts"]["selected"]["automation-science-pack"], 1)
        self.assertLess(faster["production_graph"]["active_electric_kw"], ten["production_graph"]["active_electric_kw"])


class ProductionGraphTest(unittest.TestCase):
    def setUp(self):
        evidence = json.loads(gzip.decompress(FIXTURE.read_bytes()))
        observation = evidence["inputs"]["final"]
        self.snapshot, self.rules = CoalDriver.snapshot(observation["capture"], observation["state"])

    def graph(self, available=None):
        return production_graph(Automate("automation-science-pack", 10), self.rules,
                                self.snapshot.researched, available=available)

    def test_shared_ingredient_demands_accumulate_and_reuse_capacity_once(self):
        # Two independent recipe paths now need iron: 20/min through gears and
        # 30/min directly. The available 25/min can be consumed only once.
        self.rules.recipes["automation-science-pack"]["inputs"]["iron-plate"] = 3
        graph = self.graph({"iron-plate": 25})["nodes"]
        iron = graph["iron-plate"]
        self.assertEqual(iron["required_per_minute"], 50)
        self.assertEqual(iron["reused_per_minute"], 25)
        self.assertEqual(iron["crafts_per_minute"], 25)
        self.assertEqual(iron["count"], 2)
        self.assertEqual(graph["iron-ore"]["required_per_minute"], 25)

    def test_coal_smelting_demand_and_electrical_work_come_from_runtime_rules(self):
        graph = self.graph({"iron-plate": 30})
        copper = graph["nodes"]["copper-plate"]
        furnace = self.rules.machines["stone-furnace"]
        coal_per_minute = 10 * furnace["fuel_kw"] * self.rules.recipes["copper-plate"]["seconds"] / furnace["speed"] / self.rules.document["fuel_kj"]["coal"]
        self.assertAlmostEqual(copper["dependencies"]["coal"], coal_per_minute)
        self.assertAlmostEqual(graph["nodes"]["coal"]["required_per_minute"], coal_per_minute)
        self.assertAlmostEqual(graph["active_electric_kw"], 137.5)
        self.rules.machines["assembling-machine-1"]["speed"] = 1
        faster = self.graph({"iron-plate": 30})
        self.assertAlmostEqual(faster["active_electric_kw"], 68.75)
        self.assertEqual(faster["nodes"]["automation-science-pack"]["count"], 1)

    def test_cycles_coproducts_and_missing_research_have_explicit_blockers(self):
        original = deepcopy(self.rules.document)
        self.rules.recipes["iron-gear-wheel"]["inputs"] = {"automation-science-pack": 1}
        with self.assertRaisesRegex(ValueError, "production cycle"):
            self.graph()
        self.rules.document.clear()
        self.rules.document.update(deepcopy(original))
        self.rules.recipes["automation-science-pack"]["outputs"]["iron-plate"] = 1
        with self.assertRaisesRegex(ValueError, "coproduct"):
            self.graph()
        self.rules.document.clear()
        self.rules.document.update(original)
        with self.assertRaisesRegex(ValueError, "production requires research"):
            production_graph(Automate("automation-science-pack", 10), self.rules, set())


if __name__ == "__main__":
    unittest.main()
