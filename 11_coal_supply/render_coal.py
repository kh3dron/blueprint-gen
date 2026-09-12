#!/usr/bin/env python3
"""Native footage with observed extraction, output and burner fuel buffers."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "10_powered_lab"))
from render_power import render as render_power
from render_native import build as build_native


def render(images, frame, playback):
    picture = render_power(images, frame, playback)
    coal = frame.get("coal", {})
    entities = {e["address"]: e for e in coal.get("entities", [])}
    if not entities:
        return picture
    from PIL import ImageDraw, ImageFont
    font_path = next((p for p in ("/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf") if Path(p).exists()), None)
    font = ImageFont.truetype(font_path, 16) if font_path else ImageFont.load_default(size=16)
    draw = ImageDraw.Draw(picture)
    draw.rectangle((972, 402, 1280, 720), fill="#101820")
    def line(y, text, color="#c9d5dc"):
        draw.text((980, y), text, font=font, fill=color)
    line(412, "OBSERVED COAL MODULE", "#94a7b4")
    chest = (entities.get("coal.chest", {}).get("contents") or {}).get("coal", 0)
    line(440, f"Coal delivered to chest: {chest}", "#78ddab")
    seed = frame.get("coal_seed")
    if seed:
        line(466, f"Coal mined since seeding: {coal['produced']-seed['after']['produced']:g}")
        line(490, f"Elapsed since seeding: {(frame['tick']-seed['tick'])/60:.1f}s")
    for i, address in enumerate(("coal.drill", "coal.refuel", "coal.export")):
        e = entities.get(address, {})
        fuel = (e.get("fuel") or {}).get("coal", 0)
        line(526+26*i, f"{address[5:]}: {fuel} coal + {e.get('burning_j', 0)/1e6:.2f} MJ")
    line(618, f"Coal left under drill: {coal.get('deposit_remaining', 0):,}")
    line(646, "Target: >=10 coal/min into storage", "#94a7b4")
    line(672, "10 science/min: not yet complete", "#f1bd8a")
    line(696, "Native frames + observed state", "#94a7b4")
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
