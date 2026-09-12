import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from checkpoint import digest_file, rewrite_scenario, validate_bundle, restore_driver
from run_report import report
from session import Session
from proving_ground import SOURCE


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "evidence").mkdir()
        for name in ("game.zip", "driver.json", "evidence/actions.json", "evidence/player-crafts.jsonl"):
            (self.root / name).write_text("{}")
        self.config = {"seed":42}
        self.contract = {"stage":"ready"}
        self.manifest = {"schema_version":1,"stage":"feed-ready","config":self.config,
            "contract":self.contract,"dependencies":{"prefix.py":"abc"},
            "files":{str(p.relative_to(self.root)):digest_file(p) for p in self.root.rglob("*") if p.is_file()}}
        (self.root / "checkpoint.json").write_text(json.dumps(self.manifest))

    def check(self):
        return validate_bundle(self.root, config=self.config, contract=self.contract)

    @patch("checkpoint.dependencies", return_value={"prefix.py":"abc"})
    def test_complete_checkpoint_and_corrupt_evidence(self, _):
        self.assertEqual(self.check()["stage"], "feed-ready")
        (self.root / "evidence/actions.json").write_text("changed")
        with self.assertRaisesRegex(ValueError,"artifact missing or changed"):
            self.check()

    @patch("checkpoint.dependencies", return_value={"prefix.py":"changed"})
    def test_changed_prerequisite_refuses_cached_world(self, _):
        with self.assertRaisesRegex(ValueError,"prerequisite code changed: prefix.py"):
            self.check()

    @patch("checkpoint.dependencies", return_value={"prefix.py":"abc"})
    def test_changed_world_and_preparation_contract_are_rejected(self, _):
        self.config = {"seed":43}
        with self.assertRaisesRegex(ValueError,"configuration or preparation contract"):
            self.check()
        self.config = self.manifest["config"]
        self.contract = {"stage":"different bill"}
        with self.assertRaisesRegex(ValueError,"configuration or preparation contract"):
            self.check()

    @patch("checkpoint.dependencies", return_value={"prefix.py":"abc"})
    def test_missing_required_evidence_and_path_escape_are_rejected(self, _):
        self.manifest["files"].pop("driver.json")
        (self.root/"checkpoint.json").write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(ValueError,"missing required evidence"):
            self.check()
        self.manifest["files"]["../outside.json"]="digest"
        (self.root/"checkpoint.json").write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(ValueError,"artifact missing or changed"):
            self.check()

    def test_revised_controller_preserves_binary_world_and_original_save(self):
        source, destination = self.root/"original.zip", self.root/"cloned.zip"
        scenario=self.root/"scenario";scenario.mkdir()
        (scenario/"control.lua").write_text("new controller")
        (scenario/"extension.lua").write_text("new continuation")
        with ZipFile(source,"w") as z:
            z.writestr("world/control.lua","old controller")
            z.writestr("world/script.dat",b"serialized storage\x00\xff")
            z.writestr("world/level.dat0",b"entities and inventories\x00")
        original=digest_file(source)
        rewrite_scenario(source,destination,scenario)
        self.assertEqual(original,digest_file(source))
        with ZipFile(source) as old, ZipFile(destination) as new:
            for name in ("world/script.dat","world/level.dat0"):
                self.assertEqual(old.read(name),new.read(name))
            self.assertEqual(new.read("world/control.lua"),b"new controller")
            self.assertEqual(new.read("world/extension.lua"),b"new continuation")

    def test_changed_loaded_world_stops_before_driver_restoration(self):
        (self.root/"driver.json").write_text(json.dumps({"game":{"state":{"tick":100}}}))
        driver=SimpleNamespace(session=SimpleNamespace(client=SimpleNamespace(call=lambda _: {"state":{"tick":101}})))
        with self.assertRaisesRegex(ValueError,"loaded world or command ledger differs"):
            restore_driver(driver,self.root)

    def test_resumed_session_creates_the_native_save_directory(self):
        install=self.root/"install"
        (install/"data/core").mkdir(parents=True)
        (install/"data/server-settings.example.json").write_text("{}")
        binary=install/"factorio";binary.touch()
        with ZipFile(self.root/"game.zip","w") as archive:
            archive.writestr("world/script.dat",b"saved storage")
            archive.writestr("world/control.lua","saved controller")
        config=json.loads((SOURCE/"config.json").read_text())
        session=Session(binary,self.root/"resumed",config,checkpoint=self.root)
        self.assertTrue((session.root/"user-data/saves").is_dir())
        self.assertTrue(session.save.is_file())

    def test_failure_summary_retains_exact_command_and_observed_inventory(self):
        request={"id":"action-9","op":"place","args":{"spec":{"position":{"x":1,"y":2}}},"label":"Place furnace"}
        action={"request":request,"outcome":{"status":"failed","error":"out of reach"}}
        (self.root/"actions.json").write_text(json.dumps([action]))
        (self.root/"last-failure.json").write_text(json.dumps(action))
        (self.root/"latest-observation.json").write_text(json.dumps({"state":{"tick":12,"revision":8,"inventory":{"iron-plate":3}}}))
        result=report(self.root,status="failed",wall_seconds=1,error="out of reach")
        self.assertEqual(result["failed_action"],action)
        self.assertEqual(result["last_observed"]["inventory"],{"iron-plate":3})
        self.assertEqual(json.loads((self.root/"actions.json").read_text()),[action])

    def test_later_verifier_failure_does_not_blame_an_expected_refusal(self):
        (self.root/"last-failure.json").write_text(json.dumps({"outcome":{"error":"direction drift"}}))
        result=report(self.root,status="failed",wall_seconds=1,error="coal balance failed")
        self.assertIsNone(result["failed_action"])
        self.assertEqual(result["error"],"coal balance failed")


if __name__ == "__main__":
    unittest.main()
