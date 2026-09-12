from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from factory_constructor.__main__ import compile_observation
from factory_constructor.legacy import ROOT
from factory_constructor.program import Automate, Executor, ProgramBuilder, digest, validate


FIXTURE = ROOT / "13_iron_supply/integration/fixtures/iron-opening-observation.json"


class CompilerTest(unittest.TestCase):
    def setUp(self):
        self.observation = json.loads(FIXTURE.read_text())

    def compile(self, rate, item="iron-plate"):
        return compile_observation(Automate(item, rate), self.observation)

    def test_goal_changes_machine_count_placement_and_procurement(self):
        one, two = self.compile(10), self.compile(20)
        self.assertEqual(one["blockers"], [])
        self.assertEqual(two["blockers"], [])
        self.assertEqual(one["method"]["count"], 1)
        self.assertEqual(two["method"]["count"], 2)
        self.assertEqual(one["design"]["bill"]["burner-mining-drill"], 1)
        self.assertEqual(two["design"]["bill"]["burner-mining-drill"], 2)
        self.assertLess(one["materials"]["gather"]["iron-ore"], two["materials"]["gather"]["iron-ore"])
        self.assertNotIn("iron.branch-tap", [p["address"] for p in one["design"]["placements"]])
        for program in (one, two):
            validate(json.loads(json.dumps(program)))
            leaves = [n for n in program["nodes"] if n["operation"]]
            self.assertEqual(leaves[-1]["operation"], "verify_service")
            self.assertEqual(leaves[-1]["inputs"]["per_minute"], program["goal"]["per_minute"])
            self.assertTrue(all(n["check"] for n in leaves))

    def test_rounding_uses_measured_collection_not_furnace_speed_alone(self):
        self.assertEqual(self.compile(15)["method"]["count"], 1)
        self.assertEqual(self.compile(15.01)["method"]["count"], 2)
        self.assertEqual(self.compile(30)["method"]["count"], 2)
        self.assertIn("requires 3 lines", self.compile(30.01)["blockers"][0])

    def test_inventory_reduces_procurement_but_not_production_requirement(self):
        original = self.compile(20)
        self.observation["state"]["inventory"].update(original["design"]["bill"])
        funded = self.compile(20)
        self.assertEqual(funded["materials"]["gather"], {})
        self.assertEqual(funded["method"]["count"], 2)
        self.assertEqual(funded["design"], original["design"])

    def test_observed_positions_drive_layout(self):
        original = self.compile(10)
        # Shift the pure layout inputs while preserving the importer consistency fields.
        capture, state = self.observation["capture"], self.observation["state"]
        for item in capture["survey"]["resources"] + state["coal"]["entities"] + state["power_entities"]:
            item["position"]["x"] += 4
            item["position"]["y"] -= 7
        for point in capture["survey"]["area"]:
            point[0] += 4
            point[1] -= 7
        shifted = self.compile(10)
        self.assertEqual(shifted["blockers"], [])
        for a, b in zip(original["design"]["placements"], shifted["design"]["placements"]):
            self.assertEqual(b["position"], {"x": a["position"]["x"]+4, "y": a["position"]["y"]-7})

    def test_science_expands_rates_and_requires_an_iron_checkpoint(self):
        program = self.compile(10, "automation-science-pack")
        self.assertTrue(program["blockers"])
        self.assertEqual(program["requirements"]["crafts_per_minute"]["iron-plate"], 20)
        self.assertEqual(program["requirements"]["crafts_per_minute"]["copper-plate"], 10)
        self.assertIn("verified iron deployment checkpoint", program["blockers"][0])
        self.assertFalse(any(n["operation"] for n in program["nodes"]))

    def test_existing_factory_is_not_blindly_reconstructed(self):
        self.observation["state"]["iron"] = {"entities": [{"address": "iron.line.0.drill"}]}
        self.assertIn("incremental migration", self.compile(20)["blockers"][0])

    def test_changed_runtime_mechanics_invalidate_service_estimate(self):
        self.observation["capture"]["resolved_rules"]["recipes"]["iron-plate"]["seconds"] *= 2
        self.assertIn("same engine profile", self.compile(20)["blockers"][0])

    def test_invalid_rates_are_rejected(self):
        for rate in (0, -1, True, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                Automate("iron-plate", rate)


class RecordingPort:
    def __init__(self, reject=None):
        self.actions, self.reject, self.validations = [], reject, 0

    def validate(self, program):
        self.validations += 1

    def perform(self, node):
        self.actions.append(node["id"])
        return {"command_done": True}

    def check(self, node, receipt):
        return {"observed_complete": node["id"] != self.reject}


class InterpreterTest(unittest.TestCase):
    def program(self):
        builder = ProgramBuilder(Automate("test-item", 1), {}, {})
        builder.group("goal/module", "goal", "Module", "test-method")
        builder.step("build", "goal/module", "place", {}, "built", "test-method")
        builder.step("measure", "goal/module", "measure", {}, "measured", "test-method")
        return builder.finish()

    def seal(self, program):
        program["sha256"] = digest({k: v for k, v in program.items() if k != "sha256"})
        return program

    def test_json_interpreter_respects_dependencies_with_reordered_nodes(self):
        program = self.program()
        program["nodes"].reverse()
        program = json.loads(json.dumps(self.seal(program)))
        port = RecordingPort()
        with tempfile.TemporaryDirectory() as root:
            result = Executor(program, port, root).run()
        self.assertEqual(port.actions, ["build", "measure"])
        self.assertTrue(all(s == "observed-complete" for s in result["nodes"].values()))

    def test_command_success_without_completion_stops_and_retains_stack(self):
        port = RecordingPort(reject="build")
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, "not observed"):
                Executor(self.program(), port, root).run()
            state = json.loads((Path(root) / "execution.json").read_text())
        self.assertEqual(port.actions, ["build"])
        self.assertEqual(state["stack"], ["goal", "goal/module", "build"])
        self.assertEqual(state["nodes"]["measure"], "planned")
        self.assertEqual(state["status"], "failed")

    def test_blocked_program_never_touches_player(self):
        program, port = self.program(), RecordingPort()
        program["blockers"].append("no route")
        with tempfile.TemporaryDirectory() as root, self.assertRaisesRegex(ValueError, "blocked"):
            Executor(self.seal(program), port, root)
        self.assertEqual(port.validations, 0)
        self.assertEqual(port.actions, [])

    def test_digest_and_dependency_cycles_are_rejected_before_actions(self):
        program = self.program()
        program["goal"]["per_minute"] = 100
        with self.assertRaisesRegex(ValueError, "changed"):
            validate(program)
        program = self.program()
        next(n for n in program["nodes"] if n["id"] == "build")["requires"] = ["measure"]
        with self.assertRaisesRegex(ValueError, "cyclic"):
            validate(self.seal(program))

    def test_invalid_parent_tree_is_rejected(self):
        program = self.program()
        program["nodes"][1]["parent"] = "goal/module"
        with self.assertRaisesRegex(ValueError, "hierarchy"):
            validate(self.seal(program))


if __name__ == "__main__":
    unittest.main()
