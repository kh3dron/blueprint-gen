"""Template cells from samples/<N>_to_1.md, scaled to n machines.

Template anatomy (all four samples):
  - input belts enter the bottom row northbound, left to right = input 1..N
  - the output belt exits the bottom row southbound in the rightmost column
  - one 3x3 machine; its 3 rows plus the pole row under it form a 4-row CELL
  - bends under/beside the machine merge inputs onto lanes (N=2: in1 -> left lane, in2 -> right lane)

Scaling: cell k (k >= 1) is stacked above the template. A stacked cell keeps every non-belt entity
of the template's machine rows at the same column and row offset, plus the pole, and replaces all
belts by straight belts in the columns that carry a belt in the template's top row.
"""
import base64
import copy
import json
import os
import re
import zlib

from module import Module, Port

SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")
CELL_ROWS = 4
MACHINE_TYPES = {"assembling-machine-1", "assembling-machine-2", "assembling-machine-3", "electric-furnace"}
# items/s each input port can carry on a yellow belt, by template. 15 = whole belt, 7.5 = one lane.
INPUT_CAPACITY = {1: [15.0], 2: [7.5, 7.5], 3: [15.0, 7.5, 7.5], 4: [7.5, 7.5, 7.5, 7.5]}
OUTPUT_CAPACITY = 7.5  # one lane
BELT_SCALE = {"transport-belt": 1.0, "fast-transport-belt": 2.0, "express-transport-belt": 3.0,
              "turbo-transport-belt": 4.0}


def load_template(n_inputs):
    path = os.path.join(SAMPLES, f"{n_inputs}_to_1.md")
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with open(path) as f:
        txt = f.read()
    m = re.search(r"0[A-Za-z0-9+/=]{50,}", txt)
    obj = json.loads(zlib.decompress(base64.b64decode(m.group(0)[1:])))
    bp = obj["blueprint"]
    ents = [dict(e) for e in bp["entities"]]
    # shift so the top-left occupied tile is (0, 0)
    minx = min(e["position"]["x"] - (1.5 if e["name"] in MACHINE_TYPES else 0.5) for e in ents)
    miny = min(e["position"]["y"] - (1.5 if e["name"] in MACHINE_TYPES else 0.5) for e in ents)
    for e in ents:
        e["position"] = {"x": e["position"]["x"] - minx, "y": e["position"]["y"] - miny}
        e.pop("entity_number", None)
    return ents


def analyze(ents):
    machines = [e for e in ents if e["name"] in MACHINE_TYPES]
    if len(machines) != 1:
        raise ValueError(f"template must contain exactly one machine, found {len(machines)}")
    mach = machines[0]
    top = mach["position"]["y"] - 1.5          # machine's top row (tile y)
    pole_row = top + 3
    maxy = max(e["position"]["y"] for e in ents) + 0.5
    maxx = max(e["position"]["x"] + (1.5 if e["name"] in MACHINE_TYPES else 0.5) for e in ents)
    if top != 0:
        raise ValueError(f"machine top row is {top}, expected 0 (belts above the machine are not supported)")
    belt_cols = {}  # column -> direction, from the template's top row
    for e in ents:
        if e["name"].endswith("transport-belt") and e["position"]["y"] == 0.5:
            belt_cols[e["position"]["x"]] = e.get("direction", 0)
    inputs = sorted(e["position"]["x"] for e in ents
                    if e["name"].endswith("transport-belt") and e["position"]["y"] == maxy - 0.5 and e.get("direction", 0) == 0)
    outputs = sorted(e["position"]["x"] for e in ents
                     if e["name"].endswith("transport-belt") and e["position"]["y"] == maxy - 0.5 and e.get("direction", 0) == 8)
    if len(outputs) != 1:
        raise ValueError(f"expected one southbound output belt on the bottom row, found {len(outputs)}")
    poles = [e for e in ents if e["name"].endswith("electric-pole")]
    if len(poles) != 1:
        raise ValueError(f"expected one pole, found {len(poles)}")
    return {
        "machine": mach, "pole": poles[0], "pole_row": pole_row, "belt_cols": belt_cols,
        "inputs": inputs, "output": outputs[0], "width": int(maxx), "height": int(maxy),
        "cell_entities": [e for e in ents
                          if not e["name"].endswith("transport-belt") and not e["name"].endswith("electric-pole")
                          and e["position"]["y"] < pole_row],
    }


def build(item, rate, recipe, rt, machine=None, belt="transport-belt"):
    ings = recipe["ingredients"]
    if any(i["type"] == "fluid" for i in ings) or any(r["type"] == "fluid" for r in recipe["results"]):
        raise ValueError(f"{recipe['name']}: fluid ingredients/results not supported")
    if not 1 <= len(ings) <= 4:
        raise ValueError(f"{recipe['name']}: {len(ings)} ingredients; templates cover 1-4")
    tmpl = load_template(len(ings))
    info = analyze(tmpl)
    machine = machine or info["machine"]["name"]
    speed = rt.MACHINES_BY_NAME[machine]
    per_craft = rt.net_output(recipe, item)
    crafts = rate / per_craft
    time = recipe.get("energy_required", 0.5)
    n = max(1, -(-int(crafts * time / speed * 1e9) // 10**9))  # ceil with float guard
    capacity = n * speed / time * per_craft
    belt_name = belt
    scale = BELT_SCALE[belt_name]

    ents = []
    # cell 0 = the template itself, shifted down by (n-1) cells so stacked cells fit above
    shift = (n - 1) * CELL_ROWS
    for e in tmpl:
        e = copy.deepcopy(e)
        e["position"]["y"] += shift
        if e["name"].endswith("transport-belt"):
            e["name"] = belt_name
        if e["name"] in MACHINE_TYPES:
            e["name"] = machine
            if machine != "electric-furnace":
                e["recipe"] = recipe["name"]
        ents.append(e)
    pole_ids = [next(i for i, x in enumerate(ents) if x["name"].endswith("electric-pole"))]
    for k in range(1, n):
        off = shift - k * CELL_ROWS
        for x, d in info["belt_cols"].items():
            for r in range(CELL_ROWS):
                ents.append({"name": belt_name, "position": {"x": x, "y": off + r + 0.5}, "direction": d})
        for e in info["cell_entities"]:
            e = copy.deepcopy(e)
            e["position"]["y"] += off
            if e["name"] in MACHINE_TYPES:
                e["name"] = machine
                if machine != "electric-furnace":
                    e["recipe"] = recipe["name"]
            ents.append(e)
        pole = copy.deepcopy(info["pole"])
        pole["position"]["y"] += off
        pole_ids.append(len(ents))
        ents.append(pole)
    wires = [[a + 1, 5, b + 1, 5] for a, b in zip(pole_ids, pole_ids[1:])]  # copper, 1-based entity numbers

    H = info["height"] + shift
    W = info["width"]
    caps = INPUT_CAPACITY[len(ings)]
    inputs, notes = [], []
    for i, (ing, x) in enumerate(zip(ings, info["inputs"])):
        r = crafts * ing["amount"]
        inputs.append(Port("in", "belt", ing["name"], "both", int(x), H - 1, 0, r))
        if r > caps[i] * scale + 1e-9:
            notes.append(f"WARNING input {i + 1} {ing['name']} {r:.3g}/s exceeds port capacity {caps[i] * scale:g}/s")
    outputs = [Port("out", "belt", item, "left", int(info["output"]), H - 1, 8, rate)]
    if rate > OUTPUT_CAPACITY * scale + 1e-9:
        notes.append(f"WARNING output {rate:.3g}/s exceeds lane capacity {OUTPUT_CAPACITY * scale:g}/s")
    notes.insert(0, f"{n}x {machine} {recipe['name']} -> {capacity:.3g}/s capacity; template {len(ings)}_to_1, belt {belt_name}")
    return Module(name=f"{item} {rate:g}/s", width=W, height=H, entities=ents, inputs=inputs,
                  outputs=outputs, notes=notes, wires=wires)
