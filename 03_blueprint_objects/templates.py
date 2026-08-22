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


CGAP = 1             # columns between stacks inside a module


def _column(tmpl, info, n, machine, recipe, belt_name):
    """One stack of n cells. Returns (entities, pole entity indices bottom-up, height)."""
    ents = []
    shift = (n - 1) * CELL_ROWS   # cell 0 = the template itself, pushed down so stacked cells fit above
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
    return ents, pole_ids, info["height"] + shift


def build(item, rate, recipe, rt, machine=None, belt="transport-belt"):
    """Module for `item` at `rate`. Machines are split into side-by-side columns only when a port would
    exceed what its belt can carry (INPUT_CAPACITY per template port, OUTPUT_CAPACITY for the
    single-lane output, scaled by belt tier). Ports: per column, inputs then outputs, left to right."""
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
    scale = BELT_SCALE[belt]
    ing_rates = [crafts * i["amount"] for i in ings]
    caps = [c * scale for c in INPUT_CAPACITY[len(ings)]] + [OUTPUT_CAPACITY * scale]
    # machines per column: the most that keeps every port within its belt capacity
    per_col = n
    for r, cap in zip(ing_rates + [rate], caps):
        if r > 0:
            per_col = min(per_col, int(cap * n / r + 1e-9))
    per_col = max(1, per_col)
    c = -(-n // per_col)
    q, rem = divmod(n, c)
    counts = [q + 1 if i < rem else q for i in range(c)]

    stride = info["width"] + CGAP
    cols = [_column(tmpl, info, cnt, machine, recipe, belt) for cnt in counts]
    H = max(h for _, _, h in cols)
    ents, wires, inputs, outputs = [], [], [], []
    bottom_poles = []
    for ci, ((cents, pole_ids, h), cnt) in enumerate(zip(cols, counts)):
        xoff, yoff, base = ci * stride, H - h, len(ents)
        for e in cents:
            e["position"] = {"x": e["position"]["x"] + xoff, "y": e["position"]["y"] + yoff}
            ents.append(e)
        wires += [[base + a + 1, 5, base + b + 1, 5] for a, b in zip(pole_ids, pole_ids[1:])]
        bottom_poles.append(base + pole_ids[0])
        share = cnt / n
        for ing, x, r in zip(ings, info["inputs"], ing_rates):
            inputs.append(Port("in", "belt", ing["name"], "both", int(x) + xoff, H - 1, 0, r * share))
        outputs.append(Port("out", "belt", item, "left", int(info["output"]) + xoff, H - 1, 8, rate * share))
    for a, b in zip(bottom_poles, bottom_poles[1:]):
        dx = ents[b]["position"]["x"] - ents[a]["position"]["x"]
        if dx <= 9.0:
            wires.append([a + 1, 5, b + 1, 5])
    W = (c - 1) * stride + info["width"]
    notes = []
    for p in inputs + outputs:
        cap = caps[-1] if p.io == "out" else caps[[i["name"] for i in ings].index(p.item)]
        if p.rate > cap + 1e-9:
            notes.append(f"WARNING port {p.item} {p.rate:.3g}/s exceeds its belt capacity {cap:g}/s (one machine already exceeds it)")
    notes += [f"{n}x {machine} {recipe['name']} -> {capacity:.3g}/s capacity; template {len(ings)}_to_1, belt {belt}, "
             f"{c} column(s) {counts}; port caps in {caps[:-1]} out {caps[-1]:g} /s"]
    return Module(name=f"{item} {rate:g}/s", width=W, height=H, entities=ents, inputs=inputs,
                  outputs=outputs, notes=notes, wires=wires)
