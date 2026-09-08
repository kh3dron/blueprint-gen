"""Real engine captures plus deliberate edits that must not become trusted facts."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from advisor_core.game_import import import_capture, review_template, runtime_rules
from advisor_core.model import Snapshot
from advisor_core.planner import next_step
from advisor_core.production import analyze, completion, operational_labs
from advisor_core.rules import Rules


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.capture = json.loads((HERE / "integration/fixtures/stable.json").read_text())

    def reviewed(self):
        review = review_template(self.capture)
        review.update(inventory={}, supplies_per_s={}, available_power_kw=10000)
        for settings in review["machines"].values():
            settings.update(connected=False, output_open=True)
        return review

    def test_engine_capture_uses_resolved_profile_and_real_counters(self):
        snapshot, rules = import_capture(self.capture)
        self.assertEqual(rules.document["factorio_version"], "2.1.16")
        self.assertNotEqual(rules.digest, Rules.load().digest)
        self.assertEqual(rules.machines["assembling-machine-1"]["electric_kw"], 75)
        self.assertEqual(rules.machines["stone-furnace"]["fuel_kw"], 90)
        self.assertEqual(rules.technologies["automation"]["seconds"], 10)
        self.assertEqual(snapshot.document["observations"][0]["produced"],
                         {"automation-science-pack": 12, "copper-cable": 120, "iron-gear-wheel": 52})

    def test_runtime_craft_trigger_filter_becomes_a_plannable_item_name(self):
        before = deepcopy(self.capture)
        rules = runtime_rules(self.capture)
        self.assertEqual(rules.technologies["steam-power"]["trigger"],
                         {"type": "craft-item", "item": "iron-plate", "count": 50})
        self.assertEqual(rules.technologies["automation-science-pack"]["prerequisites"],
                         ["steam-power", "electronics"])
        self.assertEqual(self.capture, before)

    def test_trigger_quality_and_comparator_constraints_are_not_discarded(self):
        for item in ({"name": "iron-plate", "quality": "rare"},
                     {"name": "iron-plate", "comparator": ">"}, {"name": "unknown"}):
            self.capture["resolved_rules"]["technologies"]["steam-power"]["trigger"]["item"] = item
            with self.subTest(item=item), self.assertRaises(ValueError):
                runtime_rules(self.capture)

    def test_missing_observations_precede_repair_and_completion(self):
        snapshot, rules = import_capture(self.capture)
        step = next_step(snapshot, rules)
        self.assertEqual(step["kind"], "observe")
        self.assertTrue(step["observation_gaps"])
        self.assertFalse(completion(snapshot, rules)["complete"])
        self.assertEqual(snapshot.document["supplies_per_s"], {})

    def test_finite_stock_and_actual_production_do_not_create_supply(self):
        review = self.reviewed()
        review["inventory"] = {"automation-science-pack": 100000, "copper-plate": 100000}
        snapshot, rules = import_capture(self.capture, review)
        self.assertFalse(snapshot.document["observation_gaps"])
        self.assertEqual(analyze(snapshot, rules)["goal_fraction"], 0)
        self.assertFalse(completion(snapshot, rules)["complete"])

    def test_full_output_overrides_operator_review(self):
        snapshot, _ = import_capture(self.capture, self.reviewed())
        gear = next(m for m in snapshot.machines if m.get("recipe") == "iron-gear-wheel")
        self.assertFalse(gear["output_open"])

    def test_engine_recipe_change_is_rejected(self):
        capture = json.loads((HERE / "integration/fixtures/recipe-change.json").read_text())
        snapshot, _ = import_capture(capture)
        self.assertEqual(snapshot.document["observations"], [])
        self.assertIn("machine configuration changed", " ".join(snapshot.document["provenance"]["notes"]))

    def test_stale_review_cannot_follow_a_new_capture(self):
        review = self.reviewed()
        self.capture["tick"] += 1
        with self.assertRaisesRegex(ValueError, "another capture"):
            import_capture(self.capture, review)

    def test_review_changes_bind_a_new_snapshot_revision(self):
        review = self.reviewed()
        first, _ = import_capture(self.capture, review)
        review["available_power_kw"] = 500
        second, _ = import_capture(self.capture, review)
        self.assertNotEqual(first.document["revision"], second.document["revision"])
        self.assertEqual(second.document["observations"][0]["revision"], second.document["revision"])

    def test_profile_exporter_and_catalog_mismatches_are_rejected(self):
        variants = [
            {"factorio_version": "2.0.72"}, {"export_schema_version": 2},
            {"exporter": {"name": "blueprint-gen-observer", "version": "9.0.0"}},
            {"active_mods": {"base": "2.1.16", "blueprint-gen-observer": "0.1.0", "space-age": "2.1.16"}},
            {"active_mods": {"base": "2.1.14", "blueprint-gen-observer": "0.1.0"}},
            {"scope": {"surface_name": "vulcanus"}},
        ]
        for change in variants:
            with self.subTest(change=change), self.assertRaises(ValueError):
                import_capture({**self.capture, **change})
        del self.capture["resolved_rules"]["recipes"]["iron-plate"]
        with self.assertRaisesRegex(ValueError, "catalog"):
            import_capture(self.capture)

    def test_changed_runtime_mechanics_are_not_replaced_with_old_constants(self):
        self.capture["resolved_rules"]["machines"]["assembling-machine-1"]["electric_kw"] = 85
        _, rules = import_capture(self.capture)
        self.assertEqual(rules.machines["assembling-machine-1"]["electric_kw"], 85)

    def test_stochastic_outputs_and_unknown_prerequisites_are_rejected(self):
        altered = deepcopy(self.capture)
        altered["resolved_rules"]["recipes"]["copper-cable"]["outputs"][0]["probability"] = 0.5
        with self.assertRaisesRegex(ValueError, "stochastic"):
            import_capture(altered)
        self.capture["resolved_rules"]["technologies"]["automation"]["prerequisites"].append("new-technology")
        with self.assertRaisesRegex(ValueError, "prerequisites"):
            import_capture(self.capture)

    def test_modifiers_and_quality_cannot_enter_normal_profile(self):
        for change in ({"quality": "rare"}, {"recipe_quality": "rare"}, {"speed_bonus": 0.2},
                       {"productivity_bonus": 0.1}, {"modules": [{"name": "speed-module", "count": 1}]}):
            altered = deepcopy(self.capture)
            altered["machines"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                import_capture(altered)

    def test_multiple_networks_and_duplicate_entities_are_rejected(self):
        altered = deepcopy(self.capture)
        altered["machines"][0]["electric_network_id"] = 2
        with self.assertRaisesRegex(ValueError, "multiple electric"):
            import_capture(altered)
        self.capture["machines"].append(deepcopy(self.capture["machines"][0]))
        with self.assertRaisesRegex(ValueError, "unique"):
            import_capture(self.capture)

    def test_no_power_status_overrides_residual_energy(self):
        self.capture["machines"][0].update(status="no_power", energy_j=1)
        snapshot, _ = import_capture(self.capture, self.reviewed())
        self.assertFalse(snapshot.machines[0]["powered"])

    def test_inactive_lab_cannot_support_research(self):
        lab = next(m for m in self.capture["machines"] if m["prototype"] == "lab")
        lab["active"] = False
        review = self.reviewed()
        review["machines"][lab["id"]]["connected"] = True
        snapshot, rules = import_capture(self.capture, review)
        self.assertEqual(operational_labs(snapshot, rules), 0)

    def test_unconfigured_machine_and_ghost_require_observation(self):
        for ghost in (False, True):
            altered = deepcopy(self.capture)
            m = altered["machines"][0]
            m.pop("recipe")
            m.update(built=not ghost, active=not ghost)
            snapshot, rules = import_capture(altered)
            self.assertEqual(next_step(snapshot, rules)["kind"], "observe")
            self.assertNotIn(m["id"], [e["id"] for e in snapshot.machines])
            self.assertTrue(any("unconfigured" in g for g in snapshot.document["observation_gaps"]))

    def test_unsupported_entity_and_recipe_fail_explicitly(self):
        for field, value in (("prototype", "electric-furnace"), ("recipe", "rocket-part")):
            altered = deepcopy(self.capture)
            altered["machines"][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "unsupported captured"):
                import_capture(altered)

    def test_actual_player_inventory_is_observed_and_cannot_be_overwritten(self):
        self.capture["player"].update(inventory_observed=True, inventory=[
            {"name": "iron-plate", "quality": "normal", "count": 5},
            {"name": "pistol", "quality": "normal", "count": 1}])
        snapshot, _ = import_capture(self.capture)
        self.assertEqual(snapshot.document["inventory"], {"iron-plate": 5})
        self.assertIn("pistol", " ".join(snapshot.document["provenance"]["notes"]))
        with self.assertRaisesRegex(ValueError, "cannot replace"):
            import_capture(self.capture, self.reviewed())

    def test_empty_lua_tables_and_foreign_research_progress(self):
        self.capture.update(machines={}, researched={}, research_units_completed={"mining-productivity-1": 2})
        self.capture.pop("observation")
        snapshot, _ = import_capture(self.capture)
        self.assertEqual(snapshot.machines, [])
        self.assertEqual(snapshot.document["research_units_completed"], {})
        self.assertTrue(snapshot.document["provenance"]["notes"])

    def test_bad_window_times_and_counts_are_errors(self):
        for change in ({"start_tick": 3630}, {"end_tick": 3631}, {"start_tick": -1},
                       {"produced": {"automation-science-pack": -1}}, {"produced": {"copper-cable": 0.5}}):
            altered = deepcopy(self.capture)
            altered["observation"].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                import_capture(altered)

    def test_handcraft_and_old_generation_cannot_verify_automation(self):
        for change in ({"source": "handcrafted"}, {"generation": 999}, {"valid": False},
                       {"invalid_reasons": ["world configuration changed"]}):
            altered = deepcopy(self.capture)
            altered["observation"].update(change)
            altered["crafted"]["iron-plate"] = 999999
            snapshot, _ = import_capture(altered)
            self.assertFalse(snapshot.document["observations"])

    def test_invalid_review_flags_and_machine_ids_are_rejected(self):
        review = self.reviewed()
        mid = next(iter(review["machines"]))
        review["machines"][mid]["connected"] = "true"
        with self.assertRaisesRegex(ValueError, "boolean"):
            import_capture(self.capture, review)
        del review["machines"][mid]
        with self.assertRaisesRegex(ValueError, "ids must match"):
            import_capture(self.capture, review)

    def test_import_roundtrip_and_cli_preserve_raw_capture(self):
        original = deepcopy(self.capture)
        snapshot, rules = import_capture(self.capture)
        self.assertEqual(self.capture, original)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root / "capture.json"
            capture.write_text(json.dumps(self.capture))
            before = capture.read_bytes()
            cmd = [sys.executable, str(HERE / "import_game.py"), "convert", str(capture),
                   "--out", str(root / "snapshot.json"), "--rules-out", str(root / "rules.json")]
            result = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            loaded_rules = Rules.load(root / "rules.json")
            self.assertEqual(loaded_rules.digest, rules.digest)
            self.assertEqual(Snapshot.load(root / "snapshot.json", loaded_rules).document, snapshot.document)
            self.assertEqual(capture.read_bytes(), before)
            cmd[cmd.index("--out") + 1] = str(capture)
            result = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("distinct paths", result.stderr)
            self.assertEqual(capture.read_bytes(), before)

    def test_packaged_mod_excludes_factory_mutating_scenario(self):
        with tempfile.TemporaryDirectory() as directory:
            cmd = [sys.executable, str(HERE / "tools/build_observer.py"), "--out", directory]
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            mod = Path(result.stdout.strip())
            self.assertEqual({p.name for p in mod.iterdir()}, {"info.json", "catalog.lua", "control.lua", "export.lua", "window.lua", "survey.lua", "routing.lua"})
            # Reusing a directory must not leave earlier test-only scripts in a package.
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)


class LuaWindowTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("luajit") or shutil.which("lua"), "Lua interpreter not installed; engine smoke also exercises the window")
    def test_counter_window_fault_injection(self):
        interpreter = shutil.which("luajit") or shutil.which("lua")
        result = subprocess.run([interpreter, str(HERE / "tests/window_test.lua"), str(HERE / "observer")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("8 window cases passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
