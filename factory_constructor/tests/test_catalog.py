from copy import deepcopy
import gzip
import json
from pathlib import Path
import unittest

from factory_constructor.catalog import ScienceDriver, ScienceSession, policy
from factory_constructor.deployment import record
from factory_constructor.legacy import CoalDriver, bill
from factory_constructor.science_layout import layout
from coal_profile import policy as coal_policy


FIXTURE = Path(__file__).resolve().parents[1]/"integration/fixtures/iron-20.json.gz"


class ScienceCatalogTest(unittest.TestCase):
    def setUp(self):
        evidence = json.loads(gzip.decompress(FIXTURE.read_bytes()))
        self.observation = evidence["inputs"]["final"]
        self.deployment = record(evidence["program"], self.observation, evidence["verification"])

    def upgraded_capture(self):
        capture = deepcopy(self.observation["capture"])
        capture["resolved_rules"]["recipes"]["iron-chest"] = {
            "categories": ["crafting"], "seconds": .5, "enabled": True,
            "inputs": [{"name": "iron-plate", "type": "item", "amount": 8}],
            "outputs": [{"name": "iron-chest", "type": "item", "amount": 1}]}
        capture["resolved_rules"]["items"]["iron-chest"] = "item"
        return capture

    def test_science_policy_extends_selection_without_changing_previous_catalog(self):
        before = deepcopy(coal_policy().document)
        selected = policy()
        self.assertEqual(selected.recipes["iron-chest"], {"category": "crafting"})
        self.assertEqual(selected.document["default_recipes"]["iron-chest"], "iron-chest")
        self.assertEqual(selected.document["items"]["iron-chest"], "item")
        self.assertEqual(coal_policy().document, before)
        self.assertNotIn("iron-chest", before["recipes"])
        self.assertIn("iron-chest", ScienceSession.observer_builder.keywords["policy"].recipes)

    def test_upgraded_snapshot_imports_native_iron_chest_mechanics(self):
        capture = self.upgraded_capture()
        snapshot, rules = ScienceDriver.snapshot(capture, self.observation["state"])
        self.assertEqual(rules.recipes["iron-chest"]["inputs"], {"iron-plate": 8})
        self.assertEqual(rules.recipes["iron-chest"]["seconds"], .5)
        self.assertTrue(rules.unlocked("iron-chest", snapshot.researched))
        # The policy does not replace mechanics with an assumed vanilla cost.
        capture["resolved_rules"]["recipes"]["iron-chest"]["inputs"][0]["amount"] = 9
        _, changed = ScienceDriver.snapshot(capture, self.observation["state"])
        self.assertEqual(changed.recipes["iron-chest"]["inputs"], {"iron-plate": 9})

    def test_iron_storage_replaces_only_new_chests_and_reduces_wood_procurement(self):
        old_snapshot, old_rules = CoalDriver.snapshot(self.observation["capture"], self.observation["state"])
        old_design = layout(self.observation, self.deployment, old_rules, 10)
        self.observation["capture"] = self.upgraded_capture()
        snapshot, rules = ScienceDriver.snapshot(self.observation["capture"], self.observation["state"])
        design = layout(self.observation, self.deployment, rules, 10)
        self.assertEqual(design["bill"]["iron-chest"], 2)
        self.assertNotIn("wooden-chest", design["bill"])
        self.assertEqual(design["output"], old_design["output"])
        self.assertEqual(design["connections"], old_design["connections"])
        self.assertEqual(design["mining_areas"], old_design["mining_areas"])
        for address in self.deployment["design"]["output"]["addresses"]:
            self.assertEqual(self.deployment["entities"][address]["name"], "wooden-chest")
        old_bill = bill(old_snapshot, old_rules, old_design["bill"])
        new_bill = bill(snapshot, rules, design["bill"])
        self.assertEqual(old_bill["gather"]["wood"]-new_bill["gather"]["wood"], 4)
        self.assertEqual(new_bill["gather"]["iron-ore"]-old_bill["gather"]["iron-ore"], 16)

    def test_original_capture_keeps_original_policy_and_wooden_storage(self):
        snapshot, rules = ScienceDriver.snapshot(self.observation["capture"], self.observation["state"])
        _, original_rules = CoalDriver.snapshot(self.observation["capture"], self.observation["state"])
        self.assertEqual(rules.document, original_rules.document)
        self.assertEqual(layout(self.observation, self.deployment, rules, 10)["bill"]["wooden-chest"], 2)


if __name__ == "__main__":
    unittest.main()
