from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from coal_plan import CoalLoop
from coal_profile import CoalDriver, policy
from advisor_core.rules import Rules
from verify_coal import verify


class CoalSupplyTests(unittest.TestCase):
    def setUp(self):
        self.fixtures = HERE / "integration/fixtures"
        def read(name): return json.loads((self.fixtures / name).read_text())
        self.final = read("coal-final-observation.json")
        self.actions = read("actions.json")
        self.design = read("coal-design.json")
        self.windows = read("coal-windows.json")
        self.reconciliation = read("coal-reconciliation.json")
        self.warmup = read("coal-warmup.json")
        self.opening = read("final-observation.json")
        self.events = [json.loads(s) for s in (self.fixtures / "player-crafts.jsonl").read_text().splitlines()]

    def verify(self):
        return verify(self.final, self.actions, self.design, self.windows,
                      self.reconciliation, self.warmup, self.opening, self.events)

    def synchronize_windows(self):
        """Keep duplicated receipts consistent so each test reaches its intended check."""
        waits = [a for a in self.actions if a["request"]["op"] == "wait_coal"]
        for action, window in zip(waits, [self.warmup, *self.windows]):
            action["outcome"]["value"] = deepcopy(window)

    def test_verified_physical_delivery_and_paid_costs(self):
        result = self.verify()
        self.assertEqual(result["idle_seconds"], 300)
        self.assertGreaterEqual(result["minimum_observed_per_min"], 10)
        self.assertEqual(result["additional_gathered"], {"wood": 4, "iron-ore": 18, "coal": 7})
        self.assertEqual(result["native_cursor_builds_added"], 11)
        self.assertTrue(result["self_fueling_observed"])
        self.assertFalse(result["goal_complete"])

    def test_runtime_profile_does_not_change_older_catalog(self):
        self.assertNotIn("burner-inserter", Rules.load().recipes)
        self.assertEqual(policy().recipes["burner-inserter"], {"category": "crafting"})
        snapshot, rules = CoalDriver.snapshot(self.final["capture"], self.final["state"])
        self.assertEqual(rules.recipes["burner-inserter"]["inputs"], {"iron-plate": 1, "iron-gear-wheel": 1})
        self.assertEqual(snapshot.document["supplies_per_s"], {})

    def test_module_is_translated_from_observed_patch(self):
        self.assertEqual(CoalLoop.from_survey(self.opening["capture"]).document(), self.design)
        shifted = json.loads((self.fixtures / "shifted-design.json").read_text())
        actual = json.loads((self.fixtures / "shifted-final-coal.json").read_text())
        for before, after in zip(self.design["placements"], shifted["placements"]):
            self.assertEqual(before["address"], after["address"])
            self.assertEqual(after["position"], {"x": before["position"]["x"]-8, "y": before["position"]["y"]+12})
        from verify_coal import check_sample
        check_sample(actual, shifted)
        report = json.loads((self.fixtures / "shifted-verification.json").read_text())
        self.assertTrue(report["self_fueling_observed"])

    def test_partial_or_boundary_patch_is_refused(self):
        capture = deepcopy(self.opening["capture"])
        coal = next(r for r in capture["survey"]["resources"] if r["prototype"] == "coal")
        capture["survey"]["resources"].remove(coal)
        with self.assertRaisesRegex(ValueError, "complete coal rectangle"):
            CoalLoop.from_survey(capture)
        capture = deepcopy(self.opening["capture"])
        capture["survey"]["area"][0][0] = -24
        with self.assertRaisesRegex(ValueError, "boundary"):
            CoalLoop.from_survey(capture)

    def test_player_transfer_during_measurement_is_rejected(self):
        self.final["transfers"].append({"tick": self.windows[2]["before"]["tick"]+1,
                                       "item": "coal", "count": 1, "removed": 1, "inserted": 1})
        with self.assertRaisesRegex(ValueError, "transfer during"):
            self.verify()

    def test_disconnected_return_is_rejected(self):
        sample = self.windows[0]["after"]
        next(e for e in sample["entities"] if e["address"] == "coal.refuel")["drop_target"] = "wrong-machine"
        self.synchronize_windows()
        with self.assertRaisesRegex(ValueError, "endpoints are disconnected"):
            self.verify()

    def test_production_without_matching_depletion_is_rejected(self):
        self.windows[0]["after"]["produced"] += 1
        self.synchronize_windows()
        with self.assertRaisesRegex(ValueError, "deposit depletion"):
            self.verify()

    def test_stored_coal_without_new_delivery_is_rejected(self):
        first = self.windows[0]
        chest = next(e for e in first["after"]["entities"] if e["address"] == "coal.chest")
        before = next(e for e in first["before"]["entities"] if e["address"] == "coal.chest")
        delta = chest["contents"]["coal"]-before["contents"]["coal"]
        chest["contents"]["coal"] -= delta
        first["after"]["loose_coal"] -= delta
        self.synchronize_windows()
        with self.assertRaisesRegex(ValueError, "delivery fell below"):
            self.verify()

    def test_paid_placement_and_tree_event_are_required(self):
        self.final["state"]["tree_events"][0]["products"]["wood"] += 1
        with self.assertRaisesRegex(ValueError, "tree yield"):
            self.verify()
        self.setUp()
        self.final["state"]["player_build_events"] = [e for e in self.final["state"]["player_build_events"] if e["name"] != "burner-inserter"]
        with self.assertRaisesRegex(ValueError, "native event"):
            self.verify()

    def test_unpaid_inventory_and_missing_craft_event_are_rejected(self):
        self.final["state"]["inventory"]["iron-plate"] = 1
        with self.assertRaisesRegex(ValueError, "final player inventory"):
            self.verify()
        self.setUp()
        self.events = [e for e in self.events if e["recipe"] != "burner-inserter"]
        with self.assertRaisesRegex(ValueError, "native crafting outputs"):
            self.verify()

    def test_seed_energy_must_be_outlasted(self):
        # If the runtime drill used almost no energy, this same short run could
        # be explained entirely by startup fuel and must not prove self-fueling.
        for sample in (self.windows[-1]["after"], self.final["state"]["coal"]):
            next(e for e in sample["entities"] if e["address"] == "coal.drill")["energy_usage_j_per_tick"] = .1
        self.synchronize_windows()
        with self.assertRaisesRegex(ValueError, "seed-energy bound"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
