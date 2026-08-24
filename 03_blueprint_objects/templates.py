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


CGAP = 2             # columns between stacks inside a module (room for a lane to surface between a push and the next pull)


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


def plan(item, rate, recipe, rt, machine=None, belt="transport-belt", prefer=None):
    """Sizing for `item` at `rate` without building: machine count n, minimum columns c_min (belt
    capacity), template info. Column count is finalised by build_columns(columns=...).

    `prefer` names an ingredient to put on the leftmost input port instead of its recipe position: the
    only port a direct link from the module next door can always reach. Ingredients are free to sit on
    any input belt (each has its own inserter into the same machine), so this only trades port
    capacities (N=3 is [15, 7.5, 7.5]); it is dropped if it would cost a column."""
    ings = list(recipe["ingredients"])
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
    caps = [c * scale for c in INPUT_CAPACITY[len(ings)]] + [OUTPUT_CAPACITY * scale]

    def columns(order):
        rates = [crafts * i["amount"] for i in order]
        per_col = n
        for r, cap in zip(rates + [rate], caps):
            if r > 0:
                per_col = min(per_col, int(cap * n / r + 1e-9))
        return max(1, per_col), rates

    per_col, ing_rates = columns(ings)
    if prefer and any(i["name"] == prefer for i in ings) and ings[0]["name"] != prefer:
        moved = sorted(ings, key=lambda i: i["name"] != prefer)      # prefer first, rest in recipe order
        pc, rates = columns(moved)
        if pc >= per_col:                                            # never trade a column for it
            ings, per_col, ing_rates = moved, pc, rates
    return {"item": item, "rate": rate, "recipe": recipe, "ings": ings, "machine": machine, "belt": belt,
            "tmpl": tmpl, "info": info, "n": n, "capacity": capacity, "ing_rates": ing_rates, "caps": caps,
            "c_min": -(-n // per_col), "width": info["width"], "base_height": info["height"]}


def build_columns(item, rate, recipe, rt, machine=None, belt="transport-belt", columns=None):
    """Modules for `item` at `rate`, one per column. Machines are split into at least c_min columns
    (so no port exceeds what its belt can carry: INPUT_CAPACITY per template port, OUTPUT_CAPACITY for
    the single-lane output, scaled by belt tier); `columns` may ask for more to limit height.
    Each column is a complete Module (own ports and poles)."""
    pl = plan(item, rate, recipe, rt, machine=machine, belt=belt)
    return build_from_plan(pl, columns)


def build_from_plan(pl, columns=None):
    n, ings = pl["n"], pl.get("ings") or pl["recipe"]["ingredients"]
    c = max(pl["c_min"], min(columns or 1, n))
    q, rem = divmod(n, c)
    counts = [q + 1 if i < rem else q for i in range(c)]
    info, caps, ing_rates = pl["info"], pl["caps"], pl["ing_rates"]
    item, rate, machine, recipe, belt = pl["item"], pl["rate"], pl["machine"], pl["recipe"], pl["belt"]
    mods = []
    for ci, cnt in enumerate(counts):
        ents, pole_ids, h = _column(pl["tmpl"], info, cnt, machine, recipe, belt)
        wires = [[a + 1, 5, b + 1, 5] for a, b in zip(pole_ids, pole_ids[1:])]
        share = cnt / n
        inputs = [Port("in", "belt", ing["name"], "both", int(x), h - 1, 0, r * share)
                  for ing, x, r in zip(ings, info["inputs"], ing_rates)]
        outputs = [Port("out", "belt", item, "left", int(info["output"]), h - 1, 8, rate * share)]
        notes = []
        for p in inputs + outputs:
            cap = caps[-1] if p.io == "out" else caps[[i["name"] for i in ings].index(p.item)]
            if p.rate > cap + 1e-9:
                notes.append(f"WARNING port {p.item} {p.rate:.3g}/s exceeds its belt capacity {cap:g}/s (one machine already exceeds it)")
        tag = f" [{ci + 1}/{c}]" if c > 1 else ""
        notes.append(f"{cnt}x {machine} {recipe['name']}; column {ci + 1} of {c} for {item} {rate:g}/s "
                     f"({n} machines -> {pl['capacity']:.3g}/s); template {len(ings)}_to_1, belt {belt}; "
                     f"port caps in {caps[:-1]} out {caps[-1]:g} /s")
        mods.append(Module(name=f"{item} {rate:g}/s{tag}", width=info["width"], height=h, entities=ents,
                           inputs=inputs, outputs=outputs, notes=notes, wires=wires))
    return mods


def choose_cells(plans, fixed_heights=(), gap=3, bus_rows=0, cells=None, spacing=3):
    """Target machines per column for a set of plans: the value minimising the bounding-box area
    estimate (sum of column extents incl. bus columns and gaps) x (tallest column + routing + bus rows).
    `cells` forces the target."""
    if cells:
        return cells
    best = None
    max_n = max([pl["n"] for pl in plans] + [1])
    for T in range(1, max_n + 1):
        width = height = 0
        for pl in plans:
            c = max(pl["c_min"], -(-pl["n"] // T))
            per = -(-pl["n"] // c)
            n_ports = len(pl["recipe"]["ingredients"])
            extent = max(pl["width"], spacing * (n_ports - 1) + spacing + 2)
            width += c * (extent + gap)
            height = max(height, pl["base_height"] + (per - 1) * CELL_ROWS)
        height = max([height] + list(fixed_heights))
        area = width * (height + bus_rows)
        if best is None or area < best[0] or (area == best[0] and T > best[1]):
            best = (area, T)
    return best[1]
def build(item, rate, recipe, rt, machine=None, belt="transport-belt"):
    """Single Module: the columns of build_columns() side by side (stride = width + CGAP, bottom-aligned,
    bottom poles wired). Ports: per column, inputs then outputs, left to right."""
    cols = build_columns(item, rate, recipe, rt, machine=machine, belt=belt)
    return combine(cols, f"{item} {rate:g}/s")


def combine(cols, name):
    """Side-by-side combination of column modules (stride = width + CGAP, bottom-aligned, bottom poles wired)."""
    if len(cols) == 1:
        return cols[0]
    stride = cols[0].width + CGAP
    H = max(m.height for m in cols)
    ents, wires, inputs, outputs, bottom_poles = [], [], [], [], []
    for ci, m in enumerate(cols):
        xoff, yoff, base = ci * stride, H - m.height, len(ents)
        for e in m.entities:
            e = copy.deepcopy(e)
            e["position"] = {"x": e["position"]["x"] + xoff, "y": e["position"]["y"] + yoff}
            ents.append(e)
        wires += [[w[0] + base, w[1], w[2] + base, w[3]] for w in m.wires]
        poles = [i for i, e in enumerate(m.entities) if e["name"].endswith("electric-pole")]
        bottom_poles.append(base + max(poles, key=lambda i: m.entities[i]["position"]["y"]))
        for p in m.inputs:
            inputs.append(Port(p.io, p.kind, p.item, p.lane, p.x + xoff, H - 1, p.direction, p.rate))
        for p in m.outputs:
            outputs.append(Port(p.io, p.kind, p.item, p.lane, p.x + xoff, H - 1, p.direction, p.rate))
    for a, b in zip(bottom_poles, bottom_poles[1:]):
        if ents[b]["position"]["x"] - ents[a]["position"]["x"] <= 9.0:
            wires.append([a + 1, 5, b + 1, 5])
    W = (len(cols) - 1) * stride + cols[0].width
    notes = [n for m in cols for n in m.notes]
    return Module(name=name, width=W, height=H, entities=ents, inputs=inputs,
                  outputs=outputs, notes=notes, wires=wires,
                  no_mirror=any(m.no_mirror for m in cols))
