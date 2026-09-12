from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from verify_iron import verify,indexed


class IronEvidenceTest(unittest.TestCase):
    def setUp(self):
        root=HERE/"integration/fixtures"
        def read(name):return json.loads((root/name).read_text())
        self.final=read("iron-final-observation.json");self.opening=read("iron-opening-observation.json")
        self.design=read("iron-design.json");self.feed=read("feed-design.json");self.coal=read("coal-design.json")
        self.actions=read("actions.json");self.windows=read("iron-windows.json");self.baseline=read("iron-baseline.json")
        self.reconciliation=read("iron-reconciliation.json")
        self.events=[json.loads(s) for s in (root/"player-crafts.jsonl").read_text().splitlines()]

    def check(self):
        return verify(self.final,self.opening,self.design,self.feed,self.coal,self.actions,self.windows,
                      self.baseline,self.reconciliation,self.events)

    def sync(self):
        waits=[a for a in self.actions if a["request"]["op"]=="wait_iron"][-5:]
        for action,window in zip(waits,self.windows):action["outcome"]["value"]=deepcopy(window)

    def test_native_production_and_every_connected_burner_balance(self):
        result=self.check()
        self.assertEqual(result["plates_per_minute"],[30]*5)
        self.assertEqual(result["iron_ore_mined"],150)
        self.assertEqual(result["plates_produced"],150)
        self.assertEqual(result["plates_collected"],150)
        self.assertEqual(result["coal_burned"],50)
        self.assertEqual(result["coal_buffer_gain"],25)
        self.assertEqual(result["native_cursor_builds_added"],62)
        self.assertFalse(result["goal_complete"])

    def test_revision_boundary_excludes_prior_research_at_the_same_tick(self):
        research=next(a for a in reversed(self.actions) if a["request"]["op"]=="research")
        self.assertEqual(research["outcome"]["finished_tick"],self.opening["state"]["tick"])
        self.assertLess(research["request"]["revision"],self.opening["state"]["revision"])
        self.check()
        research["request"]["revision"]=self.opening["state"]["revision"]
        with self.assertRaisesRegex(ValueError,"unsupported action"):self.check()

    def test_declared_startup_cannot_be_shortened(self):
        first=next(a for a in self.actions if a["request"]["op"]=="wait_iron")
        first["outcome"]["value"]["idle_ticks"]-=1
        with self.assertRaisesRegex(ValueError,"startup window"):self.check()

    def test_disconnected_drill_is_rejected(self):
        indexed(self.windows[0]["after"]["entities"])["iron.line.0.drill"]["drop_target"]="other-furnace"
        self.sync()
        with self.assertRaisesRegex(ValueError,"drill does not feed"):self.check()

    def test_disconnected_power_and_coal_belt_are_rejected(self):
        original=deepcopy(self.windows)
        indexed(self.windows[0]["after"]["entities"])["iron.line.0.output"]["network_id"]=999
        self.sync()
        with self.assertRaisesRegex(ValueError,"power disconnected"):self.check()
        self.windows=original
        indexed(self.windows[0]["after"]["entities"])["iron.trunk.0"]["outputs"]=[]
        self.sync()
        with self.assertRaisesRegex(ValueError,"coal belt disconnected"):self.check()

    def test_native_ore_depletion_and_plate_production_are_required(self):
        original=deepcopy(self.windows)
        self.windows[0]["after"]["ore_produced"]+=1;self.sync()
        with self.assertRaisesRegex(ValueError,"deposit depletion"):self.check()
        self.windows=original;self.windows[0]["after"]["plates_produced"]+=1;self.sync()
        with self.assertRaisesRegex(ValueError,"native furnace production"):self.check()

    def test_missing_or_inconsistent_burner_meter_is_rejected(self):
        original=deepcopy(self.windows)
        self.windows[0]["after"]["meters"].pop("iron.line.0.drill");self.sync()
        with self.assertRaisesRegex(ValueError,"coverage incomplete"):self.check()
        self.windows=original;self.windows[0]["after"]["meters"]["iron.line.0.drill"]["delivered"]+=1;self.sync()
        with self.assertRaisesRegex(ValueError,"delivery does not conserve"):self.check()

    def test_coal_cannot_disappear_from_connected_buffers(self):
        coal=self.windows[0]["after"]["feed"]["coal"]
        indexed(coal["entities"])["coal.chest"]["contents"]["coal"]-=1
        coal["loose_coal"]-=1;self.sync()
        with self.assertRaisesRegex(ValueError,"stocks do not balance"):self.check()

    def test_uncollected_plates_do_not_satisfy_output_service(self):
        entities=indexed(self.windows[0]["after"]["entities"])
        entities["iron.line.0.chest"]["contents"]["iron-plate"]-=15
        entities["iron.line.0.furnace"]["output"]={"iron-plate":15}
        self.sync()
        with self.assertRaisesRegex(ValueError,"collection rate below contract"):self.check()

    def test_manual_input_and_skipped_ticks_are_rejected(self):
        self.final["transfers"].append({"tick":self.windows[1]["before"]["tick"]+1,"item":"coal","count":1,"removed":1,"inserted":1})
        with self.assertRaisesRegex(ValueError,"native player action"):self.check()
        self.final["transfers"].pop();self.windows[0]["idle_ticks"]-=1;self.sync()
        with self.assertRaisesRegex(ValueError,"skipped game time"):self.check()

    def test_missing_native_build_or_craft_event_is_rejected(self):
        original=deepcopy(self.final)
        placement=next(p for p in self.final["state"]["cursor_placements"] if p["address"].startswith("iron."))
        self.final["state"]["player_build_events"]=[e for e in self.final["state"]["player_build_events"] if e["id"]!=placement["id"]]
        with self.assertRaisesRegex(ValueError,"native build event"):self.check()
        self.final=original
        event=next(e for e in self.events if e["tick"]>self.opening["state"]["tick"] and e["recipe"]=="burner-mining-drill")
        self.events.remove(event)
        with self.assertRaisesRegex(ValueError,"native crafting outputs"):self.check()

    def test_free_inventory_or_changed_recipe_is_rejected(self):
        self.final["state"]["inventory"]["iron-plate"]=1
        with self.assertRaisesRegex(ValueError,"final iron inventory"):self.check()
        self.final["state"]["inventory"].pop("iron-plate")
        indexed(self.windows[0]["after"]["entities"])["iron.line.0.furnace"]["recipe"]="steel-plate";self.sync()
        with self.assertRaisesRegex(ValueError,"wrong smelting recipe"):self.check()
