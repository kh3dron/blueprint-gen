from collections import Counter, defaultdict
from copy import deepcopy
import gzip
import json
import math
from pathlib import Path
import unittest

from factory_constructor.deployment import record
from factory_constructor.science_layout import layout, _cells


FIXTURE = Path(__file__).resolve().parents[1]/"integration/fixtures/iron-20.json.gz"


class ScienceLayoutTest(unittest.TestCase):
    def setUp(self):
        evidence = json.loads(gzip.decompress(FIXTURE.read_bytes()))
        self.observation = evidence["inputs"]["final"]
        self.deployment = record(evidence["program"], self.observation, evidence["verification"])
        self.rules = self.observation["capture"]["resolved_rules"]

    def design(self, rate=10):
        return layout(self.observation, self.deployment, self.rules, rate)

    def test_counts_rates_bill_and_immutable_inputs(self):
        before = deepcopy((self.observation, self.deployment, self.rules))
        design = self.design()
        self.assertEqual((self.observation, self.deployment, self.rules), before)
        self.assertEqual(design["counts"]["required"], {
            "automation-science-pack": 2, "iron-gear-wheel": 1, "copper-plate": 1})
        self.assertEqual(design["rates"]["items_per_minute"], {
            "automation-science-pack": 10, "iron-gear-wheel": 10, "iron-plate": 20,
            "copper-plate": 10, "copper-ore": 10})
        self.assertEqual(design["bill"], dict(Counter(p["name"] for p in design["placements"])))
        self.assertEqual(design["bill"]["burner-mining-drill"], 2)
        self.assertEqual({a["resource"] for a in design["mining_areas"]}, {"coal", "copper-ore"})
        self.assertEqual(len(design["output"]["addresses"]), 2)
        self.assertTrue(all(p["address"].startswith("science.") for p in design["placements"]))
        self.assertFalse(set(self.deployment["entities"]) & {p["address"] for p in design["placements"]})

    def test_recipe_speed_drives_selected_geometry(self):
        six = self.design(6)
        self.assertEqual(six["counts"]["selected"]["automation-science-pack"], 1)
        self.assertEqual(six["bill"]["assembling-machine-1"], 2)
        self.rules["recipes"]["automation-science-pack"]["seconds"] = 3
        ten = self.design(10)
        self.assertEqual(ten["counts"]["selected"]["automation-science-pack"], 1)
        self.assertEqual(ten["rates"]["machine_capacity_per_minute"]["automation-science-pack"], 10)
        self.rules["recipes"]["automation-science-pack"]["seconds"] = 10
        with self.assertRaisesRegex(ValueError, "runtime recipe rates"):
            self.design()

    def test_invalid_targets_and_insufficient_iron_fail_before_building(self):
        for rate in (0, -1, 12.01, True, float("nan"), float("inf")):
            with self.subTest(rate=rate), self.assertRaisesRegex(ValueError, "at most 12"):
                self.design(rate)
        self.deployment["service"]["minimum_per_minute"] = 19
        with self.assertRaisesRegex(ValueError, "verified iron service"):
            self.design()

    def test_full_footprints_never_cross_existing_entities_or_water(self):
        design = self.design()
        survey = self.observation["capture"]["survey"]
        occupied = set()
        for p in list(self.deployment["entities"].values()) + survey["infrastructure"] + survey["obstacles"]:
            if p.get("entity_type") != "character":
                occupied |= _cells(p)
        occupied |= {(p["x"], p["y"]) for p in survey["water_tiles"]}
        for spec in design["placements"]:
            self.assertFalse(occupied & _cells(spec), spec["address"])
            occupied |= _cells(spec)
        self.assertNotIn("underground-belt", design["bill"])
        self.assertNotIn("splitter", design["bill"])

    def test_observed_water_and_missing_mining_tiles_refuse_the_layout(self):
        design = self.design()
        first = design["placements"][0]
        x, y = next(iter(_cells(first)))
        self.observation["capture"]["survey"]["water_tiles"].append({"x": x, "y": y})
        with self.assertRaisesRegex(ValueError, "blocked, wet, or outside survey"):
            self.design()
        self.observation["capture"]["survey"]["water_tiles"].pop()
        ore = self.observation["capture"]["survey"]["resources"]
        ore[:] = [r for r in ore if not (r["prototype"] == "copper-ore" and r["position"] == {"x": 8.5, "y": -23.5})]
        with self.assertRaisesRegex(ValueError, "footprint lacks observed copper"):
            self.design()

    def test_every_transfer_matches_physical_direction_and_every_consumer_has_power(self):
        design = self.design()
        entities = {a: dict(e, address=a) for a, e in self.deployment["entities"].items()}
        for group in (self.observation["state"]["power_entities"], self.observation["state"]["coal"]["entities"], design["placements"]):
            entities.update({e["address"]: e for e in group})
        forward = {0: (0, -1), 4: (1, 0), 8: (0, 1), 12: (-1, 0)}
        powered = set()
        for edge in design["connections"]:
            a, b = entities[edge["from"]], entities[edge["to"]]
            ax, ay = a["position"]["x"], a["position"]["y"]
            bx, by = b["position"]["x"], b["position"]["y"]
            if edge["kind"] == "belt":
                dx, dy = forward[a["direction"]]
                self.assertEqual((ax+dx, ay+dy), (bx, by), edge)
            elif edge["kind"] == "pickup":
                dx, dy = forward[b["direction"]]
                self.assertIn((math.floor(bx+dx), math.floor(by+dy)), _cells(a), edge)
            elif edge["kind"] == "drop":
                dx, dy = forward[a["direction"]]
                self.assertIn((math.floor(ax-1.2*dx), math.floor(ay-1.2*dy)), _cells(b), edge)
            elif edge["kind"] == "wire":
                self.assertLessEqual(math.dist((ax, ay), (bx, by)), 7)
            elif edge["kind"] == "power":
                self.assertTrue(any(abs(x+.5-ax) <= 2 and abs(y+.5-ay) <= 2 for x, y in _cells(b)), edge)
                powered.add(b["address"])
        self.assertEqual(powered, {p["address"] for p in design["placements"]
                                  if p["name"] in {"inserter", "assembling-machine-1"}})

    def test_new_coal_drill_has_a_closed_automatic_refuel_path(self):
        design = self.design()
        graph = defaultdict(set)
        for edge in design["connections"]:
            if edge["item"] == "coal":
                graph[edge["from"]].add(edge["to"])
        retained = dict(self.deployment["entities"])
        retained.update({e["address"]: e for e in self.observation["state"]["coal"]["entities"]})
        by_id = {e["id"]: address for address, e in retained.items()}
        positions = {(e["position"]["x"], e["position"]["y"]): a for a, e in retained.items()
                     if e["name"] == "transport-belt"}
        for position, address in positions.items():
            e = retained[address]
            dx, dy = {0: (0, -1), 4: (1, 0), 8: (0, 1), 12: (-1, 0)}[e["direction"]]
            if (position[0]+dx, position[1]+dy) in positions:
                graph[address].add(positions[position[0]+dx, position[1]+dy])
        for address, entity in retained.items():
            if entity.get("pickup_target") in by_id:
                graph[by_id[entity["pickup_target"]]].add(address)
            if entity.get("drop_target") in by_id:
                graph[address].add(by_id[entity["drop_target"]])
        seen, pending = set(), list(graph["science.coal.drill"])
        while pending:
            node = pending.pop()
            if node not in seen:
                seen.add(node)
                pending.extend(graph[node])
        self.assertIn("science.coal.drill", seen)
        self.assertEqual(design["seed_coal"], {})

    def test_added_coal_joins_collection_before_the_shared_chest(self):
        design = self.design()
        specs = {p["address"]: p for p in design["placements"]}
        self.assertEqual(specs["science.coal.drill"]["position"], {"x": -23, "y": -19})
        self.assertEqual(specs["science.coal.drill"]["direction"], 12)
        merge = next(c for c in design["connections"]
                     if c["from"].startswith("science.coal.") and not c["to"].startswith("science."))
        self.assertEqual(merge["to"], "coal.belt.0")
        self.assertEqual(merge["kind"], "belt")
        self.assertEqual(specs[merge["from"]]["position"], {"x": -24.5, "y": -23.5})
        self.assertEqual(specs[merge["from"]]["direction"], 4)
        self.assertFalse(any(c["from"] == "science.coal.drill" and c["to"].startswith("iron.")
                             for c in design["connections"]))
        self.assertEqual(len([s for s in specs.values() if s["address"].startswith("science.coal.")
                              and s["name"] == "burner-inserter"]), 1)
        refuel = specs["science.coal.refuel.inserter"]
        self.assertEqual(refuel["position"], {"x": -21.5, "y": -18.5})
        self.assertEqual(refuel["direction"], 4)
        self.assertIn({"from": "coal.chest", "to": refuel["address"], "item": "coal", "kind": "pickup"},
                      design["connections"])


if __name__ == "__main__":
    unittest.main()
