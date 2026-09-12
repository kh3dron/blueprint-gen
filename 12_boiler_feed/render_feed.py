#!/usr/bin/env python3
"""Native footage with consumer-specific fuel and useful research output."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "11_coal_supply"))
from render_coal import render as render_coal
from render_native import build as build_native


def render(images, frame, playback):
    picture = render_coal(images, frame, playback)
    feed = frame.get("feed")
    if not feed:
        return picture
    from PIL import ImageDraw, ImageFont
    path = next((p for p in ("/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf") if Path(p).exists()), None)
    font = ImageFont.truetype(path, 16) if path else ImageFont.load_default(size=16)
    draw = ImageDraw.Draw(picture)
    draw.rectangle((972,402,1280,720), fill="#101820")
    power = {e["address"]:e for e in feed["power_entities"]}
    boiler,pole = power["power.boiler"],power["power.pole"]
    lines = [
        (412,"AUTOMATIC BOILER FUEL","#94a7b4"),
        (442,f"Coal delivered to boiler: {feed['delivered']}","#78ddab"),
        (470,f"Boiler fuel: {boiler.get('fuel',{}).get('coal',0)} coal","#c9d5dc"),
        (498,f"Currently burning: {boiler.get('burning_j',0)/1e6:.2f} MJ","#c9d5dc"),
        (536,f"Lab demand: {pole['lab_load_kw_5s']:.1f} kW","#c9d5dc"),
        (564,f"Generation: {pole['generation_kw_5s']:.1f} kW","#c9d5dc"),
        (600,f"Logistics research: {feed['research_progress']:.0%}","#78ddab"),
        (632,"Load: twenty paid science packs","#94a7b4"),
        (664,"10 science/min: not yet complete","#f1bd8a"),
        (696,"Native frames + observed state","#94a7b4")]
    for y,text,color in lines:
        draw.text((980,y),text,font=font,fill=color)
    return picture


def build(run, destination, **kwargs):
    return build_native(run, destination, render_frame=render, **kwargs)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run",type=Path)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--playback",type=float,default=12)
    parser.add_argument("--fps",type=int,default=12)
    args=parser.parse_args()
    print(build(args.run,args.out,playback=args.playback,fps=args.fps))
