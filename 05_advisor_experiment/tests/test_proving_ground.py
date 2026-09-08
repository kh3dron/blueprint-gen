"""Configuration and isolation boundaries of the controlled opening map."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from proving_ground import SOURCE, build, validate


class ProvingGroundTest(unittest.TestCase):
    def config(self):
        return json.loads((SOURCE / "config.json").read_text())

    def test_default_is_finite_and_has_opening_materials(self):
        c = validate(self.config())
        self.assertEqual(
            {p["item"] for p in c["patches"]},
            {"iron-ore", "copper-ore", "coal", "stone"},
        )
        self.assertEqual(sum(p["width"] * p["height"] for p in c["patches"]), 256)
        self.assertEqual(c["inventory"]["stone-furnace"], 1)
        self.assertTrue(c["trees"])
        self.assertTrue(c["water"])

    def test_patches_can_move_across_chunk_boundaries(self):
        c = self.config()
        c["patches"][1].update(x=29, y=29)
        self.assertEqual(validate(c), c)

    def test_overlapping_rectangles_and_blocked_spawn_fail(self):
        for kind in ("overlap", "water", "tree"):
            c = self.config()
            if kind == "overlap":
                c["patches"][1].update(x=-24, y=-24)
            else:
                c["water" if kind == "water" else "trees"][0].update(x=0, y=0)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                validate(c)

    def test_unbounded_or_unsupported_inputs_fail(self):
        for field, value in (
            ("amount", 0),
            ("amount", float("inf")),
            ("amount", True),
            ("width", 100000),
            ("x", 0.5),
            ("item", "crude-oil"),
        ):
            c = self.config()
            c["patches"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate(c)

    def test_build_preserves_configuration_and_refuses_existing_output(self):
        c = self.config()
        before = deepcopy(c)
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "scenario"
            build(c, out)
            self.assertEqual(json.loads((out / "config.json").read_text()), c)
            self.assertEqual(c, before)
            self.assertFalse((out / "observer").exists())
            self.assertFalse((out / "designs.lua").exists())
            with self.assertRaises(FileExistsError):
                build(c, out)


if __name__ == "__main__":
    unittest.main()
