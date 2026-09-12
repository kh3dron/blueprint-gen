from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from feed_plan import BoilerFeed
from coal_profile import CoalDriver
from verify_feed import verify, indexed


class BoilerFeedTests(unittest.TestCase):
    def setUp(self):
        fixtures=HERE/"integration/fixtures"
        def read(name): return json.loads((fixtures/name).read_text())
        self.final=read("feed-final-observation.json")
        self.actions=read("actions.json")
        self.design=read("feed-design.json")
        self.coal_design=read("coal-design.json")
        self.windows=read("feed-windows.json")
        self.baseline=read("feed-baseline.json")
        self.opening=read("coal-final-observation.json")
        self.reconciliation=read("feed-reconciliation.json")
        self.events=[json.loads(s) for s in (fixtures/"player-crafts.jsonl").read_text().splitlines()]

    def verify(self):
        return verify(self.final,self.actions,self.design,self.coal_design,self.windows,
                      self.baseline,self.opening,self.reconciliation,self.events)

    def sync(self):
        waits=[a for a in self.actions if a["request"]["op"]=="wait_feed"]
        for action,window in zip(waits[1:],self.windows):
            action["outcome"]["value"]=deepcopy(window)

    def test_real_engine_connection_and_useful_power(self):
        report=self.verify()
        self.assertTrue(report["automatic_boiler_fuel_observed"])
        self.assertEqual(report["idle_seconds"],300)
        self.assertGreater(report["coal_delivered_to_boiler_during_measurement"],0)
        self.assertGreater(report["generated_j_since_connection"],report["original_power_reserve_j"])
        self.assertGreaterEqual(report["coal_buffer_gain"],0)
        self.assertEqual(report["researched"],"logistics")
        self.assertEqual(report["native_cursor_builds_added"],20)
        self.assertEqual(report["additional_gathered"],{"iron-ore":73,"copper-ore":20,"coal":10})
        self.assertFalse(report["goal_complete"])

    def test_finite_research_does_not_establish_science_supply(self):
        snapshot,_=CoalDriver.snapshot(self.final["capture"],self.final["state"])
        self.assertEqual(snapshot.document["supplies_per_s"],{})

    def test_route_uses_observed_endpoints_and_refuses_unsupported_geometry(self):
        original=BoilerFeed.from_state(self.opening["state"]).document()
        state=deepcopy(self.opening["state"])
        for e in state["coal"]["entities"]+state["power_entities"]:
            e["position"]["x"]-=4;e["position"]["y"]+=7
        shifted=BoilerFeed.from_state(state).document()
        for a,b in zip(original["placements"],shifted["placements"]):
            self.assertEqual(b["position"],{"x":a["position"]["x"]-4,"y":a["position"]["y"]+7})
        indexed(state["power_entities"])["power.boiler"]["direction"]=4
        with self.assertRaisesRegex(ValueError,"north-facing"):
            BoilerFeed.from_state(state)

    def test_disconnected_belt_is_rejected(self):
        indexed(self.windows[0]["after"]["entities"])["feed.belt.0"]["outputs"]=[]
        self.sync()
        with self.assertRaisesRegex(ValueError,"belt path is disconnected"):
            self.verify()

    def test_coal_in_storage_is_not_consumer_delivery(self):
        indexed(self.windows[0]["after"]["entities"])["feed.insert"]["drop_target"]=self.design["source"]["id"]
        self.sync()
        with self.assertRaisesRegex(ValueError,"inserter endpoints are disconnected"):
            self.verify()

    def test_production_must_match_depletion(self):
        self.windows[0]["after"]["coal"]["produced"]+=1
        self.sync()
        with self.assertRaisesRegex(ValueError,"deposit depletion"):
            self.verify()

    def test_idle_power_is_not_useful_load(self):
        a,b=self.windows[0]["before"],self.windows[0]["after"]
        indexed(b["power_entities"])["power.pole"]["lab_consumed_j"]=indexed(a["power_entities"])["power.pole"]["lab_consumed_j"]
        self.sync()
        with self.assertRaisesRegex(ValueError,"load was not sustained"):
            self.verify()

    def test_original_reserves_cannot_explain_result(self):
        self.baseline["power_reserve_j"]=1e12
        next(a for a in self.actions if a["request"]["op"]=="begin_feed")["outcome"]["value"]=deepcopy(self.baseline)
        with self.assertRaisesRegex(ValueError,"original boiler fuel"):
            self.verify()

    def test_manual_refuel_is_rejected(self):
        self.final["transfers"].append({"tick":self.windows[2]["before"]["tick"]+1,"item":"coal","count":1,"removed":1,"inserted":1})
        with self.assertRaisesRegex(ValueError,"player action during"):
            self.verify()

    def test_meter_must_match_boiler_inventory(self):
        self.windows[0]["after"]["delivered"]+=1
        self.sync()
        with self.assertRaisesRegex(ValueError,"fuel meter"):
            self.verify()

    def test_draining_reserves_do_not_establish_sustained_supply(self):
        coal=self.windows[0]["before"]["coal"]
        indexed(coal["entities"])["coal.chest"]["contents"]["coal"]+=1000
        coal["loose_coal"]+=1000
        self.sync()
        with self.assertRaisesRegex(ValueError,"fuel buffers drained"):
            self.verify()

    def test_missing_native_build_event_is_rejected(self):
        ident=next(p["id"] for p in self.final["state"]["cursor_placements"] if p["address"]=="feed.insert")
        self.final["state"]["player_build_events"]=[e for e in self.final["state"]["player_build_events"] if e["id"]!=ident]
        with self.assertRaisesRegex(ValueError,"native build event"):
            self.verify()

    def test_unpaid_inventory_is_rejected(self):
        self.final["state"]["inventory"]["iron-plate"]=999
        with self.assertRaisesRegex(ValueError,"final inventory"):
            self.verify()

    def test_missing_native_crafts_are_rejected(self):
        tick=self.opening["state"]["tick"]
        self.events=[e for e in self.events if e["tick"]<=tick or e["recipe"]!="burner-inserter"]
        with self.assertRaisesRegex(ValueError,"native crafting outputs"):
            self.verify()


if __name__=="__main__": unittest.main()
