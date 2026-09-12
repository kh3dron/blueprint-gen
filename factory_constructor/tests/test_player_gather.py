from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from factory_constructor.player import PlayerPort


class GatherTest(unittest.TestCase):
    def test_partial_tree_survey_refreshes_only_after_observed_progress(self):
        for progresses in (True, False):
            with self.subTest(progresses=progresses), tempfile.TemporaryDirectory() as directory:
                state = {"inventory": {}, "tick": 1, "revision": 1}
                calls = []
                def mine(item, quantity):
                    calls.append(quantity)
                    if len(calls) == 1:
                        if progresses:
                            state["inventory"][item] = 4
                        raise ValueError("not enough surveyed trees to cover the wood bill")
                    state["inventory"][item] += quantity
                driver = SimpleNamespace(root=Path(directory), observations=[{"state": deepcopy(state)}],
                    actions=[], mine=mine, session=SimpleNamespace(client=SimpleNamespace(call=lambda request: deepcopy(state))))
                port = PlayerPort(driver, {"goal": {"item": "iron-plate"}})
                node = {"id": "gather", "parent": "goal/procure", "operation": "gather",
                    "inputs": {"item": "wood", "quantity": 8}, "check": "inventory_gain"}
                if progresses:
                    receipt = port.perform(node)
                    self.assertTrue(port.check(node, receipt)["observed_complete"])
                    self.assertEqual(calls, [8, 4])
                else:
                    with self.assertRaisesRegex(ValueError, "not enough surveyed trees"):
                        port.perform(node)
                    self.assertEqual(calls, [8])
