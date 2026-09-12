import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from iron_checkpoint import validate_iron_checkpoint,digest_file


class IronCheckpointTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.config={"seed":42};self.contract={"method":"iron-ready-v1"}
        for name in ("game.zip","driver.json","evidence/actions.json","evidence/player-crafts.jsonl",
                     "evidence/iron-design.json","evidence/iron-opening-observation.json","evidence/feed-verification.json"):
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text("{}")
        self.manifest={"schema_version":1,"stage":"iron-ready","config":self.config,"contract":self.contract,
            "dependencies":{"12_boiler_feed/run_feed.py":"original"},
            "files":{str(p.relative_to(self.root)):digest_file(p) for p in self.root.rglob("*") if p.is_file()}}
        self.write()

    def write(self):
        (self.root/"checkpoint.json").write_text(json.dumps(self.manifest))

    def check(self):
        return validate_iron_checkpoint(self.root,config=self.config,contract=self.contract)

    @patch("iron_checkpoint.prerequisites",return_value={"12_boiler_feed/run_feed.py":"original"})
    def test_complete_bundle_and_changed_evidence(self,_):
        self.assertEqual(self.check()["stage"],"iron-ready")
        (self.root/"evidence/actions.json").write_text("changed")
        with self.assertRaisesRegex(ValueError,"artifact missing or changed"):self.check()

    @patch("iron_checkpoint.prerequisites",return_value={"12_boiler_feed/run_feed.py":"changed"})
    def test_upstream_changes_and_wrong_stage_refuse_resume(self,_):
        with self.assertRaisesRegex(ValueError,"prerequisites or preparation changed"):self.check()
        self.manifest["stage"]="feed-ready";self.write()
        with self.assertRaisesRegex(ValueError,"sealed iron-ready"):self.check()

    @unittest.skipUnless(shutil.which("luajit"),"LuaJIT is required for the native approach helper")
    def test_native_approach_filters_occupied_points_and_returns_one_value(self):
        result=subprocess.run(["luajit",str(HERE/"tests/approach_test.lua"),str(HERE/"integration/extension.lua")],
                              capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
