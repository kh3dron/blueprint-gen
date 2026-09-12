from copy import deepcopy
import json
import math
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from iron_plan import IronSupply


class IronPlanTest(unittest.TestCase):
    def setUp(self):
        self.observation=json.loads((HERE.parent/"12_boiler_feed/integration/fixtures/feed-final-observation.json").read_text())

    def plan(self):
        return IronSupply.from_observation(self.observation["capture"],self.observation["state"]).document()

    def test_furnaces_leave_ore_uncovered_and_output_inserters_have_power_coverage(self):
        design=self.plan();placements=design["placements"]
        ores=[r["position"] for r in self.observation["capture"]["survey"]["resources"]]
        for p in placements:
            pos=p["position"]
            if p["name"]=="stone-furnace":
                self.assertFalse(any(abs(r["x"]-pos["x"])<1 and abs(r["y"]-pos["y"])<1 for r in ores))
            if p["name"]=="inserter":
                self.assertTrue(any(max(abs(e["position"][k]-pos[k]) for k in ("x","y"))<=2.5
                    for e in placements if e["name"]=="small-electric-pole"))
        poles=[next(e for e in self.observation["state"]["power_entities"] if e["address"]=="power.pole")]
        poles += [p for p in placements if p["name"]=="small-electric-pole"]
        for a,b in zip(poles,poles[1:]):
            self.assertLessEqual(math.dist([a["position"][k] for k in ("x","y")],[b["position"][k] for k in ("x","y")]),7.5)
        self.assertEqual(design["output"]["minimum_per_min"],20)
        self.assertEqual(design["bill"]["burner-mining-drill"],2)

    def test_plan_translates_with_observed_ore_coal_and_power(self):
        original=deepcopy(self.plan());dx,dy=4,-7
        capture,state=self.observation["capture"],self.observation["state"]
        for r in capture["survey"]["resources"]+state["coal"]["entities"]+state["power_entities"]:
            r["position"]["x"]+=dx;r["position"]["y"]+=dy
        for point in capture["survey"]["area"]:point[0]+=dx;point[1]+=dy
        shifted=self.plan()
        self.assertEqual(original["bill"],shifted["bill"])
        for a,b in zip(original["placements"],shifted["placements"]):
            self.assertEqual(b["position"],{"x":a["position"]["x"]+dx,"y":a["position"]["y"]+dy})

    def test_partial_resource_survey_and_wrong_coal_endpoint_are_refused(self):
        original=deepcopy(self.observation)
        resources=self.observation["capture"]["survey"]["resources"]
        resources.remove(next(r for r in resources if r["prototype"]=="iron-ore"))
        with self.assertRaisesRegex(ValueError,"fully observed iron rectangle"):self.plan()
        self.observation=original
        chest=next(e for e in self.observation["state"]["coal"]["entities"] if e["address"]=="coal.chest")
        chest["position"]["x"]=20.5
        with self.assertRaisesRegex(ValueError,"coal chest west"):self.plan()
