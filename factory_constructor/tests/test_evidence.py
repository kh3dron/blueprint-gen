from copy import deepcopy
import gzip
import json
from pathlib import Path
import unittest

from factory_constructor.legacy import verify_iron
from factory_constructor.program import validate


class ConstructorEvidenceTest(unittest.TestCase):
    def evidence(self, rate):
        path = Path(__file__).resolve().parents[1] / f"integration/fixtures/iron-{rate}.json.gz"
        return json.loads(gzip.decompress(path.read_bytes()))

    def test_declarations_complete_through_the_same_interpreter(self):
        for target, count, achieved in ((10, 1, 15), (20, 2, 30)):
            with self.subTest(target=target):
                evidence = self.evidence(target)
                program, execution = evidence["program"], evidence["execution"]
                validate(program)
                self.assertEqual(program["goal"], {"item": "iron-plate", "per_minute": target})
                self.assertEqual(program["method"]["count"], count)
                self.assertEqual(execution["program_sha256"], program["sha256"])
                self.assertEqual(execution["status"], "observed-complete")
                self.assertTrue(all(v == "observed-complete" for v in execution["nodes"].values()))
                checked = verify_iron(**evidence["inputs"], require_refusal=False)
                self.assertEqual(checked, evidence["verification"])
                self.assertEqual(checked["plates_per_minute"], [achieved] * 5)
                self.assertEqual(evidence["summary"]["png_count"], 0)
                mapped = {a for receipt in execution["receipts"].values() for a in receipt["action_ids"]}
                self.assertEqual(mapped, {a["request"]["id"] for a in evidence["inputs"]["actions"]})
                for action in evidence["inputs"]["actions"]:
                    request = action["request"]
                    self.assertIn(request["program_node"], execution["receipts"])
                    self.assertEqual(request["goal"], f"Automate {target} iron-plate/min")

    def test_two_line_proof_executes_generated_procurement(self):
        evidence = self.evidence(20)
        self.assertEqual(evidence["verification"]["additional_gathered"],
                         {"iron-ore": 104, "copper-ore": 7, "coal": 14, "stone": 20, "wood": 8})
        self.assertEqual(evidence["program"]["materials"]["gather"]["wood"], 6)
        # Whole trees yield surplus; the paid ledger, rather than the hypothetical bill, establishes it.
        self.assertTrue(any(n["operation"] == "process" for n in evidence["program"]["nodes"]))

    def test_idle_recipe_acceptance_still_refuses_wrong_or_inflight_recipes(self):
        evidence = self.evidence(10)
        for update in ({"recipe": "copper-plate"}, {"progress": .2}, {"input": {"copper-ore": 1}}):
            args = deepcopy(evidence["inputs"])
            entity = next(e for e in args["windows"][0]["before"]["entities"] if e["name"] == "stone-furnace")
            self.assertIsNone(entity.get("recipe"))
            entity.update(update)
            # Keep action receipts and the preceding startup boundary consistent so the
            # test reaches the furnace predicate instead of merely detecting edited logs.
            waits = [a for a in args["actions"] if a["request"]["op"] == "wait_iron"]
            waits[2]["outcome"]["value"] = deepcopy(args["windows"][0])
            waits[1]["outcome"]["value"]["after"] = deepcopy(args["windows"][0]["before"])
            with self.assertRaisesRegex(ValueError, "wrong smelting recipe"):
                verify_iron(**args, require_refusal=False)


if __name__ == "__main__":
    unittest.main()
