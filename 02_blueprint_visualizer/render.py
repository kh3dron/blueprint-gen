#!/usr/bin/env python3
"""Render a Factorio blueprint string to PNG.

    python render.py <blueprint-string | file | -> [-o out.png] [--tile PX] [--index N] [--labels]

Requires entities.json (extract_entities.lua) and sprites/ (fetch_sprites.py) next to this file.
"""
import argparse
import base64
import json
import math
import os
import sys
import zlib
from collections import defaultdict

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SPRITES = os.path.join(HERE, "sprites")

BG = (40, 40, 40, 255)
GRID = (56, 56, 56, 255)
BOX_FILL = (90, 90, 90, 160)
BOX_LINE = (140, 140, 140, 255)
ARROW = (255, 220, 60, 255)
WIRE = {1: (230, 60, 60, 255), 2: (60, 200, 60, 255), 3: (230, 60, 60, 255), 4: (60, 200, 60, 255)}
COPPER = (210, 130, 60, 255)
PORT_IN = (80, 220, 120, 255)
PORT_OUT = (255, 150, 50, 255)
TILE_COLORS = {
    "stone-path": (120, 115, 105, 255),
    "concrete": (95, 100, 105, 255),
    "refined-concrete": (80, 85, 95, 255),
    "hazard-concrete-left": (150, 130, 40, 255),
    "hazard-concrete-right": (150, 130, 40, 255),
    "refined-hazard-concrete-left": (140, 120, 40, 255),
    "refined-hazard-concrete-right": (140, 120, 40, 255),
    "landfill": (90, 80, 50, 255),
    "space-platform-foundation": (70, 75, 90, 255),
    "foundation": (100, 95, 85, 255),
}

# 16-way direction -> unit vector (dx, dy); y grows downward (south).
DIRS = {0: (0, -1), 4: (1, 0), 8: (0, 1), 12: (-1, 0)}
OPP = {0: 8, 4: 12, 8: 0, 12: 4}
BELT_TYPES = {"transport-belt", "underground-belt", "splitter", "loader", "loader-1x1", "linked-belt"}
# Belt sheet row (0-based) by (belt direction, feeding direction). Rows from transport-belts.lua.
BELT_ROW_STRAIGHT = {4: 0, 12: 1, 0: 2, 8: 3}
# (belt direction, travel direction of the feeding belt) -> 0-based sheet row.
# Sheet names are side_to_side: "north_to_east" enters from the NORTH side (feeder travelling south)
# and exits east. Feeder travelling N enters from the south side, etc.
BELT_ROW_CURVE = {
    (0, 12): 4,   # east_to_north:  exits N, feeder travels W (enters from east side)
    (4, 8): 5,    # north_to_east:  exits E, feeder travels S
    (0, 4): 6,    # west_to_north:  exits N, feeder travels E
    (12, 8): 7,   # north_to_west:  exits W, feeder travels S
    (4, 0): 8,    # south_to_east:  exits E, feeder travels N
    (8, 12): 9,   # east_to_south:  exits S, feeder travels W
    (12, 0): 10,  # south_to_west:  exits W, feeder travels N
    (8, 4): 11,   # west_to_south:  exits S, feeder travels E
}
# Types that get a direction arrow drawn on top of the icon.
ARROW_TYPES = {"inserter", "underground-belt", "splitter", "loader", "loader-1x1", "mining-drill",
               "pump", "offshore-pump", "linked-belt", "train-stop", "rail-signal", "rail-chain-signal",
               "boiler", "valve"}
LAYER = {"transport-belt": 0, "underground-belt": 0, "splitter": 0, "loader": 0, "loader-1x1": 0,
         "pipe": 0, "pipe-to-ground": 0, "straight-rail": 0, "curved-rail-a": 0, "curved-rail-b": 0,
         "half-diagonal-rail": 0, "heat-pipe": 0,
         "inserter": 2, "electric-pole": 2, "rail-signal": 2, "rail-chain-signal": 2}


def decode(s):
    s = s.strip()
    if s.startswith("{"):
        return json.loads(s)
    if s[0] != "0":
        sys.exit(f"unsupported blueprint string version byte: {s[0]!r}")
    return json.loads(zlib.decompress(base64.b64decode(s[1:])))


def pick_blueprint(obj, index):
    if "blueprint" in obj:
        return obj["blueprint"]
    if "blueprint_book" in obj:
        book = obj["blueprint_book"]
        entries = [b for b in book.get("blueprints", []) if "blueprint" in b]
        if not entries:
            sys.exit("blueprint book contains no blueprints")
        if index is None:
            index = book.get("active_index", 0)
        for b in entries:
            if b.get("index") == index:
                return b["blueprint"]
        print(f"index {index} not in book; using first of {len(entries)}", file=sys.stderr)
        return entries[0]["blueprint"]
    sys.exit(f"unrecognized top-level keys: {list(obj)}")


def load_entities():
    with open(os.path.join(HERE, "entities.json")) as f:
        return {e["name"]: e for e in json.load(f)}


def footprint(proto, direction):
    box = proto["collision_box"] if proto and proto["collision_box"] else [-0.5, -0.5, 0.5, 0.5]
    w = max(1, math.ceil(box[2] - box[0] - 0.01))
    h = max(1, math.ceil(box[3] - box[1] - 0.01))
    if direction in (4, 12):
        w, h = h, w
    return w, h


_icon_cache = {}


def icon(name):
    if name in _icon_cache:
        return _icon_cache[name]
    path = os.path.join(SPRITES, "icons", name + ".png")
    im = Image.open(path).convert("RGBA") if os.path.exists(path) else None
    _icon_cache[name] = im
    return im


_belt_cache = {}


def belt_frame(name, row):
    key = (name, row)
    if key in _belt_cache:
        return _belt_cache[key]
    path = os.path.join(SPRITES, "belts", name + ".png")
    if not os.path.exists(path):
        _belt_cache[key] = None
        return None
    sheet = Image.open(path).convert("RGBA")
    fw = sheet.width
    frame = sheet.crop((0, row * fw, fw, (row + 1) * fw))
    _belt_cache[key] = frame
    return frame


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="blueprint string, path to a file containing one, or - for stdin")
    ap.add_argument("-o", "--out", help="output PNG (default: <label>.png)")
    ap.add_argument("--tile", type=int, default=32, help="pixels per tile (default 32)")
    ap.add_argument("--index", type=int, help="blueprint index when given a book")
    ap.add_argument("--labels", action="store_true", help="print entity names on each footprint")
    args = ap.parse_args()

    if args.source == "-":
        raw = sys.stdin.read()
    elif os.path.exists(args.source):
        with open(args.source) as f:
            raw = f.read()
    else:
        raw = args.source
    bp = pick_blueprint(decode(raw), args.index)
    protos = load_entities()
    T = args.tile

    entities = bp.get("entities", [])
    tiles = bp.get("tiles", [])
    if not entities and not tiles:
        sys.exit("blueprint has no entities or tiles")

    placed = []  # (entity, proto, x1, y1, w, h)
    for e in entities:
        p = protos.get(e["name"])
        if p is None:
            print(f"unknown entity {e['name']}; drawing as 1x1", file=sys.stderr)
        d = e.get("direction", 0)
        w, h = footprint(p, d)
        x1 = e["position"]["x"] - w / 2
        y1 = e["position"]["y"] - h / 2
        placed.append((e, p, x1, y1, w, h))

    xs = [x1 for _, _, x1, _, _, _ in placed] + [t["position"]["x"] for t in tiles]
    ys = [y1 for _, _, _, y1, _, _ in placed] + [t["position"]["y"] for t in tiles]
    xe = [x1 + w for _, _, x1, _, w, _ in placed] + [t["position"]["x"] + 1 for t in tiles]
    ye = [y1 + h for _, _, _, y1, _, h in placed] + [t["position"]["y"] + 1 for t in tiles]
    minx, miny = math.floor(min(xs)) - 1, math.floor(min(ys)) - 1
    maxx, maxy = math.ceil(max(xe)) + 1, math.ceil(max(ye)) + 1
    W, H = (maxx - minx) * T, (maxy - miny) * T

    img = Image.new("RGBA", (W, H), BG)
    draw = ImageDraw.Draw(img, "RGBA")

    def px(x, y):
        return ((x - minx) * T, (y - miny) * T)

    # tiles
    for t in tiles:
        x0, y0 = px(t["position"]["x"], t["position"]["y"])
        draw.rectangle([x0, y0, x0 + T - 1, y0 + T - 1], fill=TILE_COLORS.get(t["name"], (110, 110, 110, 255)))

    # grid
    for gx in range(minx, maxx + 1):
        x0, _ = px(gx, 0)
        draw.line([(x0, 0), (x0, H)], fill=GRID)
    for gy in range(miny, maxy + 1):
        _, y0 = px(0, gy)
        draw.line([(0, y0), (W, y0)], fill=GRID)

    # occupancy map for belt curve resolution: tile -> (type, direction)
    occ = {}
    for e, p, x1, y1, w, h in placed:
        if p and p["type"] in BELT_TYPES:
            for ix in range(w):
                for iy in range(h):
                    occ[(math.floor(x1) + ix, math.floor(y1) + iy)] = (p["type"], e.get("direction", 0), e)

    def feeds(tile, into_dir):
        """True if the belt-like entity at tile moves in into_dir (i.e. would feed the tile ahead of it)."""
        o = occ.get(tile)
        if not o:
            return False
        typ, d, e = o
        if typ == "underground-belt" and e.get("type") == "input":
            return False
        return d == into_dir

    def belt_row(e, x1, y1):
        d = e.get("direction", 0)
        if d not in DIRS:
            return BELT_ROW_STRAIGHT[0]
        tx, ty = math.floor(x1), math.floor(y1)
        dx, dy = DIRS[d]
        if feeds((tx - dx, ty - dy), d):
            return BELT_ROW_STRAIGHT[d]
        sides = []
        for sd in DIRS:
            if sd == d or sd == OPP[d]:
                continue
            sx, sy = DIRS[sd]
            if feeds((tx - sx, ty - sy), sd):
                sides.append(sd)
        if len(sides) == 1:
            return BELT_ROW_CURVE[(d, sides[0])]
        return BELT_ROW_STRAIGHT[d]

    font = None
    if args.labels:
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", max(8, T // 4))
        except OSError:
            font = ImageFont.load_default()

    # entities
    order = sorted(placed, key=lambda t: (LAYER.get(t[1]["type"], 1) if t[1] else 1, t[3], t[2]))
    for e, p, x1, y1, w, h in order:
        x0, y0 = px(x1, y1)
        x0, y0 = int(round(x0)), int(round(y0))
        pw, ph = w * T, h * T
        typ = p["type"] if p else None
        d = e.get("direction", 0)

        if typ == "transport-belt":
            frame = belt_frame(e["name"], belt_row(e, x1, y1))
            if frame is not None:
                size = 2 * T  # 128px frame at scale 0.5 covers 2 tiles
                fr = frame.resize((size, size), Image.LANCZOS)
                img.alpha_composite(fr, (x0 - T // 2, y0 - T // 2))
                continue

        draw.rectangle([x0, y0, x0 + pw - 1, y0 + ph - 1], fill=BOX_FILL, outline=BOX_LINE)
        ic = icon(e["name"]) or (icon(os.path.basename(p["icon"])[:-4]) if p and p["icon"] else None)
        if ic is not None:
            s = int(min(pw, ph) * 0.85)
            ic = ic.resize((s, s), Image.LANCZOS)
            img.alpha_composite(ic, (x0 + (pw - s) // 2, y0 + (ph - s) // 2))

        if e.get("recipe") and min(w, h) >= 2:
            ric = icon(e["recipe"])
            if ric is not None:
                s = T
                ric = ric.resize((s, s), Image.LANCZOS)
                bx, by = x0 + pw - s - 2, y0 + ph - s - 2
                draw.rectangle([bx - 1, by - 1, bx + s, by + s], fill=(0, 0, 0, 180))
                img.alpha_composite(ric, (bx, by))

        if typ in ARROW_TYPES and d in DIRS:
            dx, dy = DIRS[d]
            if typ == "inserter":
                dx, dy = -dx, -dy  # inserter direction points at the pickup side
            cx, cy = x0 + pw / 2, y0 + ph / 2
            L = min(pw, ph) * 0.42
            ax, ay = cx + dx * L, cy + dy * L
            bx, by = cx - dx * L, cy - dy * L
            draw.line([(bx, by), (ax, ay)], fill=ARROW, width=max(2, T // 10))
            hw = max(3, T // 5)
            nx, ny = -dy, dx
            draw.polygon([(ax + dx * hw * 0.6, ay + dy * hw * 0.6),
                          (ax - dx * hw + nx * hw, ay - dy * hw + ny * hw),
                          (ax - dx * hw - nx * hw, ay - dy * hw - ny * hw)], fill=ARROW)

        if font is not None or (ic is None and p is None):
            f = font or ImageFont.load_default()
            draw.text((x0 + 2, y0 + 1), e["name"], fill=(255, 255, 255, 255), font=f)

    # wires: [e1, connector1, e2, connector2]
    centers = {e["entity_number"]: (px(e["position"]["x"], e["position"]["y"])) for e in entities}
    for wire in bp.get("wires", []):
        a, ca, b, cb = wire
        if a in centers and b in centers:
            color = WIRE.get(ca, COPPER)
            draw.line([centers[a], centers[b]], fill=color, width=max(1, T // 16))

    # ports (non-vanilla key written by 03_blueprint_objects): {io, kind, item, lane, x, y, direction, rate}
    for p in bp.get("ports", []):
        x0, y0 = px(p["x"], p["y"])
        x0, y0 = int(x0), int(y0)
        color = PORT_IN if p["io"] == "in" else PORT_OUT
        lw = max(2, T // 12)
        draw.rectangle([x0 + 1, y0 + 1, x0 + T - 2, y0 + T - 2], outline=color, width=lw)
        ic = icon(p["item"])
        s = max(8, T // 2)
        # lane badge: left lane on the left half of the tile (relative to flow direction), right on the right
        dx, dy = DIRS.get(p["direction"], (1, 0))
        side = {"left": -1, "right": 1, "both": 0}[p["lane"]]
        nx, ny = -dy * side, dx * side  # right-hand normal of flow
        cx = x0 + T / 2 + nx * T / 4
        cy = y0 + T / 2 + ny * T / 4
        if ic is not None:
            ic = ic.resize((s, s), Image.LANCZOS)
            img.alpha_composite(ic, (int(cx - s / 2), int(cy - s / 2)))
        tag = ("IN" if p["io"] == "in" else "OUT") + ("" if p["lane"] == "both" else p["lane"][0].upper())
        ty = y0 + T - 12 if ny > 0 else y0 + 1
        tx = x0 + T - 6 * len(tag) - 3 if nx > 0 else x0 + 2
        draw.text((tx, ty), tag, fill=color, font=ImageFont.load_default())

    out = args.out or (bp.get("label") or "blueprint").replace("/", "_") + ".png"
    img.convert("RGB").save(out)
    print(f"{out}: {W}x{H}px, {maxx - minx}x{maxy - miny} tiles, {len(entities)} entities, {len(tiles)} tiles")


if __name__ == "__main__":
    main()
