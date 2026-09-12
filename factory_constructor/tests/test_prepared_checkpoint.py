from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from factory_constructor import checkpoints
from factory_constructor.deployment import record
from factory_constructor.program import save
from test_deployment import evidence


class PreparedCheckpointTest(unittest.TestCase):
    def test_preparation_is_an_inventory_boundary_not_a_completed_service(self):
        e = evidence(10)
        observation = deepcopy(e["inputs"]["final"])
        observation["state"]["inventory"] = {"assembling-machine-1": 3}
        deployment = record(e["program"], observation, e["verification"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "evidence").mkdir()
            for name in ("game.zip", "evidence/actions.json", "evidence/player-crafts.jsonl", "evidence/program.json",
                         "evidence/constructor-verification.json", "evidence/feed-design.json", "evidence/coal-design.json"):
                (root / name).write_text("{}")
            save(root / "driver.json", {"latest_observation": observation})
            save(root / "evidence/deployment.json", deployment)
            save(root / "evidence/execution.json", {"status": "running"})
            manifest = {"schema_version": 1, "stage": "constructor-prepared", "config": {},
                "contract": checkpoints.CONTRACT, "dependencies": {},
                "preparation": {"goal": {"item": "automation-science-pack", "per_minute": 10},
                    "items": {"assembling-machine-1": 3}, "deployment_sha256": deployment["sha256"]},
                "files": {str(p.relative_to(root)): checkpoints.digest_file(p) for p in root.rglob("*") if p.is_file()}}
            save(root / "checkpoint.json", manifest)
            with patch.object(checkpoints, "prerequisites", return_value={}):
                self.assertEqual(checkpoints.validate(root, config={})["stage"], "constructor-prepared")
                observation["state"]["inventory"]["assembling-machine-1"] = 2
                save(root / "driver.json", {"latest_observation": observation})
                manifest["files"]["driver.json"] = checkpoints.digest_file(root / "driver.json")
                save(root / "checkpoint.json", manifest)
                with self.assertRaisesRegex(ValueError, "lacks its construction items"):
                    checkpoints.validate(root, config={})


class FreshSaveTest(unittest.TestCase):
    def test_second_checkpoint_cannot_copy_the_previous_staging_archive(self):
        from types import SimpleNamespace
        e = evidence(10)
        d = record(e["program"], e["inputs"]["final"], e["verification"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save(root / "deployment.json", d)
            staging = root / "user-data/saves/dev-feed-ready.zip"
            staging.parent.mkdir(parents=True)
            staging.write_bytes(b"older completed native save")
            driver = SimpleNamespace(root=root, observations=[e["inputs"]["final"]], session=SimpleNamespace(root=root))
            def native_writer(driver, destination, **kwargs):
                self.assertFalse(staging.exists(), "old ZIP must not satisfy the next save completion check")
                destination.mkdir()
                (destination / "game.zip").write_bytes(b"new completed native save")
                save(destination / "checkpoint.json", {})
                return destination
            with patch.object(checkpoints, "write_checkpoint", side_effect=native_writer):
                result = checkpoints.write(driver, root / "checkpoint", config={})
            self.assertEqual((result / "game.zip").read_bytes(), b"new completed native save")
