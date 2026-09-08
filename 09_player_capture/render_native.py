#!/usr/bin/env python3
"""Encode native Factorio screenshots with the state captured at each image's tick."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import textwrap

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "08_live_executor"))
from render_trace import read_trace, sample_indices


def load_sources(run):
    run = Path(run)
    trace = run / "user-data/script-output/native-trace.jsonl"
    images = run / "graphical/user-data/script-output"
    frames = read_trace(trace)
    evidence = []
    from PIL import Image
    for frame in frames:
        relative = frame.get("image", "")
        if not re.fullmatch(r"native/frame-[0-9]{6}\.png", relative):
            raise ValueError("invalid native image path")
        path = images / relative
        if not path.is_file():
            raise ValueError(f"missing native frame at tick {frame['tick']}: {relative}")
        with Image.open(path) as picture:
            picture.load()
            if picture.size != (960, 640):
                raise ValueError("unexpected native screenshot resolution")
        evidence.append({"frame": frame["frame"], "tick": frame["tick"], "image": relative,
                         "sha256": sha256(path.read_bytes()).hexdigest()})
    return trace, images, frames, evidence


def render(images, frame, playback):
    from PIL import Image, ImageDraw, ImageFont
    picture = Image.new("RGB", (1280, 720), "#101820")
    with Image.open(images / frame["image"]) as native:
        picture.paste(native.convert("RGB"), (0, 80))
    draw = ImageDraw.Draw(picture)
    def font(size):
        for path in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
            if Path(path).exists():
                return ImageFont.truetype(path, size)
        return ImageFont.load_default(size=size)
    small, normal, heading = font(15), font(18), font(24)
    # The native screenshot camera is centered on the recorded actor. This
    # annotation keeps it locatable even when the engine omits its sprite.
    draw.ellipse((470, 390, 490, 410), outline="#66e1ff", width=2)
    draw.text((495, 380), "Agent position (observed)", font=small, fill="#66e1ff", stroke_width=1, stroke_fill="#101820")
    draw.text((20, 12), "Factorio opening / native game capture", font=heading, fill="#f0f4f6")
    draw.text((20, 47), "Goal: produce 10 red science per minute", font=normal, fill="#b6c5ce")
    draw.text((990, 23), f"Playback: {playback:g}x game time", font=small, fill="#94a7b4")
    x = 980
    draw.text((x, 98), f"Game time {frame['tick']/60:.1f}s", font=heading, fill="#f0f4f6")
    draw.text((x, 132), f"Tick {frame['tick']:,} / {frame['event']}", font=small, fill="#94a7b4")
    action = frame.get("action") or {}
    draw.text((x, 178), "CURRENT SUBGOAL", font=small, fill="#94a7b4")
    draw.text((x, 204), action.get("milestone", "opening"), font=normal, fill="#f7d588")
    draw.text((x, 250), "CURRENT ACTION", font=small, fill="#94a7b4")
    draw.multiline_text((x, 276), "\n".join(textwrap.wrap(action.get("label", "Observe initial environment"), 30)),
                        font=normal, spacing=5, fill="#f0f4f6")
    draw.text((x, 412), "PRODUCED / IN INVENTORY", font=small, fill="#94a7b4")
    for row, item in enumerate(("iron-plate", "copper-plate", "coal", "lab")):
        produced = frame["crafted"].get(item, "--")
        draw.text((x, 438+row*24), f"{item}: {produced} / {frame['inventory'].get(item, 0)}", font=normal, fill="#c9d5dc")
    for row, tech in enumerate(("steam-power", "electronics", "automation-science-pack")):
        unlocked = tech in frame["researched"]
        draw.text((x, 554+row*26), ("Done: " if unlocked else "Pending: ") + tech,
                  font=small, fill="#78ddab" if unlocked else "#94a7b4")
    draw.text((x, 658), "10 science/min: not yet complete", font=small, fill="#f1bd8a")
    draw.text((x, 685), "Native frames + observed state", font=small, fill="#94a7b4")
    return picture


def build(run, destination, *, playback=12, fps=12, mp4=True, render_frame=render):
    trace, images, frames, evidence = load_sources(run)
    indices = sample_indices(frames, fps, playback)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    ffmpeg = shutil.which("ffmpeg") if mp4 else None
    encoder = None
    gif_frames = []
    try:
        if ffmpeg:
            encoder = subprocess.Popen([ffmpeg, "-v", "error", "-f", "rawvideo", "-pixel_format", "rgb24",
                "-video_size", "1280x720", "-framerate", str(fps), "-i", "pipe:0", "-an", "-c:v", "libx264",
                "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                str(destination / "run.mp4")], stdin=subprocess.PIPE)
        last_index = None
        for index in indices:
            if index != last_index:
                picture = render_frame(images, frames[index], playback)
                last_index = index
            if encoder:
                encoder.stdin.write(picture.tobytes())
            gif_frames.append(picture.resize((960, 540)).quantize(colors=128))
        if encoder:
            encoder.stdin.close()
            if encoder.wait(timeout=30):
                raise RuntimeError("ffmpeg failed")
        durations = [round((i+1)*100/fps)*10 - round(i*100/fps)*10 for i in range(len(indices))]
        gif_frames[0].save(destination / "run.gif", save_all=True, append_images=gif_frames[1:],
                           duration=durations, loop=0, optimize=True)
        render_frame(images, frames[-1], playback).save(destination / "poster.png")
        metadata = {"source": str(Path(run).resolve()), "kind": "native Factorio screenshots with synchronized state overlay",
                    "trace_sha256": sha256(trace.read_bytes()).hexdigest(), "source_frames": evidence,
                    "rendered_source_frame_ids": [frames[i]["frame"] for i in indices],
                    "method": "hold latest captured image and its own state together; no interpolation",
                    "missing_frames": 0, "fps": fps, "playback_simulated_seconds_per_second": playback,
                    "first_tick": frames[0]["tick"], "last_tick": frames[-1]["tick"],
                    "duration_seconds": len(indices)/fps, "mp4": bool(ffmpeg), "camera": "follow character; zoom 0.8",
                    "visual_settings": "960x640 source; daylight override; alt mode; no game GUI, clouds or fog"}
        (destination / "recording.json").write_text(json.dumps(metadata, indent=2) + "\n")
    finally:
        if encoder and encoder.poll() is None:
            encoder.terminate()
            encoder.wait(timeout=10)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--playback", type=float, default=12)
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--no-mp4", action="store_true")
    args = parser.parse_args()
    try:
        print(build(args.run, args.out, playback=args.playback, fps=args.fps, mp4=not args.no_mp4))
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f"render-native: {error}\n")
