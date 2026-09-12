from collections import Counter
from copy import deepcopy
import gzip
import json
from pathlib import Path
import unittest

from factory_constructor.legacy import CoalDriver, bill
from factory_constructor.procurement import refine


FIXTURE = Path(__file__).resolve().parents[1]/"integration/fixtures/iron-20.json.gz"


class ProcurementRefinementTest(unittest.TestCase):
    def setUp(self):
        evidence = json.loads(gzip.decompress(FIXTURE.read_bytes()))
        observation = evidence["inputs"]["final"]
        self.snapshot, self.rules = CoalDriver.snapshot(observation["capture"], observation["state"])
        self.snapshot.document["inventory"] = {}

    def material(self, requested):
        return bill(self.snapshot, self.rules, requested)

    def test_gather_and_smelting_batches_preserve_inventory_and_pay_extra_fuel(self):
        original = self.material({"iron-plate": 150})
        untouched = deepcopy(original)
        result = refine(original, self.rules)
        self.assertEqual(original, untouched)
        self.assertEqual(result["requested"], {"iron-plate": 150})
        self.assertEqual(result["remaining_inventory"], original["remaining_inventory"])
        self.assertEqual(result["inventory_used"], original["inventory_used"])
        smelts = [s for s in result["steps"] if s["kind"] == "smelt"]
        self.assertEqual([s["crafts"] for s in smelts], [50, 50, 50])
        self.assertEqual([s["processing_seconds"] for s in smelts], [160, 160, 160])
        self.assertEqual([s["coal"] for s in smelts], [4, 4, 4])
        self.assertEqual(result["refinement"]["additional_coal"], 1)
        self.assertEqual(result["gather"]["coal"], 12)
        self.assertEqual([s["quantity"] for s in result["gather_batches"] if s["item"] == "iron-ore"], [100, 50])
        self.assertEqual(result["smelting_machine_seconds"], original["smelting_machine_seconds"])
        gathered = Counter()
        for step in result["steps"]:
            if step["kind"] == "gather":
                self.assertLessEqual(step["quantity"], 100)
                gathered[step["item"]] += step["quantity"]
        self.assertEqual(dict(gathered), result["gather"])

    def test_input_capacity_caps_each_ingredient_and_funds_additional_coal(self):
        original = self.material({"iron-plate": 116})
        result = refine(original, self.rules)
        smelts = [s for s in result["steps"] if s["kind"] == "smelt"]
        self.assertEqual([s["crafts"] for s in smelts], [50, 50, 16])
        self.assertEqual([s["coal"] for s in smelts], [4, 4, 2])
        self.assertEqual(result["gather"]["coal"], original["gather"]["coal"]+1)
        self.assertEqual(result["refinement"]["additional_coal"], 1)
        self.assertEqual(result["refinement"]["smelt_input_limit"], 50)
        self.assertTrue(all(quantity <= 50 for s in smelts for quantity in s["inputs"].values()))
        larger = refine(original, self.rules, smelt_input_limit=100)
        self.assertEqual([s["crafts"] for s in larger["steps"] if s["kind"] == "smelt"], [75, 41])
        self.assertEqual(larger["refinement"]["additional_coal"], 0)
        # Capacity constrains item quantities, not merely recipe craft counts.
        self.rules.recipes["iron-plate"]["inputs"]["iron-ore"] = 2
        doubled = refine(self.material({"iron-plate": 40}), self.rules)
        self.assertEqual([s["crafts"] for s in doubled["steps"] if s["kind"] == "smelt"], [25, 15])

    def test_handcraft_uses_character_time_and_preserves_multi_item_recipe_yield(self):
        self.snapshot.document["inventory"] = {"iron-gear-wheel": 501, "iron-plate": 501}
        original = self.material({"transport-belt": 1002})
        # Character speed remains one even when the default assembler is faster.
        self.rules.machines["assembling-machine-1"]["speed"] = 4
        result = refine(original, self.rules)
        steps = [s for s in result["steps"] if s["kind"] == "handcraft"]
        self.assertEqual([s["crafts"] for s in steps], [480, 21])
        self.assertEqual([s["crafting_seconds"] for s in steps], [240, 10.5])
        self.assertEqual([s["outputs"]["transport-belt"] for s in steps], [960, 42])
        self.assertEqual(sum(s["inputs"]["iron-plate"] for s in steps), 501)
        self.assertEqual(result["handcraft_seconds"], 250.5)
        self.assertEqual(result["gather"], {})

    def test_runtime_smelting_speed_controls_batch_size(self):
        self.rules.machines["stone-furnace"]["speed"] = .5
        original = self.material({"iron-plate": 76})
        result = refine(original, self.rules)
        smelts = [s for s in result["steps"] if s["kind"] == "smelt"]
        self.assertEqual([s["crafts"] for s in smelts], [37, 37, 2])
        self.assertTrue(all(s["processing_seconds"] <= 240 for s in smelts))
        self.assertEqual(sum(s["outputs"]["iron-plate"] for s in smelts), 76)

    def test_refinement_is_idempotent_and_rejects_unbatchable_recipe(self):
        once = refine(self.material({"iron-plate": 150}), self.rules)
        twice = refine(once, self.rules)
        self.assertEqual(twice["steps"], once["steps"])
        self.assertEqual(twice["gather"], once["gather"])
        self.assertEqual(twice["refinement"]["additional_coal"], 0)
        self.rules.recipes["iron-plate"]["seconds"] = 241
        with self.assertRaisesRegex(ValueError, "one recipe craft exceeds"):
            refine(self.material({"iron-plate": 1}), self.rules)


if __name__ == "__main__":
    unittest.main()
