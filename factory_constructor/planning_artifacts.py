"""Portable stage viewer, SVG site maps, and Factorio blueprint-book encoding."""
import base64
from html import escape
import json
from pathlib import Path
import zlib

from .program import save
from .science_layout import _cells


def encode_blueprint(document):
    raw = json.dumps(document, separators=(",", ":"), allow_nan=False).encode()
    return "0" + base64.b64encode(zlib.compress(raw)).decode()


def blueprint(stage, version):
    entities = []
    for number, spec in enumerate(stage["placements"], 1):
        entity = {"entity_number": number, "name": spec["name"],
                  "position": spec["position"], "direction": spec["direction"]}
        # Furnaces choose their recipe from inputs and cannot set an assembler recipe.
        if spec["name"].startswith("assembling-machine") and spec.get("recipe"):
            entity["recipe"] = spec["recipe"]
        if spec.get("type"):
            entity["type"] = spec["type"]
        if spec.get("output_priority"):
            entity["output_priority"] = spec["output_priority"]
        entities.append(entity)
    parts = [int(p) for p in version.split(".")]
    packed_version = (parts[0] << 48) | (parts[1] << 32) | (parts[2] << 16)
    ids = {spec["address"]: i for i, spec in enumerate(stage["placements"], 1)}
    wires = [[ids[c["from"]], 5, ids[c["to"]], 5] for c in stage.get("connections", []) if c["kind"] == "wire"]
    return {"blueprint": {"item": "blueprint", "version": packed_version,
                          "label": stage["title"] + " [build plan]", "entities": entities, "wires": wires,
                          "description": stage["instruction"] + "\nCumulative build plan with routed belts, inserters, underground crossings and power wires. Static geometry checked; startup and sustained production remain unverified in the game."}}


COLORS = {"coal": "#444951", "iron-ore": "#729cbb", "copper-ore": "#c98755", "stone": "#acac92"}
LABELS = {"stone-furnace": "F", "burner-mining-drill": "D", "assembling-machine-1": "A",
          "lab": "LAB", "boiler": "B", "steam-engine": "STEAM", "offshore-pump": "P", "pipe": "", "small-electric-pole": "+", "wooden-chest": "C", "splitter": "S"}


def bounds(plan):
    positions = [e["position"] for e in plan["stages"][-1]["placements"] + plan["survey"]["resources"]]
    positions += plan["survey"]["water_tiles"]
    return (min(p["x"] for p in positions) - 5, min(p["y"] for p in positions) - 5,
            max(p["x"] for p in positions) + 5, max(p["y"] for p in positions) + 5)


def site_svg(plan, stage):
    xmin, ymin, xmax, ymax = bounds(plan)
    added = {e["address"] for e in stage["additions"]}
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{xmin} {ymin} {xmax-xmin} {ymax-ymin}" role="img" aria-label="{escape(stage["title"])} site plan">',
           '<defs><pattern id="grid" width="1" height="1" patternUnits="userSpaceOnUse"><path d="M 1 0 L 0 0 0 1" fill="none" stroke="#283a42" stroke-width=".035"/></pattern></defs>',
           f'<rect x="{xmin}" y="{ymin}" width="{xmax-xmin}" height="{ymax-ymin}" fill="#12242d"/>',
           f'<rect x="{xmin}" y="{ymin}" width="{xmax-xmin}" height="{ymax-ymin}" fill="url(#grid)"/>']
    for tile in plan["survey"]["water_tiles"]:
        out.append(f'<rect x="{tile["x"]}" y="{tile["y"]}" width="1" height="1" fill="#286681"/>')
    for resource in plan["survey"]["resources"]:
        x, y = resource["position"]["x"], resource["position"]["y"]
        out.append(f'<rect x="{x-.5}" y="{y-.5}" width="1" height="1" fill="{COLORS.get(resource["prototype"], "#555")}" opacity=".65"/>')
    for obstacle in plan["survey"]["obstacles"]:
        if obstacle["entity_type"] != "character":
            p = obstacle["position"]
            out.append(f'<circle cx="{p["x"]}" cy="{p["y"]}" r=".7" fill="#4f7651"/>')
    for item in COLORS:
        tiles = [r["position"] for r in plan["survey"]["resources"] if r["prototype"] == item]
        if tiles:
            x, y = min(p["x"] for p in tiles) - .5, min(p["y"] for p in tiles) - 1.2
            out.append(f'<text x="{x}" y="{y}" fill="#bbced7" font-family="sans-serif" font-size="1">{item}</text>')
    entities = {e["address"]: e for e in stage["placements"]}
    for connection in stage.get("connections", []):
        if connection["kind"] not in {"wire", "underground"}:
            continue
        a, b = entities[connection["from"]]["position"], entities[connection["to"]]["position"]
        color = "#c88645" if connection["kind"] == "wire" else "#dbd47f"
        dash = "" if connection["kind"] == "wire" else ' stroke-dasharray=".3 .3"'
        out.append(f'<line x1="{a["x"]}" y1="{a["y"]}" x2="{b["x"]}" y2="{b["y"]}" stroke="{color}" stroke-width=".065" opacity=".7"{dash}/>')
    for entity in sorted(stage["placements"], key=lambda e: e["name"] not in {"transport-belt", "underground-belt", "splitter"}):
        cells = _cells(entity)
        x, y = min(x for x, y in cells), min(y for x, y in cells)
        w, h = max(cx for cx, cy in cells) - x + 1, max(cy for cx, cy in cells) - y + 1
        color = "#f2b85c" if entity["address"] in added else "#94b5bd"
        label = LABELS.get(entity["name"], "?")
        title = escape(f'{entity["address"]} · {entity.get("recipe", entity["name"])} · ({entity["position"]["x"]}, {entity["position"]["y"]})')
        if entity["name"] in {"transport-belt", "underground-belt", "inserter"}:
            px, py = entity["position"]["x"], entity["position"]["y"]
            angle = {0: -90, 4: 0, 8: 90, 12: 180}[entity["direction"]]
            out.append(f'<g data-entity="{entity["name"]}"><title>{title}</title>')
            if entity["name"] == "inserter":
                # Inserter direction is the pickup side; the arrow points to drop.
                out.append(f'<g transform="translate({px} {py}) rotate({angle+180})"><circle r=".23" fill="{color}"/><path d="M -.9 0 L .9 0 M .6 -.2 L .9 0 L .6 .2" fill="none" stroke="{color}" stroke-width=".12"/></g>')
            else:
                fill = "#6e6641" if entity["name"] == "transport-belt" else "#a18a48"
                out.append(f'<g transform="translate({px} {py}) rotate({angle})"><rect x="-.47" y="-.4" width=".94" height=".8" fill="{fill}" stroke="{color}" stroke-width=".06"/><path d="M -.22 -.2 L .08 0 L -.22 .2 M .08 -.2 L .38 0 L .08 .2" fill="none" stroke="{color}" stroke-width=".08"/>')
                if entity["name"] == "underground-belt":
                    hood_x = -.43 if entity["type"] == "output" else .08
                    out.append(f'<rect x="{hood_x}" y="-.4" width=".35" height=".8" fill="#293b43"/>')
                out.append('</g>')
            out.append('</g>')
            continue
        out.append(f'<g><title>{title}</title><rect x="{x+.09}" y="{y+.09}" width="{w-.18}" height="{h-.18}" rx=".14" fill="#263c44" stroke="{color}" stroke-width=".16"/>')
        out.append(f'<text x="{x+w/2}" y="{y+h/2+.25}" text-anchor="middle" fill="{color}" font-family="sans-serif" font-size=".75">{label}</text>')
        if entity["name"] == "assembling-machine-1":
            recipe = entity["recipe"]
            tag = {"automation-science-pack": "RED", "logistic-science-pack": "GREEN", "iron-gear-wheel": "GEAR",
                   "electronic-circuit": "CIRCUIT", "copper-cable": "CABLE", "transport-belt": "BELT", "inserter": "INS"}.get(recipe, recipe)
            out.append(f'<text x="{x+w/2}" y="{y+h+1}" text-anchor="middle" fill="{color}" font-family="sans-serif" font-size=".8">{escape(tag)}</text>')
        out.append('</g>')
    out.append('</svg>')
    return "".join(out)


def write_progression(plan, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    save(out / "plan.json", plan)
    book = []
    maps = []
    for index, stage in enumerate(plan["stages"]):
        bp = blueprint(stage, plan["source"]["factorio_version"])
        book.append({"index": index, **bp})
        name = f'{index+1:02d}-{stage["id"]}'
        (out / (name + ".txt")).write_text(encode_blueprint(bp) + "\n")
        svg = site_svg(plan, stage)
        (out / (name + ".svg")).write_text(svg)
        maps.append(svg)
    document = {"blueprint_book": {"item": "blueprint-book", "label": "Fresh start to red + green science [build plans]",
                                  "version": book[0]["blueprint"]["version"], "active_index": 0, "blueprints": book}}
    save(out / "blueprint-book.json", document)
    (out / "blueprint-book.txt").write_text(encode_blueprint(document) + "\n")
    payload = {"plan": plan, "maps": maps, "blueprints": [encode_blueprint({"blueprint": e["blueprint"]}) for e in book]}
    template = Path(__file__).with_name("planning_viewer.html").read_text()
    # No user-controlled string may terminate the embedded JSON script element.
    data = json.dumps(payload, separators=(",", ":")).replace("<", "\\u003c").replace("&", "\\u0026")
    (out / "index.html").write_text(template.replace("__PLAN_DATA__", data))
    return out / "index.html"
