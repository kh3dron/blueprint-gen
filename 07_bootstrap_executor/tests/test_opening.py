"""Real opening captures and failures that must not become successful execution."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from opening import procurement, executable, observed_snapshot, verify_result, check_replay
from advisor_core.planner import next_step
from advisor_core.production import analyze, completion


class OpeningTest(unittest.TestCase):
    def fixture(self, name):
        return json.loads((HERE / "integration/fixtures" / f"{name}.json").read_text())

    def test_real_start_produces_the_advisors_finite_steam_power_bill(self):
        capture, state = self.fixture("initial-capture"), self.fixture("initial-state")
        before = deepcopy(state)
        p = procurement(capture, state)
        self.assertEqual(p["materials"]["requested"], {"iron-plate": 50})
        self.assertEqual(p["materials"]["inventory_used"], {"stone-furnace": 1})
        self.assertEqual(p["materials"]["gather"], {"iron-ore": 50, "coal": 4})
        self.assertEqual(p["advisor_action"]["technology"], "steam-power")
        self.assertEqual(state, before)

    def test_declarative_site_comes_from_observation_and_pays_the_starter_bill(self):
        p = self.fixture("instructions")
        compiled = executable(p, p["placement_state"])
        self.assertEqual(compiled["design"], p["design"])
        self.assertEqual(compiled["change"]["bill"], {"stone-furnace": 1})
        self.assertEqual(compiled["placement"]["position"], {"x": -2, "y": -14})

    def test_missing_gathered_stock_furnace_or_build_site_refuses_execution(self):
        for kind in ("ore", "furnace", "site"):
            p = self.fixture("instructions")
            state = deepcopy(p["placement_state"])
            if kind == "ore":
                state["inventory"]["iron-ore"] -= 1
            elif kind == "furnace":
                del state["inventory"]["stone-furnace"]
            else:
                state["furnace_sites"] = []
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                executable(p, state)

    def test_short_or_obstructed_deposits_do_not_create_gathering_instructions(self):
        for kind in ("short", "obstructed"):
            c = self.fixture("initial-capture")
            for resource in c["survey"]["resources"]:
                if resource["prototype"] == "iron-ore":
                    if kind == "short":
                        resource["amount"] = 1
                    else:
                        resource["standable"] = False
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                procurement(c, self.fixture("initial-state"))

    def test_observations_must_describe_the_same_actual_checkpoint(self):
        for field, value in (("tick", 999), ("map_seed", 9), ("produced_iron", 5),
                             ("researched", ["steam-power"]), ("position", {"x": 10, "y": 10})):
            state = self.fixture("initial-state")
            state[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "different checkpoints"):
                observed_snapshot(self.fixture("initial-capture"), state)

    def test_actual_run_conserves_items_and_observes_delayed_research(self):
        r = verify_result(self.fixture("execution"), self.fixture("instructions"), self.fixture("initial-state"))
        self.assertEqual(r["final_inventory"], {"burner-mining-drill": 1, "wood": 1, "iron-plate": 58})
        self.assertEqual(r["smelting_ticks"], 9602)
        self.assertEqual(r["trigger_wait_ticks"], 19)
        self.assertTrue(r["steam_power_observed"])
        self.assertFalse(r["goal_complete"])

    def test_shifted_iron_patch_changes_the_site_and_route_with_the_same_costs(self):
        p, result = self.fixture("shifted-instructions"), self.fixture("shifted-execution")
        r = verify_result(result, p, self.fixture("initial-state"))
        self.assertEqual(r["furnace_position"], {"x": 11, "y": 1})
        self.assertGreater(r["walking_distance"], 50)
        self.assertEqual(r["mined"], {"iron-ore": 50, "coal": 4})

    def test_false_inventory_depletion_transfers_and_unlocks_are_rejected(self):
        for kind in ("inventory", "depletion", "transfer", "research", "crafts", "duplicate", "time"):
            result = self.fixture("execution")
            if kind == "inventory":
                result["final"]["inventory"]["iron-plate"] += 1
            elif kind == "depletion":
                result["mining"][1]["depleted"] -= 1
            elif kind == "transfer":
                result["transfers"][0]["removed"] = 0
            elif kind == "research":
                result["final"]["researched"] = []
            elif kind == "crafts":
                result["furnace"]["products_finished"] = 0
            elif kind == "duplicate":
                result["paid_furnaces"] = 2
            else:
                result["smelting_ticks"] = 10
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                verify_result(result, self.fixture("instructions"), self.fixture("initial-state"))

    def test_empty_furnace_is_retained_without_inventing_recipe_or_production(self):
        capture, state = self.fixture("final-capture"), self.fixture("execution")["final"]
        snapshot, rules = observed_snapshot(capture, state)
        self.assertEqual(len(snapshot.machines), 1)
        self.assertIsNone(snapshot.machines[0]["recipe"])
        self.assertTrue(snapshot.machines[0]["built"])
        self.assertEqual(analyze(snapshot, rules)["goal_fraction"], 0)
        self.assertFalse(completion(snapshot, rules)["complete"])
        action = next_step(snapshot, rules)
        self.assertEqual(action["technology"], "electronics")
        self.assertEqual(action["construction"]["gather"], {"copper-ore": 10, "coal": 1})
        self.assertFalse(any(s["kind"] == "place" for s in action["construction"]["steps"]))
        self.assertNotIn("stone-furnace", action["construction"]["gather"])

    def test_ghost_furnace_cannot_supply_the_next_smelting_station(self):
        c, state = self.fixture("final-capture"), self.fixture("execution")["final"]
        c["machines"][0]["built"] = False
        snapshot, rules = observed_snapshot(c, state)
        action = next_step(snapshot, rules)
        self.assertTrue(any(s["kind"] == "place" for s in action["construction"]["steps"]))
        self.assertEqual(action["construction"]["gather"]["stone"], 5)

    def test_different_or_missing_fresh_route_cannot_validate_replay(self):
        first = {"states": {"initial-state": self.fixture("initial-state")}, "captures": [self.fixture("initial-capture")]}
        receipts = self.fixture("receipts")
        stage = {**first, "receipts": deepcopy(receipts)}
        check_replay(stage, first, receipts)
        stage["receipts"][0]["generation"] += 1
        with self.assertRaisesRegex(ValueError, "fresh native route"):
            check_replay(stage, first, receipts)
        stage["receipts"] = []
        with self.assertRaisesRegex(ValueError, "every consumed receipt"):
            check_replay(stage, first, receipts)


if __name__ == "__main__":
    unittest.main()
