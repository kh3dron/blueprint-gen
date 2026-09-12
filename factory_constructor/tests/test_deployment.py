from copy import deepcopy
import gzip
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from factory_constructor import Automate
from factory_constructor.__main__ import compile_observation
from factory_constructor import checkpoints
from factory_constructor.deployment import additions, entities, record, refresh
from factory_constructor.program import digest, save, validate
from factory_constructor.legacy import ROOT
from factory_constructor.player import PlayerPort


def evidence(rate):
    return json.loads(gzip.decompress((ROOT/f"factory_constructor/integration/fixtures/iron-{rate}.json.gz").read_bytes()))


class DeploymentTest(unittest.TestCase):
    def setUp(self):
        self.evidence=evidence(10)
        self.observation=deepcopy(self.evidence["inputs"]["final"])
        self.deployment=record(self.evidence["program"],self.observation,self.evidence["verification"])

    def compile(self,rate=10):
        return compile_observation(Automate("iron-plate",rate),self.observation,self.deployment)

    def test_native_empty_science_table_preserves_retained_entities(self):
        state = deepcopy(self.observation["state"])
        state["science"] = {"entities": {}}
        self.assertEqual(entities(state), self.deployment["entities"])

    def test_repeat_reuses_entities_and_emits_only_observation_and_retention(self):
        p=self.compile()
        validate(p)
        self.assertFalse(p["blockers"])
        self.assertEqual(len(p["change"]["retained"]),44)
        self.assertEqual(p["change"]["add"],[])
        self.assertEqual(p["materials"]["requested"],{})
        self.assertEqual(p["materials"]["gather"],{})
        self.assertFalse(any(n["operation"] in {"place","gather","process","preflight"} for n in p["nodes"]))
        self.assertTrue(any(n["operation"]=="verify_service" for n in p["nodes"]))

    def test_extension_preserves_identity_and_every_existing_configuration(self):
        p=self.compile(20)
        self.assertFalse(p["blockers"])
        self.assertEqual(p["method"]["additional_count"],1)
        self.assertEqual(len(p["change"]["add"]),16)
        before={e["address"]:e for e in self.deployment["design"]["placements"]}
        after={e["address"]:e for e in p["design"]["placements"]}
        self.assertEqual({k:after[k] for k in before},before)
        self.assertEqual(p["change"]["retained"],self.deployment["entities"])
        self.assertEqual(p["change"]["bill"],{"small-electric-pole":1,"wooden-chest":1,"stone-furnace":1,
            "burner-mining-drill":1,"inserter":1,"burner-inserter":3,"transport-belt":8})
        self.assertEqual(len(p["design"]["fuel_taps"]),1)

    def test_empty_player_inventory_procures_only_the_extension(self):
        self.observation["state"]["inventory"]={}
        p=self.compile(20)
        self.assertFalse(p["blockers"])
        self.assertEqual(p["materials"]["requested"]["burner-mining-drill"],1)
        self.assertEqual(p["materials"]["requested"]["transport-belt"],8)
        self.assertTrue(p["materials"]["gather"])

    def test_lower_goal_preserves_excess_capacity(self):
        e=evidence(20)
        d=record(e["program"],e["inputs"]["final"],e["verification"])
        p=compile_observation(Automate("iron-plate",10),e["inputs"]["final"],d)
        self.assertFalse(p["blockers"])
        self.assertEqual(p["method"]["count"],2)
        self.assertEqual(len(p["change"]["retained"]),62)
        self.assertEqual(p["change"]["add"],[])

    def test_drift_blocks_before_procurement(self):
        original=deepcopy(self.observation)
        for mutation in (lambda rows:rows.pop(),lambda rows:rows[0].update(id="replacement"),
                         lambda rows:rows[0].update(direction=4),lambda rows:rows[0]["position"].update(x=999)):
            self.observation=deepcopy(original)
            mutation(self.observation["state"]["iron"]["entities"])
            p=self.compile(20)
            self.assertIn("observed deployment drift",p["blockers"][0])
            self.assertFalse(any(n["operation"] for n in p["nodes"]))

    def test_record_hash_and_world_history_are_checked(self):
        broken=deepcopy(self.deployment);broken["entities"].clear()
        with self.assertRaisesRegex(ValueError,"record changed"):
            refresh(broken,self.observation)
        self.observation["state"]["tick"]-=1
        with self.assertRaisesRegex(ValueError,"different world"):
            refresh(self.deployment,self.observation)

    def test_difference_refuses_destructive_changes(self):
        design=deepcopy(self.deployment["design"])
        design["placements"][0]["direction"]=4
        with self.assertRaisesRegex(ValueError,"migration method"):
            additions(design,self.deployment["entities"])

    def test_unverified_result_cannot_become_a_deployment(self):
        verification=deepcopy(self.evidence["verification"])
        verification["plates_per_minute"][0]=0
        with self.assertRaisesRegex(ValueError,"unverified"):
            record(self.evidence["program"],self.observation,verification)

    def test_drift_after_compilation_stops_before_a_paid_action(self):
        program=self.compile(20)
        changed=deepcopy(self.observation["state"])
        changed["iron"]["entities"][0]["id"]="replaced-after-plan"
        calls=[]
        def call(request):
            calls.append(request)
            return changed
        with tempfile.TemporaryDirectory() as root:
            driver=SimpleNamespace(root=Path(root),observations=[self.observation],actions=[],
                session=SimpleNamespace(client=SimpleNamespace(call=call)))
            port=PlayerPort(driver,program)
            node=next(n for n in program["nodes"] if n["operation"]=="place")
            with self.assertRaisesRegex(ValueError,"retained deployment changed"):
                port.perform(node)
        self.assertEqual(calls,[{"op":"status"}])


class CheckpointTest(unittest.TestCase):
    def test_checkpoint_refuses_changed_sources_artifacts_or_execution_state(self):
        e=evidence(10)
        d=record(e["program"],e["inputs"]["final"],e["verification"])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/"evidence").mkdir()
            for name in ("game.zip","evidence/actions.json","evidence/player-crafts.jsonl","evidence/program.json",
                         "evidence/constructor-verification.json","evidence/feed-design.json","evidence/coal-design.json"):
                (root/name).write_text("{}")
            save(root/"driver.json",{"latest_observation":e["inputs"]["final"]})
            save(root/"evidence/deployment.json",d)
            save(root/"evidence/execution.json",e["execution"])
            manifest={"schema_version":1,"stage":"constructor-idle","config":{"test":1},"contract":checkpoints.CONTRACT,
                "dependencies":{"upstream":"original"},
                "files":{str(p.relative_to(root)):checkpoints.digest_file(p) for p in root.rglob("*") if p.is_file()}}
            save(root/"checkpoint.json",manifest)
            with patch.object(checkpoints,"prerequisites",return_value={"upstream":"original"}):
                checkpoints.validate(root,config={"test":1})
                (root/"evidence/actions.json").write_text("changed")
                with self.assertRaisesRegex(ValueError,"artifact missing or changed"):
                    checkpoints.validate(root,config={"test":1})
            with patch.object(checkpoints,"prerequisites",return_value={"upstream":"changed"}):
                with self.assertRaisesRegex(ValueError,"prerequisites"):
                    checkpoints.validate(root,config={"test":1})


if __name__=="__main__":
    unittest.main()
