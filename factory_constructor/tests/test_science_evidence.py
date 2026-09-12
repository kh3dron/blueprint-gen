import gzip
import json
from pathlib import Path
import unittest

from factory_constructor.deployment import record, refresh
from factory_constructor.program import digest, validate
from factory_constructor.verify_science import verify


class NativeScienceEvidenceTest(unittest.TestCase):
    def test_declared_science_service_replays_native_payment_and_production_proof(self):
        path = Path(__file__).resolve().parents[1] / "integration/fixtures/science-10.json.gz"
        evidence = json.loads(gzip.decompress(path.read_bytes()))
        program, execution = evidence["program"], evidence["execution"]
        validate(program)
        self.assertEqual(program["goal"], {"item": "automation-science-pack", "per_minute": 10})
        self.assertEqual(execution["status"], "observed-complete")
        self.assertEqual(execution["program_sha256"], program["sha256"])
        self.assertTrue(all(status == "observed-complete" for status in execution["nodes"].values()))
        self.assertEqual(evidence["inputs"]["design"], program["design"])
        self.assertEqual(evidence["inputs"]["previous_deployment"], program["deployment"])
        opening = evidence["inputs"]["opening"]
        self.assertEqual(digest(opening["capture"]), program["binding"]["capture_sha256"])
        self.assertEqual(digest(opening["state"]), program["binding"]["state_sha256"])
        checked = verify(**evidence["inputs"])
        self.assertEqual(checked, evidence["verification"])
        self.assertEqual(len(checked["science_per_minute"]), 5)
        self.assertGreaterEqual(min(checked["science_per_minute"]), 10)
        self.assertGreaterEqual(checked["coal_buffer_gain"], 0)
        self.assertEqual(checked["native_cursor_builds_added"], len(program["change"]["add"]))
        self.assertEqual(evidence["summary"]["png_count"], 0)
        self.assertTrue(evidence["summary"]["science_goal_complete"])
        mapped = [action for receipt in execution["receipts"].values() for action in receipt["action_ids"]]
        self.assertEqual(len(mapped), len(set(mapped)), "native actions must belong to exactly one node receipt")
        self.assertEqual(set(mapped), {a["request"]["id"] for a in evidence["inputs"]["actions"]})
        for action in evidence["inputs"]["actions"]:
            self.assertIn(action["request"]["program_node"], execution["receipts"])
            self.assertIn(action["request"]["id"], execution["receipts"][action["request"]["program_node"]]["action_ids"])
            self.assertEqual(action["request"]["goal"], "Automate 10 automation-science-pack/min")
        deployment = record(program, evidence["inputs"]["final"], checked)
        self.assertEqual(refresh(deployment, evidence["inputs"]["final"]), deployment["entities"])
        self.assertEqual(len(deployment["entities"]), len(program["change"]["retained"]) + len(program["change"]["add"]))
