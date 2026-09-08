#!/usr/bin/env python3
"""Render actual Factorio observations as a labeled overview GIF, MP4 and poster.

This is recorded-state visualization, not native game footage. No simulated
positions or interpolated production counts are introduced by this renderer.
"""
import argparse
from bisect import bisect_right
from hashlib import sha256
import json
import math
from pathlib import Path
import shutil
import subprocess
import textwrap


def read_trace(path):
    frames = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    if not frames:
        raise ValueError("trace is empty")
    for index, frame in enumerate(frames):
        if (not isinstance(frame, dict) or type(frame.get("tick")) is not int or frame["tick"] < 0
                or type(frame.get("frame")) is not int or frame["frame"] <= 0
                or (index and (frame["tick"] < frames[index - 1]["tick"] or frame["frame"] <= frames[index - 1]["frame"]))):
            raise ValueError("trace frames must retain recorded order and nondecreasing game ticks")
        if not isinstance(frame.get("position"), dict) or not all(isinstance(frame["position"].get(axis), (int, float))
                   and math.isfinite(frame["position"][axis]) for axis in ("x", "y")):
            raise ValueError("invalid recorded position")
    return frames


def sample_indices(frames, fps, playback):
    if not frames or type(fps) is not int or not 1 <= fps <= 60 or not math.isfinite(playback) or not .1 <= playback <= 100:
        raise ValueError("fps must be 1..60 and playback must be 0.1..100 simulated seconds per video second")
    ticks = [f["tick"] for f in frames]
    count = max(1, math.ceil((ticks[-1] - ticks[0]) / 60 / playback * fps))
    if count > 10000:
        raise ValueError("video would exceed 10,000 frames; increase playback speed")
    # Hold the latest real observation. There is no path or inventory interpolation.
    return [max(0, bisect_right(ticks, ticks[0] + i * 60 * playback / fps) - 1) for i in range(count)] + [len(frames) - 1] * fps


def render(world, frames, index, playback):
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new("RGB", (1040, 640), "#101820")
    draw = ImageDraw.Draw(image)
    def font(size):
        for path in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
            if Path(path).exists():
                return ImageFont.truetype(path, size)
        return ImageFont.load_default(size=size)
    small, normal, heading = font(14), font(17), font(23)
    f = frames[index]
    config = world["config"]
    draw.text((24, 16), "Factorio opening / recorded-state replay", font=heading, fill="#f0f4f6")
    draw.text((24, 48), "Goal: 10 red science per minute", font=normal, fill="#b6c5ce")
    draw.text((775, 25), f"Playback: {playback:g}x game time", font=small, fill="#94a7b4")
    # A fixed camera makes placement and spatial progress comparable across the run.
    positions = [p["position"] for p in frames]
    xmin = min([p["x"] for p in positions] + [r["x"] for r in config["patches"]]) - 5
    xmax = max([p["x"] for p in positions] + [r["x"] + r["width"] for r in config["patches"]]) + 5
    ymin = min([p["y"] for p in positions] + [r["y"] for r in config["patches"]]) - 5
    ymax = max([p["y"] for p in positions] + [r["y"] + r["height"] for r in config["patches"]]) + 5
    scale = min(700 / (xmax - xmin), 455 / (ymax - ymin))
    left, top = 20 + (710 - (xmax - xmin) * scale) / 2, 95 + (470 - (ymax - ymin) * scale) / 2
    def xy(p):
        return (left + (p["x"] - xmin) * scale, top + (p["y"] - ymin) * scale)
    draw.rectangle((20, 90, 730, 570), fill="#243e32")
    for x in range(math.ceil(xmin), math.floor(xmax) + 1):
        a, b = xy({"x": x, "y": ymin}), xy({"x": x, "y": ymax})
        draw.line((*a, *b), fill="#2b473a")
    for y in range(math.ceil(ymin), math.floor(ymax) + 1):
        a, b = xy({"x": xmin, "y": y}), xy({"x": xmax, "y": y})
        draw.line((*a, *b), fill="#2b473a")
    colors = {"coal": "#222a30", "iron-ore": "#91a9b9", "copper-ore": "#c98353", "stone": "#b7ad8c"}
    for resource in config["patches"]:
        a = xy(resource)
        b = xy({"x": resource["x"] + resource["width"], "y": resource["y"] + resource["height"]})
        draw.rectangle((*a, *b), fill=colors[resource["item"]])
        for x in range(resource["x"], resource["x"] + resource["width"]):
            for y in range(resource["y"], resource["y"] + resource["height"]):
                cx, cy = xy({"x": x + .5, "y": y + .5})
                draw.ellipse((cx-2, cy-2, cx+2, cy+2), fill="#46524c")
        draw.text((a[0], a[1]-20), resource["item"], fill="#eff3f1", font=small)
    # This view covers the mining row; off-camera water/trees are left outside it.
    path = [xy(frame["position"]) for frame in frames[max(0, index-80):index+1]]
    if len(path) > 1:
        draw.line(path, fill="#86b4a4", width=2)
    for e in f["built"]:
        x, y = xy(e["position"])
        r = scale
        draw.rectangle((x-r, y-r, x+r, y+r), fill="#56636e", outline="#e5ebef", width=2)
        draw.rectangle((x-r/2, y-r/3, x+r/2, y+r/2), fill="#ff9d4d" if e["progress"] else "#202832")
        draw.text((x+14, y+7), f"Furnace #{e['id']} / {e['crafts']} crafts", fill="#f8e7c6", font=small)
    x, y = xy(f["position"])
    draw.ellipse((x-7, y-7, x+7, y+7), fill="#66e1ff", outline="#f6ffff", width=2)
    draw.text((x+11, y-19), "agent", font=small, fill="#a9efff")
    action = f.get("action") or {}
    panel_x = 755
    draw.text((panel_x, 95), f"Game time  {f['tick']//3600:02}:{(f['tick']//60)%60:02}", font=heading, fill="#f0f4f6")
    draw.text((panel_x, 126), f"Tick {f['tick']:,}  |  {f['event']}", font=small, fill="#94a7b4")
    draw.text((panel_x, 165), "CURRENT SUBGOAL", font=small, fill="#94a7b4")
    draw.text((panel_x, 188), action.get("milestone", "initial observation"), font=normal, fill="#f7d588")
    draw.text((panel_x, 228), "CURRENT ACTION", font=small, fill="#94a7b4")
    lines = textwrap.wrap(action.get("label", "Observe initial environment"), 31)
    draw.multiline_text((panel_x, 251), "\n".join(lines[:5]), font=normal, spacing=5, fill="#f0f4f6")
    if f["inventory"].get("lab", 0) and not f["crafted"].get("lab", 0):
        draw.text((panel_x, 348), "Lab present; research not credited.", font=small, fill="#f1bd8a")
    draw.text((panel_x, 376), "PRODUCED / INVENTORY", font=small, fill="#94a7b4")
    for row, item in enumerate(("iron-plate", "copper-plate", "iron-ore", "copper-ore", "coal", "lab")):
        produced = f["crafted"].get(item)
        value = f["inventory"].get(item, 0)
        text = f"{item}:  {produced} / {value}" if produced is not None else f"{item}:  -- / {value}"
        draw.text((panel_x, 402+row*23), text, font=small, fill="#c9d5dc")
    labels = ("Steam power", "Electronics", "Science recipe")
    technologies = ("steam-power", "electronics", "automation-science-pack")
    for i, (label, tech) in enumerate(zip(labels, technologies)):
        x = 24+i*230
        draw.ellipse((x, 595, x+13, 608), fill="#78ddab" if tech in f["researched"] else "#56616b")
        draw.text((x+22, 591), label, font=normal, fill="#d6e1e5")
    draw.text((755, 578), "Science goal: not yet complete", font=small, fill="#f1bd8a")
    draw.text((755, 605), "Observed state, not game footage", font=small, fill="#94a7b4")
    return image


def build(run_directory, destination, *, playback=12, fps=16, mp4=True):
    run_directory, destination = Path(run_directory), Path(destination)
    output = run_directory / "user-data/script-output"
    if not output.is_dir():
        output = run_directory  # Also accept the checked-in raw recording fixtures.
    world = json.loads((output / "live-world.json").read_text())
    frames = read_trace(output / "live-trace.jsonl")
    indices = sample_indices(frames, fps, playback)
    destination.mkdir(parents=True, exist_ok=False)
    ffmpeg = shutil.which("ffmpeg") if mp4 else None
    encoder = None
    gif_frames = []
    try:
        if ffmpeg:
            encoder = subprocess.Popen([ffmpeg, "-v", "error", "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", "1040x640",
                "-framerate", str(fps), "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(destination / "run.mp4")], stdin=subprocess.PIPE)
        for index in indices:
            picture = render(world, frames, index, playback)
            if encoder:
                encoder.stdin.write(picture.tobytes())
            gif_frames.append(picture.quantize(colors=128))
        if encoder:
            encoder.stdin.close()
            if encoder.wait(timeout=30):
                raise RuntimeError("ffmpeg failed")
        # GIF delays have 10 ms resolution. Distribute rounding across frames so
        # arbitrary requested FPS does not silently change the playback speed.
        durations = [round((i+1)*100/fps)*10 - round(i*100/fps)*10 for i in range(len(gif_frames))]
        gif_frames[0].save(destination / "run.gif", save_all=True, append_images=gif_frames[1:],
                           duration=durations, loop=0, optimize=True)
        render(world, frames, len(frames)-1, playback).save(destination / "poster.png")
        (destination / "recording.json").write_text(json.dumps({"source": str(output), "observations": len(frames),
            "trace_sha256": sha256((output / "live-trace.jsonl").read_bytes()).hexdigest(),
            "world_sha256": sha256((output / "live-world.json").read_bytes()).hexdigest(),
            "rendered_frames": len(indices), "fps": fps, "playback_simulated_seconds_per_second": playback,
            "first_tick": frames[0]["tick"], "last_tick": frames[-1]["tick"],
            "method": "hold latest observed state; schematic terrain/entities; no game footage or interpolation",
            "mp4": bool(ffmpeg)}, indent=2) + "\n")
    finally:
        if encoder and encoder.poll() is None:
            encoder.terminate()
            encoder.wait(timeout=10)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--playback", type=float, default=12)
    parser.add_argument("--fps", type=int, default=16)
    parser.add_argument("--no-mp4", action="store_true")
    args = parser.parse_args()
    try:
        print(build(args.run, args.out, playback=args.playback, fps=args.fps, mp4=not args.no_mp4))
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f"render-trace: {error}\n")
