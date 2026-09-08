"""Engine survey fixtures plus perturbations that must not invent stock or connections."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from advisor_core.game_import import import_capture
from advisor_core.survey import gather, inspect, patches, write_map


class SurveyTest(unittest.TestCase):
    def setUp(self):
        self.capture = json.loads(
            (HERE / "integration/survey-fixtures/connected.json").read_text()
        )
        self.entities = json.loads(
            (HERE / "integration/survey-fixtures/engine-entities.json").read_text()
        )

    def test_adjacent_resource_tiles_share_a_patch_without_combining_separate_deposits(
        self,
    ):
        iron = [p for p in patches(self.capture) if p["resource"] == "iron-ore"]
        self.assertEqual(sorted(p["units_observed"] for p in iron), [55, 200, 10000])
        self.assertEqual(next(p for p in iron if p["units_observed"] == 55)["tiles"], 2)
        self.assertEqual(
            next(p for p in iron if p["units_observed"] == 10000)[
                "hand_mineable_units"
            ],
            0,
        )

    def test_additional_mining_splits_quantities_and_skips_the_obstructed_deposit(self):
        plan = gather(self.capture, {"iron-ore": 50, "coal": 4})
        self.assertTrue(plan["all_quantities_located"])
        self.assertEqual(
            [(s["item"], s["quantity"]) for s in plan["steps"]],
            [("coal", 4), ("iron-ore", 30), ("iron-ore", 20)],
        )
        self.assertTrue(
            all(
                s["position"] != self.entities["blocked_resource_position"]
                for s in plan["steps"]
            )
        )
        self.assertFalse(plan["changes_snapshot"])

    def test_insufficient_surveyed_stock_is_partial_and_never_double_counted(self):
        plan = gather(self.capture, {"iron-ore": 300, "coal": 12, "stone": 6})
        self.assertEqual(plan["unplanned"], {"iron-ore": 45, "coal": 2, "stone": 1})
        ids = [s["resource_id"] for s in plan["steps"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(
            all(s["quantity"] <= s["observed_resource_units"] for s in plan["steps"])
        )

    def test_existing_inventory_does_not_satisfy_an_additional_gather_request(self):
        self.capture["player"].update(
            inventory_observed=True,
            inventory=[{"name": "iron-ore", "count": 999, "quality": "normal"}],
        )
        self.assertEqual(
            sum(s["quantity"] for s in gather(self.capture, {"iron-ore": 50})["steps"]),
            50,
        )

    def test_infinite_fluid_and_stochastic_mining_are_not_finite_resources(self):
        for change in (
            {"infinite": True},
            {"required_fluid": "sulfuric-acid"},
            {"minable": False},
            {
                "products": [
                    {"type": "item", "name": "coal", "amount": 1, "probability": 0.5}
                ]
            },
            {
                "products": [
                    {
                        "type": "item",
                        "name": "coal",
                        "amount": 1,
                        "independent_probability": 0.5,
                    }
                ]
            },
            {
                "products": [
                    {
                        "type": "item",
                        "name": "coal",
                        "amount": 1,
                        "shared_probability": {"min": 0, "max": 0.5},
                    }
                ]
            },
        ):
            altered = deepcopy(self.capture)
            for r in altered["survey"]["resources"]:
                if r["prototype"] == "coal":
                    r.update(change)
            with self.subTest(change=change):
                self.assertEqual(gather(altered, {"coal": 1})["unplanned"], {"coal": 1})

    def test_empty_or_unsupported_requests_fail(self):
        for request in (
            {},
            {"wood": 1},
            {"uranium-ore": 1},
            {"coal": 0},
            {"coal": -1},
            {"coal": 1.5},
            {"coal": True},
        ):
            with self.subTest(request=request), self.assertRaises(ValueError):
                gather(self.capture, request)

    def test_removed_source_yields_an_inspection_at_the_actual_pickup_point(self):
        before = inspect(self.capture)
        mid = self.entities["inserter_id"]
        self.assertFalse(
            any(
                d["entity_id"] == mid and d["status"] == "no_pickup_entity"
                for d in before["diagnostics"]
            )
        )
        changed = json.loads(
            (HERE / "integration/survey-fixtures/removed-source.json").read_text()
        )
        after = inspect(changed)
        result = next(
            d
            for d in after["diagnostics"]
            if d["entity_id"] == mid and d["status"] == "no_pickup_entity"
        )
        inserter = next(
            e for e in changed["survey"]["infrastructure"] if e["id"] == mid
        )
        self.assertEqual(result["position"], inserter["pickup_position"])
        self.assertIn("may be intentional", result["instruction"])

    def test_unfueled_drill_and_network_membership_are_observed(self):
        report = inspect(self.capture)
        self.assertTrue(
            any(
                d["entity_id"] == self.entities["drill_id"] and d["status"] == "no_fuel"
                for d in report["diagnostics"]
            )
        )
        groups = list(report["network_members_in_scope"].values())
        self.assertEqual(len(groups), 2)
        self.assertTrue(
            any(
                self.entities["pole1_id"] in group
                and self.entities["pole2_id"] in group
                for group in groups
            )
        )
        self.assertEqual(report["water_tile_count"], 19)

    def test_survey_never_substitutes_network_rating_or_ore_for_power_and_supply(self):
        snapshot, _ = import_capture(self.capture)
        self.assertEqual(snapshot.document["power"]["available_kw"], 0)
        self.assertEqual(snapshot.document["supplies_per_s"], {})
        self.assertTrue(
            any("generation" in gap for gap in snapshot.document["observation_gaps"])
        )

    def test_survey_must_match_capture_tick_area_and_supported_profile(self):
        for change in (
            {"tick": 121},
            {"area": [[-1, -1], [1, 1]]},
            {"schema_version": 2},
        ):
            altered = deepcopy(self.capture)
            altered["survey"].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                inspect(altered)
        del self.capture["survey"]
        with self.assertRaisesRegex(ValueError, "advisor-survey"):
            gather(self.capture, {"coal": 1})

    def test_bad_and_duplicate_resource_records_are_rejected(self):
        for change in (
            {"amount": -1},
            {"amount": 1.5},
            {"standable": "yes"},
            {"position": {"x": 999, "y": 999}},
            {"products": ["coal"]},
        ):
            altered = deepcopy(self.capture)
            altered["survey"]["resources"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                inspect(altered)
        resource = deepcopy(self.capture["survey"]["resources"][0])
        resource["id"] += "-duplicate"
        self.capture["survey"]["resources"].append(resource)
        with self.assertRaisesRegex(ValueError, "double-count"):
            inspect(self.capture)

    def test_empty_survey_reports_only_absence_within_this_scope(self):
        self.capture["survey"].update(
            resources={},
            infrastructure={},
            obstacles={},
            water_tiles={},
            ungenerated_chunks={},
        )
        self.assertEqual(inspect(self.capture)["patches"], [])
        plan = gather(self.capture, {"copper-ore": 5})
        self.assertEqual(plan["unplanned"], {"copper-ore": 5})
        self.assertIn("another survey", " ".join(plan["limits"]))

    def test_patch_at_observation_boundary_is_marked_as_clipped(self):
        resource = self.capture["survey"]["resources"][0]
        resource["position"] = {
            "x": self.capture["scope"]["area"][0][0] + 0.5,
            "y": -3.5,
        }
        patch = next(
            p
            for p in patches(self.capture)
            if p["nearest_position"] == resource["position"]
        )
        self.assertTrue(patch["touches_scope_edge"])

    def test_read_only_determinism_and_capture_identity(self):
        original = deepcopy(self.capture)
        plan = gather(self.capture, {"iron-ore": 50})
        self.capture["survey"]["resources"].reverse()
        shuffled = gather(self.capture, {"iron-ore": 50})
        self.assertEqual(plan["steps"], shuffled["steps"])
        self.assertNotEqual(plan["capture_sha256"], shuffled["capture_sha256"])
        self.capture["survey"]["resources"].reverse()
        self.assertEqual(self.capture, original)

    def test_svg_is_standalone_and_escapes_observed_names(self):
        self.capture["survey"]["resources"][0]["prototype"] = (
            '<script>alert("x")</script>'
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "survey.svg"
            write_map(self.capture, path, gather(self.capture, {"iron-ore": 50}))
            root = ET.fromstring(path.read_text())
            self.assertEqual(root.tag, "{http://www.w3.org/2000/svg}svg")
            self.assertNotIn("<script>", path.read_text())
            self.assertIn("&lt;script&gt;", path.read_text())
            self.assertIn("mining targets", path.read_text())

    def test_cli_supports_separate_working_directory_without_overwriting_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "capture.json"
            path.write_text(json.dumps(self.capture))
            before = path.read_bytes()
            command = [
                sys.executable,
                str(HERE / "survey.py"),
                "gather",
                str(path),
                "iron-ore=40",
                "iron-ore=10",
                "coal=4",
                "--json",
                "--map",
                str(root / "map.svg"),
            ]
            result = subprocess.run(command, cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(result.stdout)["requested_additional"],
                {"iron-ore": 50, "coal": 4},
            )
            self.assertTrue((root / "map.svg").exists())
            command[-1] = str(path)
            result = subprocess.run(command, cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("must not overwrite", result.stderr)
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
