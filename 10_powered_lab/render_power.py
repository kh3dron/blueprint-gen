#!/usr/bin/env python3
"""Native capture with observed electric energy and lab research progress."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "09_player_capture"))
from render_native import build as build_native, render as render_native


def render(images, frame, playback):
    from PIL import ImageDraw, ImageFont
    picture = render_native(images, frame, playback)
    draw = ImageDraw.Draw(picture)
    font_path = next((p for p in ("/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf") if Path(p).exists()), None)
    font = ImageFont.truetype(font_path, 16) if font_path else ImageFont.load_default(size=16)
    draw.rectangle((972, 402, 1280, 720), fill="#101820")
    x = 980
    def line(y, text, color="#c9d5dc"):
        draw.text((x, y), text, font=font, fill=color)
    line(412, "PRODUCED / IN INVENTORY", "#94a7b4")
    for i, item in enumerate(("iron-plate", "copper-plate", "coal")):
        line(438+24*i, f"{item}: {frame['crafted'].get(item, '--')} / {frame['inventory'].get(item, 0)}")
    entities = {e["name"]: e for e in frame.get("power_entities", [])}
    lab, pole = entities.get("lab", {}), entities.get("small-electric-pole", {})
    packs = lab.get("science") or {}
    line(512, f"Red science: {frame.get('science_produced', 0):g} made / {packs.get('automation-science-pack', 0):g} in lab")
    line(552, "OBSERVED STEAM POWER", "#94a7b4")
    line(578, f"Generation (5s): {pole.get('generation_kw_5s', 0):,.1f} kW")
    line(602, f"Lab load (5s): {pole.get('lab_load_kw_5s', 0):,.1f} kW")
    line(632, f"Automation research: {frame.get('automation_progress', 0)*100:.0f}%", "#78ddab")
    line(668, "10 science/min: not yet complete", "#f1bd8a")
    line(694, "Native frames + observed state", "#94a7b4")
    return picture


def build(run, destination, **kwargs):
    return build_native(run, destination, render_frame=render, **kwargs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--playback", type=float, default=12)
    parser.add_argument("--fps", type=int, default=12)
    args = parser.parse_args()
    print(build(args.run, args.out, playback=args.playback, fps=args.fps))
