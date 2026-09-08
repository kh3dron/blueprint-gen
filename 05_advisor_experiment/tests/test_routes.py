"""Actual engine route receipts, instruction compilation, and refusal boundaries."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from advisor_core.routes import compile_route, map_plan
from advisor_core.survey import distance


class RouteTest(unittest.TestCase):
    def fixture(self, name):
        return json.loads(
            (HERE / "integration/route-fixtures" / f"{name}.json").read_text()
        )

    def test_engine_detour_is_preserved_while_collinear_points_are_compacted(self):
        raw = self.fixture("detour")
        before = deepcopy(raw)
        plan = compile_route(raw)
        self.assertEqual(plan["kind"], "walk_then_mine")
        self.assertLess(len(plan["waypoints"]), len(raw["path"]))
        self.assertEqual(plan["waypoints"][0], raw["start"])
        self.assertEqual(plan["waypoints"][-1], raw["path"][-1]["position"])
        raw_distance = sum(
            distance(a["position"], b["position"])
            for a, b in zip(raw["path"], raw["path"][1:])
        )
        self.assertAlmostEqual(plan["planned_distance_tiles"], raw_distance)
        self.assertTrue(any(p["y"] < -6 or p["y"] > 7 for p in plan["waypoints"]))
        self.assertFalse(plan["changes_game"])
        self.assertEqual(raw, before)

    def test_actual_character_walked_and_mined_the_python_compiled_plan(self):
        plan = compile_route(self.fixture("detour"))
        execution = self.fixture("execution")
        self.assertEqual(execution["receipt_sha256"], plan["receipt_sha256"])
        self.assertEqual(execution["actual_inventory"], 3)
        self.assertEqual(execution["resource_depletion"], 3)
        self.assertTrue(execution["wall_preserved"])
        self.assertTrue(execution["can_reach"])
        self.assertLess(
            distance(execution["final_position"], plan["stand_position"]), 0.13
        )

    def test_unreachable_and_invalidated_receipts_produce_no_instructions(self):
        for name in ("unreachable", "moved", "world-changed"):
            with self.subTest(name=name):
                plan = compile_route(self.fixture(name))
                self.assertEqual(plan["kind"], "observe")
                self.assertEqual(plan["waypoints"], [])
                self.assertEqual(plan["instructions"], [])
                self.assertTrue(plan["reasons"])

    def test_already_in_reach_requests_mining_without_walking(self):
        plan = compile_route(self.fixture("in-reach"))
        self.assertEqual(len(plan["waypoints"]), 1)
        self.assertEqual(plan["planned_distance_tiles"], 0)
        self.assertEqual(len(plan["instructions"]), 1)
        self.assertIn("hand-mine 2 additional coal", plan["instructions"][0])

    def test_busy_pathfinder_is_retry_without_fake_path(self):
        raw = self.fixture("unreachable")
        raw.update(status="retry", reasons=["native pathfinder was busy"])
        self.assertEqual(compile_route(raw)["kind"], "retry")

    def test_stale_or_impossible_current_tick_cannot_issue_walk_instructions(self):
        raw = self.fixture("detour")
        self.assertEqual(
            compile_route(raw, current_tick=raw["completed_tick"] + 601)["kind"],
            "observe",
        )
        self.assertEqual(
            compile_route(raw, current_tick=raw["completed_tick"] + 600)["kind"],
            "walk_then_mine",
        )
        with self.assertRaises(ValueError):
            compile_route(raw, current_tick=raw["completed_tick"] - 1)

    def test_version_mod_and_source_mismatches_fail(self):
        for change in (
            {"route_schema_version": 2},
            {"source": "predicted"},
            {"factorio_version": "2.0.72"},
            {"exporter": {"name": "blueprint-gen-observer", "version": "0.2.0"}},
            {"active_mods": {"base": "2.1.16", "space-age": "2.1.16"}},
            {"surface_name": "vulcanus"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                compile_route({**self.fixture("detour"), **change})

    def test_destruction_and_incompatible_constraints_are_rejected(self):
        raw = self.fixture("detour")
        raw["path"][1]["needs_destroy_to_reach"] = True
        with self.assertRaisesRegex(ValueError, "destruction"):
            compile_route(raw)
        raw = self.fixture("detour")
        raw["constraints"]["can_open_gates"] = True
        with self.assertRaisesRegex(ValueError, "constraints"):
            compile_route(raw)

    def test_native_success_requires_the_independent_collision_check(self):
        raw = self.fixture("detour")
        del raw["path_validation"]
        with self.assertRaisesRegex(ValueError, "independent collision"):
            compile_route(raw)
        raw = self.fixture("detour")
        raw["pathfinder_collision_mask"]["layers"].pop("water_tile")
        with self.assertRaisesRegex(ValueError, "explicitly block water"):
            compile_route(raw)
        for mask in (None, [], {"layers": None}, {"layers": []}):
            raw = self.fixture("detour")
            raw["pathfinder_collision_mask"] = mask
            with self.subTest(mask=mask), self.assertRaises(ValueError):
                compile_route(raw)

    def test_start_endpoint_and_mining_radius_are_checked(self):
        for kind in ("start", "end", "radius"):
            raw = self.fixture("detour")
            if kind == "start":
                raw["path"][0]["position"]["x"] += 1
            elif kind == "end":
                raw["path"][-1]["position"] = {"x": 100, "y": 100}
            else:
                raw["goal_radius"] = raw["actor"]["resource_reach_distance"]
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                compile_route(raw)

    def test_invalid_counts_times_positions_and_ready_status_fail(self):
        for field, value in (
            ("quantity", 0),
            ("quantity", 1.5),
            ("quantity", 1001),
            ("amount", 1),
        ):
            raw = self.fixture("detour")
            raw["target"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                compile_route(raw)
        for change in (
            {"completed_tick": -1},
            {"generation_at_completion": 999},
            {"reasons": ["world changed"]},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                compile_route({**self.fixture("detour"), **change})
        raw = self.fixture("detour")
        raw["path"][1]["position"]["x"] = float("nan")
        with self.assertRaises(ValueError):
            compile_route(raw)

    def test_unusable_status_cannot_hide_a_path(self):
        raw = self.fixture("detour")
        raw.update(status="invalidated", reasons=["world changed"])
        with self.assertRaisesRegex(ValueError, "no walking path"):
            compile_route(raw)

    def test_map_requires_matching_recent_survey_and_complete_spatial_coverage(self):
        raw, survey = self.fixture("detour"), self.fixture("survey")
        self.assertTrue(map_plan(raw, survey)["route"])
        survey["generation"] += 1
        with self.assertRaisesRegex(ValueError, "same recent"):
            map_plan(raw, survey)
        survey = self.fixture("survey")
        survey["scope"]["area"] = [[-32.5, -23.5], [5, 24.5]]
        survey["survey"]["area"] = survey["scope"]["area"]
        survey["survey"]["resources"] = [
            r for r in survey["survey"]["resources"] if r["position"]["x"] < 5
        ]
        with self.assertRaisesRegex(ValueError, "leaves the supplied survey"):
            map_plan(raw, survey)

    def test_collinear_backtracking_is_not_removed(self):
        raw = self.fixture("detour")
        start = raw["start"]
        raw["path"] = (
            raw["path"][:1]
            + [
                {
                    "position": {"x": start["x"] - 0.25, "y": start["y"]},
                    "needs_destroy_to_reach": False,
                },
                {"position": deepcopy(start), "needs_destroy_to_reach": False},
            ]
            + raw["path"][1:]
        )
        plan = compile_route(raw)
        self.assertEqual(plan["waypoints"][2], start)

    def test_cli_outputs_valid_json_and_refuses_to_overwrite_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "receipt.json"
            survey = root / "survey.json"
            receipt.write_text(json.dumps(self.fixture("detour")))
            survey.write_text(json.dumps(self.fixture("survey")))
            before = receipt.read_bytes()
            command = [
                sys.executable,
                str(HERE / "route.py"),
                str(receipt),
                "--json",
                "--survey",
                str(survey),
                "--map",
                str(root / "map.svg"),
            ]
            result = subprocess.run(command, cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["kind"], "walk_then_mine")
            self.assertTrue((root / "map.svg").exists())
            command[-1] = str(receipt)
            result = subprocess.run(command, cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(receipt.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
