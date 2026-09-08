"""Behavioral checks for feasibility, bootstrap advice, and evidence boundaries."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from advisor_core.construction import bill
from advisor_core.linear import maximize
from advisor_core.model import Snapshot
from advisor_core.planner import next_step
from advisor_core.production import analyze, completion
from advisor_core.rules import Rules


class AdvisorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = Rules.load()

    def document(self, name="ready"):
        return json.loads((HERE / "examples" / f"{name}.json").read_text())

    def snapshot(self, name="ready", **changes):
        doc = self.document(name)
        doc.update(changes)
        return Snapshot.from_dict(doc, self.rules)

    def test_empty_factory_has_zero_flow(self):
        self.assertEqual(analyze(self.snapshot("start"), self.rules)["goal_fraction"], 0)

    def test_stockpile_is_not_an_infinite_supply(self):
        s = self.snapshot("starved", inventory={"iron-ore": 100000, "automation-science-pack": 100000})
        self.assertEqual(analyze(s, self.rules)["goal_fraction"], 0)
        self.assertFalse(completion(s, self.rules)["complete"])

    def test_missing_furnace_fuel_stops_science(self):
        s = self.snapshot("missing-coal")
        self.assertEqual(analyze(s, self.rules)["goal_fraction"], 0)
        move = next_step(s, self.rules)
        self.assertEqual(move["item"], "coal")
        self.assertAlmostEqual(move["target_per_min"], 2.16)

    def test_resource_bound_and_monotonicity(self):
        for iron_per_min in (0, 1, 5, 10, 15, 20, 30):
            with self.subTest(iron=iron_per_min):
                d = self.document()
                d["supplies_per_s"]["iron-ore"] = iron_per_min / 60
                result = analyze(Snapshot.from_dict(d, self.rules), self.rules)
                self.assertAlmostEqual(result["goal_fraction"], min(1, iron_per_min / 20))
                self.assertTrue(all(v >= -1e-7 for v in result["net_per_s"].values()))

    def test_shared_inputs_are_not_counted_twice(self):
        s = self.snapshot(goals_per_min={"automation-science-pack": 10, "iron-gear-wheel": 10})
        # Science plus exported gears require 40 plates/min; the source supplies 20.
        self.assertAlmostEqual(analyze(s, self.rules)["goal_fraction"], 0.5)

    def test_custom_goal_replaces_science_ladder(self):
        s = self.snapshot(goals_per_min={"iron-gear-wheel": 30})
        self.assertAlmostEqual(analyze(s, self.rules)["goal_fraction"], 1 / 3)
        step = next_step(s, self.rules)
        self.assertEqual(step["item"], "iron-ore")
        self.assertAlmostEqual(step["target_per_min"], 60)

    def test_labs_reserve_power_before_crafting(self):
        result = analyze(self.snapshot("brownout"), self.rules)
        # 60 kW lab, 125 kW science, 12.5 kW gears at the target rate.
        self.assertAlmostEqual(result["goal_fraction"], 40 / 137.5)
        self.assertAlmostEqual(result["electric_kw"], 100)
        self.assertEqual(next_step(self.snapshot("brownout"), self.rules)["kind"], "power")

    def test_power_advice_uses_installed_machine_tier(self):
        d = self.document()
        d["researched"] = self.rules.research_path("automation-3", set())
        d["machines"][3]["prototype"] = "assembling-machine-3"
        d["power"]["available_kw"] = 250
        step = next_step(Snapshot.from_dict(d, self.rules), self.rules)
        self.assertEqual(step["kind"], "power")
        self.assertAlmostEqual(step["active_load_lower_bound_kw"], 322.5)

    def test_research_needs_power_for_every_observed_active_lab(self):
        d = self.document()
        d["researched"].remove("automation")
        d["machines"] = [dict(d["machines"][-1], count=2)]
        d["power"]["available_kw"] = 100
        step = next_step(Snapshot.from_dict(d, self.rules), self.rules)
        self.assertEqual(step["kind"], "power")

    def test_impossible_lab_power_is_not_reported_as_a_measurement_problem(self):
        d = self.document("observed")
        d["goals_per_min"] = {"iron-plate": 1}
        d["supplies_per_s"] = {"iron-plate": 1}
        d["power"]["available_kw"] = 30
        s = Snapshot.from_dict(d, self.rules)
        self.assertFalse(completion(s, self.rules)["complete"])
        self.assertEqual(next_step(s, self.rules)["kind"], "power")

    def test_ghosts_supply_no_capacity(self):
        s = self.snapshot("ghosts")
        self.assertEqual(analyze(s, self.rules)["goal_fraction"], 0)
        step = next_step(s, self.rules)
        self.assertEqual((step["kind"], step["count"]), ("build", 2))

    def test_partial_build_only_requests_missing_machine(self):
        d = self.document()
        d["machines"][3]["count"] = 1
        step = next_step(Snapshot.from_dict(d, self.rules), self.rules)
        self.assertEqual((step["kind"], step["prototype"], step["count"]), ("build", "assembling-machine-1", 1))

    def test_disconnected_line_is_repaired_before_expanding(self):
        step = next_step(self.snapshot("disconnected"), self.rules)
        self.assertEqual((step["kind"], step["machine_id"]), ("repair", "red"))

    def test_output_blockage_stops_the_complete_recipe(self):
        d = self.document("oil-coproducts")
        d["machines"][0]["output_open"] = False
        s = Snapshot.from_dict(d, self.rules)
        self.assertEqual(analyze(s, self.rules)["goal_fraction"], 0)

    def test_all_oil_coproducts_are_credited(self):
        result = analyze(self.snapshot("oil-coproducts"), self.rules)
        self.assertAlmostEqual(result["goal_fraction"], 1)
        self.assertAlmostEqual(result["production_per_s"]["heavy-oil"], 5)
        self.assertAlmostEqual(result["production_per_s"]["light-oil"], 9)
        self.assertAlmostEqual(result["production_per_s"]["petroleum-gas"], 11)
        self.assertAlmostEqual(result["consumption_per_s"]["crude-oil"], 20)

    def test_locked_installed_recipe_has_zero_activity(self):
        s = self.snapshot("oil-coproducts", researched=[])
        result = analyze(s, self.rules)
        self.assertEqual(result["goal_fraction"], 0)
        self.assertIn("recipe locked", result["disabled"][0]["reason"])

    def test_predictions_do_not_complete_a_goal(self):
        s = self.snapshot()
        self.assertAlmostEqual(analyze(s, self.rules)["goal_fraction"], 1)
        self.assertFalse(completion(s, self.rules)["complete"])
        self.assertEqual(next_step(s, self.rules)["kind"], "verify")

    def test_fresh_observation_completes_the_goal(self):
        s = self.snapshot("observed")
        self.assertTrue(completion(s, self.rules)["complete"])
        self.assertEqual(next_step(s, self.rules)["kind"], "done")

    def test_old_measurement_cannot_verify_new_revision(self):
        s = self.snapshot("observed", revision="changed")
        self.assertFalse(completion(s, self.rules)["complete"])

    def test_stale_measurement_cannot_verify_goal(self):
        self.assertFalse(completion(self.snapshot("observed", tick=9000), self.rules)["complete"])

    def test_latest_bad_measurement_overrides_earlier_good_measurement(self):
        d = self.document("observed")
        d["tick"] = 7500
        sample = deepcopy(d["observations"][0])
        sample.update(start_tick=3900, end_tick=7500, produced={"automation-science-pack": 2})
        d["observations"].append(sample)
        self.assertFalse(completion(Snapshot.from_dict(d, self.rules), self.rules)["complete"])

    def test_handcrafts_and_short_windows_do_not_verify(self):
        for field, value in (("source", "handcrafted"), ("start_tick", 7000)):
            with self.subTest(field=field):
                d = self.document("observed")
                d["observations"][0][field] = value
                self.assertFalse(completion(Snapshot.from_dict(d, self.rules), self.rules)["complete"])

    def test_measurement_does_not_override_current_loss_of_supply(self):
        s = self.snapshot("observed", supplies_per_s={})
        self.assertFalse(completion(s, self.rules)["complete"])

    def test_lab_must_be_built_and_powered(self):
        d = self.document("observed")
        d["machines"][-1]["built"] = False
        s = Snapshot.from_dict(d, self.rules)
        self.assertFalse(completion(s, self.rules)["complete"])
        self.assertEqual(next_step(s, self.rules)["kind"], "prepare_lab")

    def test_initial_trigger_requires_new_production_and_real_fuel(self):
        s = self.snapshot("start")
        step = next_step(s, self.rules)
        self.assertEqual(step["technology"], "steam-power")
        construction = step["construction"]
        self.assertEqual(construction["gather"], {"iron-ore": 50, "coal": 4})
        self.assertEqual(construction["smelting_machine_seconds"], 160)
        self.assertEqual(construction["inventory_used"], {"stone-furnace": 1})
        self.assertEqual(construction["remaining_inventory"]["iron-plate"], 8)

    def test_observed_trigger_counter_does_not_mark_research_done(self):
        s = self.snapshot("start", crafted={"iron-plate": 50})
        self.assertEqual(next_step(s, self.rules)["kind"], "observe")
        self.assertEqual(s.researched, set())

    def test_trigger_sequence_includes_copper_and_lab_bootstrap(self):
        s = self.snapshot("start", researched=["steam-power"], crafted={"iron-plate": 50})
        self.assertEqual(next_step(s, self.rules)["technology"], "electronics")
        s = self.snapshot("start", researched=["steam-power", "electronics"],
                          crafted={"iron-plate": 50, "copper-plate": 10})
        self.assertEqual(next_step(s, self.rules)["technology"], "automation-science-pack")
        self.assertEqual(next_step(s, self.rules)["construction"]["requested"], {"lab": 1})

    def test_research_uses_remaining_units_and_stockpiled_packs(self):
        d = self.document()
        d["researched"].remove("automation")
        d["machines"] = [d["machines"][-1]]
        d["research_units_completed"] = {"automation": 3}
        d["inventory"] = {"automation-science-pack": 5, "copper-plate": 2, "iron-gear-wheel": 2}
        step = next_step(Snapshot.from_dict(d, self.rules), self.rules)
        self.assertEqual(step["kind"], "research")
        self.assertEqual(step["science_required"], {"automation-science-pack": 7})
        crafts = [x for x in step["construction"]["steps"] if x.get("recipe") == "automation-science-pack"]
        self.assertEqual(crafts[0]["crafts"], 2)

    def test_batch_rounding_keeps_surplus(self):
        s = self.snapshot(inventory={"copper-plate": 2})
        result = bill(s, self.rules, {"copper-cable": 3})
        self.assertEqual(result["steps"][0]["crafts"], 2)
        self.assertEqual(result["remaining_inventory"], {"copper-cable": 1})
        self.assertEqual(result["inventory_used"], {"copper-plate": 2})

    def test_shared_construction_inventory_is_reserved_once(self):
        s = self.snapshot(inventory={"iron-plate": 5})
        result = bill(s, self.rules, {"iron-gear-wheel": 1, "transport-belt": 1})
        self.assertEqual(result["gather"], {})
        self.assertEqual(result["inventory_used"], {"iron-plate": 5})
        self.assertEqual(result["remaining_inventory"], {"transport-belt": 1})

    def test_starter_furnace_bill_reuses_inventory(self):
        s = self.snapshot("start", inventory={"stone-furnace": 1, "stone": 5})
        result = bill(s, self.rules, {"stone-furnace": 2})
        self.assertEqual(result["gather"], {})
        self.assertEqual(result["inventory_used"], {"stone-furnace": 1, "stone": 5})
        self.assertEqual(result["steps"][0]["crafts"], 1)

    def test_two_stone_furnaces_are_required_for_20_plates_per_min(self):
        d = self.document()
        d["goals_per_min"] = {"iron-plate": 20}
        d["machines"] = [dict(d["machines"][0], count=1)]
        d["require_lab"] = False
        step = next_step(Snapshot.from_dict(d, self.rules), self.rules)
        self.assertEqual((step["prototype"], step["count"]), ("stone-furnace", 1))

    def test_analysis_and_planning_are_read_only(self):
        s = self.snapshot("start")
        before = s.to_dict()
        analyze(s, self.rules)
        next_step(s, self.rules)
        bill(s, self.rules, {"lab": 1})
        self.assertEqual(s.to_dict(), before)

    def test_recipe_hardware_and_selection_survive_save_load(self):
        s = self.snapshot("oil-coproducts", selected_recipes={"petroleum-gas": "advanced-oil-processing"})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            s.save(path)
            loaded = Snapshot.load(path, self.rules)
        self.assertEqual(loaded.to_dict(), s.to_dict())
        self.assertEqual(loaded.machines[0]["recipe"], "advanced-oil-processing")

    def test_versions_mods_and_dataset_hash_are_enforced(self):
        for key, value in (("ruleset_sha256", "wrong"), ("factorio_version", "2.0.73"),
                           ("mods", {"base": "2.1.14", "space-age": "2.1.14"}), ("surface", "vulcanus")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.snapshot(**{key: value})

    def test_space_age_recipe_is_not_silently_selected(self):
        self.assertNotIn("simple-coal-liquefaction", self.rules.recipes)
        with self.assertRaises(ValueError):
            self.snapshot(selected_recipes={"heavy-oil": "simple-coal-liquefaction"})

    def test_unknown_unlock_is_an_error(self):
        with self.assertRaises(ValueError):
            self.rules.unlock_path("unknown-recipe", set())

    def test_bad_counts_rates_and_identifiers_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "JSON object"):
            Snapshot.from_dict([], self.rules)
        for change in ({"goals_per_min": {"iron-plate": -1}}, {"supplies_per_s": {"iron-ore": float('nan')}},
                       {"inventory": {"coal": 0.5}}, {"researched": ["automation"]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.snapshot(**change)
        for value in (0, -1, 1.5, True):
            d = self.document()
            d["machines"][0]["count"] = value
            with self.subTest(count=value), self.assertRaises(ValueError):
                Snapshot.from_dict(d, self.rules)
        d = self.document()
        d["machines"][0]["id"] = d["machines"][1]["id"]
        with self.assertRaises(ValueError):
            Snapshot.from_dict(d, self.rules)

    def test_cli_runs_from_another_directory_without_mutating_snapshot(self):
        source = HERE / "examples" / "ready.json"
        before = source.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(HERE / "advisor.py"), "next", str(source), "--json"],
                                    cwd=directory, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["kind"], "verify")
        self.assertEqual(source.read_bytes(), before)

    def test_cli_rejects_wrong_profile_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrong.json"
            d = self.document()
            d["ruleset_sha256"] = "wrong"
            path.write_text(json.dumps(d))
            result = subprocess.run([sys.executable, str(HERE / "advisor.py"), "next", str(path)],
                                    text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("does not match", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


class LinearTest(unittest.TestCase):
    def test_shared_capacity(self):
        result = maximize([1, 1], [[1, 0], [0, 1], [1, 1]], [2, 3, 4])
        self.assertAlmostEqual(sum(result), 4)
        self.assertLessEqual(result[0], 2)
        self.assertLessEqual(result[1], 3)

    def test_producer_consumer_balance_with_zero_rhs(self):
        # x supplies two inputs per cycle; y consumes three. Capacity x=6 -> y=4.
        result = maximize([0, 1], [[1, 0], [-2, 3]], [6, 0])
        self.assertAlmostEqual(result[1], 4)

    def test_degenerate_constraints(self):
        result = maximize([1, 1], [[1, 0], [1, 0], [0, 1], [1, 1]], [0, 0, 2, 2])
        self.assertAlmostEqual(result[0], 0)
        self.assertAlmostEqual(result[1], 2)

    def test_unbounded_and_negative_rhs_are_explicit(self):
        with self.assertRaisesRegex(ValueError, "unbounded"):
            maximize([1], [[-1]], [0])
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            maximize([1], [[1]], [-1])


if __name__ == "__main__":
    unittest.main()
