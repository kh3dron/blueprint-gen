#!/usr/bin/env python3
"""Copy the game sprites render.py needs into ./sprites.

    python fetch_sprites.py [--factorio PATH]

Icons: 64x64 crop of the mipmap strip for every entity in entities.json with an icon.
Belts: full animation sheets for every transport-belt prototype (frame 0 of each direction row is used).
"""
import argparse
import json
import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FACTORIO = os.path.expanduser(
    "~/Library/Application Support/Steam/steamapps/common/Factorio/factorio.app/Contents/data")
ICON_SIZE = 64


def resolve(path, data_dir):
    # "__base__/graphics/icons/x.png" -> <data_dir>/base/graphics/icons/x.png
    assert path.startswith("__"), path
    mod, rest = path[2:].split("__/", 1)
    return os.path.join(data_dir, mod, rest)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--factorio", default=DEFAULT_FACTORIO, help="Factorio data directory")
    args = ap.parse_args()
    if not os.path.isdir(args.factorio):
        sys.exit(f"not a directory: {args.factorio}")

    with open(os.path.join(HERE, "entities.json")) as f:
        entities = json.load(f)

    icon_dir = os.path.join(HERE, "sprites", "icons")
    belt_dir = os.path.join(HERE, "sprites", "belts")
    os.makedirs(icon_dir, exist_ok=True)
    os.makedirs(belt_dir, exist_ok=True)

    # Every icon from every mod's graphics/icons tree (entities, items, fluids, recipes),
    # flattened by basename. Later mods do not overwrite earlier ones.
    copied = 0
    for mod in ("base", "space-age", "quality", "elevated-rails", "recycler"):
        root = os.path.join(args.factorio, mod, "graphics", "icons")
        for dirpath, _, files in os.walk(root):
            for fn in sorted(files):
                if not fn.endswith(".png"):
                    continue
                dst = os.path.join(icon_dir, fn)
                if os.path.exists(dst):
                    continue
                im = Image.open(os.path.join(dirpath, fn)).convert("RGBA")
                if im.height <= ICON_SIZE and im.width > im.height:
                    im = im.crop((0, 0, im.height, im.height))  # mipmap strip: keep level 0
                im.save(dst)
                copied += 1
    print(f"icons: {copied} copied")

    missing = 0
    for e in entities:
        if e["icon"] and e["collision_box"]:
            if not os.path.exists(os.path.join(icon_dir, os.path.basename(e["icon"]))):
                missing += 1
                print(f"MISSING icon for {e['name']}: {e['icon']}", file=sys.stderr)
    print(f"entity icons missing: {missing}")

    copied = 0
    for e in entities:
        if e["type"] != "transport-belt":
            continue
        for mod in ("base", "space-age"):
            src = os.path.join(args.factorio, mod, "graphics", "entity", e["name"], e["name"] + ".png")
            if os.path.exists(src):
                im = Image.open(src).convert("RGBA")
                # 20 direction rows; keep only frame 0 of each row.
                row_h = im.height // 20
                frame_w = row_h  # frames are square
                out = Image.new("RGBA", (frame_w, im.height))
                for r in range(20):
                    out.paste(im.crop((0, r * row_h, frame_w, (r + 1) * row_h)), (0, r * row_h))
                out.save(os.path.join(belt_dir, e["name"] + ".png"))
                copied += 1
                break
        else:
            print(f"MISSING belt sheet {e['name']}", file=sys.stderr)
    print(f"belts: {copied} copied")


if __name__ == "__main__":
    main()
