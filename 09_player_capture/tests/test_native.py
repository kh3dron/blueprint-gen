"""Reject incomplete/misbound image evidence; exercise actual GIF export."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from render_native import build, load_sources


class NativeRecordingTest(unittest.TestCase):
    def source(self, root):
        from PIL import Image
        trace = root / "user-data/script-output/native-trace.jsonl"
        trace.parent.mkdir(parents=True)
        image_root = root / "graphical/user-data/script-output/native"
        image_root.mkdir(parents=True)
        state = json.loads((HERE / "integration/fixtures/final-observation.json").read_text())["state"]
        frames = [{**state, "frame": i+1, "tick": i*60, "image": f"native/frame-{i+1:06}.png", "event": "sample"} for i in range(2)]
        trace.write_text("\n".join(json.dumps(f) for f in frames) + "\n")
        for i in range(2):
            Image.new("RGB", (960, 640), ["#223344", "#445566"][i]).save(image_root / f"frame-{i+1:06}.png")
        return trace, image_root, frames

    def test_missing_native_frame_is_refused_before_creating_video(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, images, _ = self.source(root)
            (images / "frame-000002.png").unlink()
            with self.assertRaisesRegex(ValueError, "missing native frame"):
                build(root, root / "recording", mp4=False)
            self.assertFalse((root / "recording").exists())

    def test_paths_cannot_escape_native_image_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trace, _, frames = self.source(root)
            frames[0]["image"] = "../unrelated.png"
            trace.write_text("\n".join(json.dumps(f) for f in frames))
            with self.assertRaisesRegex(ValueError, "image path"):
                load_sources(root)

    def test_gif_manifest_binds_images_to_observed_ticks_and_playback(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.source(root)
            out = build(root, root / "recording", fps=4, playback=1, mp4=False)
            metadata = json.loads((out / "recording.json").read_text())
            self.assertEqual(metadata["rendered_source_frame_ids"], [1]*4 + [2]*4)
            self.assertEqual(metadata["duration_seconds"], 2)
            self.assertEqual(metadata["missing_frames"], 0)
            self.assertNotEqual(metadata["source_frames"][0]["sha256"], metadata["source_frames"][1]["sha256"])
            with Image.open(out / "run.gif") as gif:
                duration = 0
                for i in range(gif.n_frames):
                    gif.seek(i)
                    duration += gif.info["duration"]
                self.assertEqual(duration, 2000)
                self.assertEqual(gif.size, (960, 540))


if __name__ == "__main__":
    unittest.main()
