"""Recordings preserve observed chronology and never interpolate imagined state."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from render_trace import read_trace, sample_indices, build


class RecordingTest(unittest.TestCase):
    def test_sampling_holds_real_observations_and_includes_final_state(self):
        frames = [{"tick": 0}, {"tick": 60}, {"tick": 120}]
        indices = sample_indices(frames, fps=2, playback=1)
        self.assertEqual(indices, [0, 0, 1, 1, 2, 2])

    def test_real_trace_contains_movement_paid_building_and_crafting(self):
        frames = read_trace(HERE / "integration/fixtures/live-trace.jsonl")
        self.assertEqual(frames[0]["inventory"]["stone-furnace"], 1)
        self.assertEqual(frames[-1]["inventory"]["lab"], 1)
        self.assertGreater(len({(f["position"]["x"], f["position"]["y"]) for f in frames}), 20)
        self.assertEqual(frames[-1]["built"][0]["crafts"], 65)
        self.assertTrue(any(f["built"] and f["built"][0]["progress"] > 0 for f in frames))

    def test_out_of_order_or_nonfinite_trace_is_refused(self):
        a = {"frame": 1, "tick": 10, "position": {"x": 0, "y": 0}}
        for b in ({"frame": 2, "tick": 9, "position": {"x": 0, "y": 0}},
                  {"frame": 1, "tick": 20, "position": {"x": 0, "y": 0}},
                  {"frame": 2, "tick": 20, "position": {"x": float("nan"), "y": 0}}):
            with tempfile.TemporaryDirectory() as d:
                path = Path(d) / "trace.jsonl"
                path.write_text(json.dumps(a) + "\n" + json.dumps(b) + "\n")
                with self.assertRaises(ValueError):
                    read_trace(path)

    def test_invalid_playback_parameters_are_refused(self):
        for fps, playback in ((0, 1), (61, 1), (16, 0), (16, float("nan"))):
            with self.subTest(fps=fps, playback=playback), self.assertRaises(ValueError):
                sample_indices([{"tick": 0}], fps, playback)

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow is an optional recording dependency")
    def test_exported_gif_has_animation_timing_and_cannot_overwrite_source(self):
        from PIL import Image
        fixtures = HERE / "integration/fixtures"
        frames = read_trace(fixtures / "live-trace.jsonl")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / "source"
            source.mkdir()
            (source / "live-world.json").write_bytes((fixtures / "live-world.json").read_bytes())
            (source / "live-trace.jsonl").write_text("\n".join(json.dumps(f) for f in (frames[0], frames[-1])))
            with self.assertRaises(FileExistsError):
                build(source, source, playback=100, fps=1, mp4=False)
            output = build(source, root / "video", playback=100, fps=1, mp4=False)
            metadata = json.loads((output / "recording.json").read_text())
            with Image.open(output / "run.gif") as gif:
                self.assertGreater(gif.n_frames, 1)
                total = 0
                for i in range(gif.n_frames):
                    gif.seek(i)
                    total += gif.info["duration"]
            self.assertAlmostEqual(total, metadata["rendered_frames"] * 1000, delta=10)
            self.assertEqual(len(metadata["trace_sha256"]), 64)
            self.assertFalse(metadata["mp4"])


if __name__ == "__main__":
    unittest.main()
