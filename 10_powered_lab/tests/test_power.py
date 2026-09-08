"""Actual construction/research receipts and conservative power planning boundaries."""
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from power_plan import PowerIsland
from verify_power import verify


class PowerPlanTest(unittest.TestCase):
    def capture(self, dx=0, dy=0):
        return {"survey": {"water_tiles": [{"x": x+dx, "y": y+dy} for x in range(-48,-40) for y in range(-24,-16)]}}

    def test_relocated_water_moves_the_whole_island_without_changing_its_bill(self):
        original = PowerIsland.from_survey(self.capture()).document()
        shifted = PowerIsland.from_survey(self.capture(8,20)).document()
        self.assertEqual(original["bill"], shifted["bill"])
        self.assertEqual(original["connections"], shifted["connections"])
        self.assertEqual(sum(original["bill"].values()), 6)
        for a,b in zip(original["placements"], shifted["placements"]):
            self.assertEqual(a["address"], b["address"])
            self.assertEqual((b["position"]["x"]-a["position"]["x"], b["position"]["y"]-a["position"]["y"]), (8,20))

    def test_incomplete_irregular_and_missing_ponds_require_another_method(self):
        for kind in ("missing", "hole", "two_ponds"):
            capture = self.capture()
            tiles = capture["survey"]["water_tiles"]
            if kind == "missing":
                tiles.clear()
            elif kind == "hole":
                tiles.pop(25)
            else:
                tiles.append({"x": 100,"y": 100})
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                PowerIsland.from_survey(capture)

    def test_a_rectangular_patch_clipped_by_the_survey_is_not_a_complete_shoreline(self):
        capture = self.capture()
        capture["survey"]["area"] = [[-48, -40], [40, 40]]
        with self.assertRaisesRegex(ValueError, "survey boundary"):
            PowerIsland.from_survey(capture)


class PowerEvidenceTest(unittest.TestCase):
    def inputs(self):
        root = HERE / "integration/fixtures"
        def read(name):
            return json.loads((root / f"{name}.json").read_text())
        events = [json.loads(s) for s in (root / "player-crafts.jsonl").read_text().splitlines()]
        return [read("final-observation"), read("actions"), read("refusals"), read("power-design"), events]

    def test_native_builds_paid_science_and_actual_power_unlock_automation(self):
        report = verify(*self.inputs())
        self.assertEqual(report["native_cursor_builds"], 7)
        self.assertEqual(report["research_ticks"], 6000)
        self.assertEqual(report["science_consumed"], 10)
        self.assertEqual(report["furnace_crafts"], 117)
        self.assertTrue(report["automation_researched"])
        self.assertTrue(report["repeat_lab_retained"])
        self.assertFalse(report["goal_complete"])

    def test_physical_relocated_pond_run_preserves_costs_and_moves_every_power_entity(self):
        shifted = self.inputs()[0]["state"]
        original = json.loads((HERE / "integration/fixtures/default-final-observation.json").read_text())["state"]
        self.assertEqual(original["inventory"], shifted["inventory"])
        self.assertEqual(original["crafted"], shifted["crafted"])
        self.assertEqual(original["researched"], shifted["researched"])
        original_entities = {e["address"]: e for e in original["power_entities"]}
        for entity in shifted["power_entities"]:
            prior = original_entities[entity["address"]]
            self.assertEqual(entity["name"], prior["name"])
            self.assertEqual(entity["position"]["x"]-prior["position"]["x"], 8)
            self.assertEqual(entity["position"]["y"]-prior["position"]["y"], 20)

    def test_missing_wire_power_or_research_is_not_success(self):
        for kind in ("network", "power", "energy", "research", "science", "energy_total"):
            args = self.inputs()
            state = args[0]["state"]
            entities = {e["name"]: e for e in state["power_entities"]}
            if kind == "network":
                entities["lab"]["network_id"] = 99
            elif kind == "power":
                entities["small-electric-pole"]["generation_kw_5s"] = 0
            elif kind == "energy":
                entities["lab"]["energy_j"] = 0
            elif kind == "research":
                state["researched"].remove("automation")
            elif kind == "energy_total":
                entities["small-electric-pole"]["generated_j"] = 0
            else:
                entities["lab"]["science"] = {"automation-science-pack": 1}
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                verify(*args)

    def test_free_build_missing_native_event_or_deployment_drift_is_refused(self):
        for kind in ("free", "event", "drift", "duplicate"):
            args = self.inputs()
            state = args[0]["state"]
            if kind == "free":
                placement = state["cursor_placements"][-1]
                placement["after"] = placement["before"]
            elif kind == "event":
                state["player_build_events"].pop()
            elif kind == "drift":
                state["power_entities"][0]["position"]["x"] += 1
            else:
                state["cursor_placements"][-1]["id"] = state["cursor_placements"][0]["id"]
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                verify(*args)

    def test_false_refusals_short_transfers_or_missing_crafts_are_refused(self):
        for kind in ("refusal", "transfer", "craft", "time"):
            args = self.inputs()
            if kind == "refusal":
                args[2][0]["after"]["inventory"]["lab"] += 1
            elif kind == "transfer":
                args[0]["transfers"][-1]["inserted"] -= 1
            elif kind == "craft":
                args[4].pop()
            else:
                args[1][-1]["outcome"]["finished_tick"] -= 100
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                verify(*args)


if __name__ == "__main__":
    unittest.main()
