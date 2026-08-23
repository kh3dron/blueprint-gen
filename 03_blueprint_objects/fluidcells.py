"""Generated cells for fluid machines (chemical plant, oil refinery), built from prototype fluid boxes.

Layout of one column (machine-relative x, machines stacked every `size` rows):

  fluid inputs   : west side. Fluid ingredient i enters at its box's external tile; i = 0 uses a plain
                   pipe stub to a vertical main one column further west, i >= 1 tunnels out with a
                   pipe-to-ground pair so its main sits 2 columns further out again. Mains never touch.
  fluid outputs  : east side, same scheme mirrored (tunnels skip the item belts if present).
  items          : east side. <= 1 item ingredient: inserter at row 0 picking from an input belt
                   (northbound) at base+1; <= 1 item result: long-handed inserter on an unused output
                   row dropping on an output belt (southbound) at base+2.
  power          : medium pole on the west side at row 0 of every machine, poles wired in a chain.
  ports          : bottom row; pipe mains (kind "pipe", inputs flow N, outputs flow S), belts.

Fluid boxes are taken from data/base/prototypes/entity/entities.lua (direction north) and rotated.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from module import Module, Port  # noqa: E402

N, E, S, W = 0, 4, 8, 12
DIRV = {N: (0, -1), E: (1, 0), S: (0, 1), W: (-1, 0)}
# (x, y, exit direction) in the prototype's north orientation
MACHINES = {
    "chemical-plant": {"size": 3, "speed": 1.0, "orient": W,
                       "inputs": [(-1, -1, N), (1, -1, N)], "outputs": [(-1, 1, S), (1, 1, S)]},
    "oil-refinery": {"size": 5, "speed": 1.0, "orient": E,
                     "inputs": [(-1, 2, S), (1, 2, S)], "outputs": [(-2, -2, N), (0, -2, N), (2, -2, N)]},
}
CATEGORY_MACHINE = {"chemistry": "chemical-plant", "oil-processing": "oil-refinery"}
BELT_IN_CAP = {"transport-belt": 15.0, "fast-transport-belt": 30.0, "express-transport-belt": 45.0,
               "turbo-transport-belt": 60.0}


def rotate(x, y, d, orient):
    """Rotate a north-orientation fluid box (x, y, exit dir) to `orient`."""
    for _ in range(orient // 4):
        x, y, d = -y, x, (d + 4) % 16
    return x, y, d


def boxes(machine):
    m = MACHINES[machine]
    ins = [rotate(*b, m["orient"]) for b in m["inputs"]]
    outs = [rotate(*b, m["orient"]) for b in m["outputs"]]
    ext = lambda b: (b[0] + DIRV[b[2]][0], b[1] + DIRV[b[2]][1])   # noqa: E731  tile outside the machine
    return [ext(b) for b in ins], [ext(b) for b in outs]


def plan(recipe, crafts, rt, belt="transport-belt"):
    """Sizing for a fluid recipe at `crafts` crafts/s. Mirrors templates.plan()."""
    cats = recipe.get("categories") or []
    machine = next((CATEGORY_MACHINE[c] for c in cats if c in CATEGORY_MACHINE), None)
    if machine is None:
        raise ValueError(f"{recipe['name']}: categories {cats} have no fluid machine")
    fin = [i for i in recipe["ingredients"] if i["type"] == "fluid"]
    iin = [i for i in recipe["ingredients"] if i["type"] == "item"]
    fout = [r for r in recipe["results"] if r["type"] == "fluid"]
    iout = [r for r in recipe["results"] if r["type"] == "item"]
    m = MACHINES[machine]
    if len(fin) > len(m["inputs"]) or len(fout) > len(m["outputs"]):
        raise ValueError(f"{recipe['name']}: more fluid ports than {machine} has")
    if len(iin) > 1 or len(iout) > 1:
        raise ValueError(f"{recipe['name']}: fluid cells support at most one item input and one item output")
    time = recipe.get("energy_required", 0.5)
    n = max(1, -(-int(crafts * time / m["speed"] * 1e9) // 10**9))
    # columns: only item belts have a capacity (input belt: full belt; output: one lane)
    scale = BELT_IN_CAP[belt] / 15.0
    per_col = n
    for lst, cap in ((iin, 15.0 * scale), (iout, 7.5 * scale)):
        for x in lst:
            r = crafts * rt.expected_amount(x) if x in iout else crafts * x["amount"]
            if r > 0:
                per_col = min(per_col, int(cap * n / r + 1e-9))
    per_col = max(1, per_col)
    return {"kind": "fluid", "recipe": recipe, "machine": machine, "belt": belt, "crafts": crafts, "n": n,
            "fin": fin, "iin": iin, "fout": fout, "iout": iout, "c_min": -(-n // per_col),
            "width": None, "base_height": m["size"] + 1, "item": (iout[0]["name"] if iout else fout[0]["name"]),
            "rate": crafts * (rt.expected_amount(iout[0]) if iout else fout[0]["amount"])}


def build_from_plan(pl, columns=None):
    n = pl["n"]
    c = max(pl["c_min"], min(columns or 1, n))
    q, rem = divmod(n, c)
    counts = [q + 1 if i < rem else q for i in range(c)]
    return [_column(pl, cnt, ci, c) for ci, cnt in enumerate(counts)]


def _column(pl, cnt, ci, ctotal):
    m = MACHINES[pl["machine"]]
    size, pitch = m["size"], m["size"]
    half = size // 2
    belt = pl["belt"]
    recipe = pl["recipe"]
    ins_ext, outs_ext = boxes(pl["machine"])
    has_belts = bool(pl["iin"] or pl["iout"])
    base_w = -(half + 1)                       # west external column
    base_e = half + 1                          # east external column
    ents, wires = [], []
    mains = {}                                 # item name -> (column, io)
    pole_ids = []
    share = cnt / n if (n := pl["n"]) else 1.0

    def ent(name, x, y, d=N, **kw):
        e = {"name": name, "position": {"x": x + 0.5, "y": y + 0.5}, "direction": d}
        e.update(kw)
        ents.append(e)
        return e

    rows_top = 0
    for k in range(cnt):
        cy = rows_top + k * pitch + half         # machine center tile row
        ent(pl["machine"], half + 0, cy, m["orient"], recipe=recipe["name"])
        # fix position: machine center is at (0.5 + half... ) -> use tile coords relative to column 0 = machine left edge - |base_w|
        ents[-1]["position"] = {"x": 0.0, "y": cy + 0.5}
        # fluid inputs
        for i, ing in enumerate(pl["fin"]):
            ex, ey = ins_ext[i]
            y = cy + ey
            if i == 0:
                ent("pipe", ex, y)
                mains[ing["name"]] = (ex - 1, "in")
            else:
                ent("pipe-to-ground", ex, y, E)                    # opening toward the machine, tunnel west
                ent("pipe-to-ground", ex - 2 * i, y, W)
                mains[ing["name"]] = (ex - 2 * i - 1, "in")
        # fluid outputs
        for j, res in enumerate(pl["fout"]):
            ex, ey = outs_ext[j]
            y = cy + ey
            if not has_belts and j == 0:
                ent("pipe", ex, y)
                mains[res["name"]] = (ex + 1, "out")
            else:
                exit_x = ex + (3 + 2 * j if has_belts else 2 * j)
                ent("pipe-to-ground", ex, y, W)                    # opening toward the machine, tunnel east
                ent("pipe-to-ground", exit_x, y, E)
                mains[res["name"]] = (exit_x + 1, "out")
        # items
        used_rows = {outs_ext[j][1] for j in range(len(pl["fout"]))}
        if pl["iin"]:
            ent("inserter", base_e, cy, E)                         # picks from the input belt to the east
        if pl["iout"]:
            r_out = next(r for r in (-1, 1, 0) if r not in used_rows and (r != 0 or not pl["iin"]))
            ent("long-handed-inserter", base_e, cy + r_out, W)     # picks from the machine, drops 2 east
        # pole
        pid = len(ents)
        ent("medium-electric-pole", base_w, cy)
        pole_ids.append(pid)
    H = cnt * pitch + 1
    pid = len(ents)
    ent("medium-electric-pole", base_e, H - 1)        # bottom-east pole: reachable by the bus pole chains
    pole_ids.append(pid)
    wires = [[a + 1, 5, b + 1, 5] for a, b in zip(pole_ids, pole_ids[1:])]
    # mains and belts run from the top to the bottom row
    for name, (x, io) in mains.items():
        for y in range(0, H):
            ent("pipe", x, y)
    if pl["iin"]:
        for y in range(0, H):
            ent(belt, base_e + 1, y, N)
    if pl["iout"]:
        for y in range(0, H):
            ent(belt, base_e + 2, y, S)

    # shift to module-local coordinates (min x -> 0)
    minx = min(int(e["position"]["x"] - 0.5) if e["name"] != pl["machine"] else -half for e in ents)
    for e in ents:
        e["position"]["x"] -= minx
    width = max(int(e["position"]["x"] + 0.5) if e["name"] != pl["machine"] else int(e["position"]["x"]) + half + 1
                for e in ents)
    for e in ents:                              # machine center to proper half-tile center for odd sizes
        if e["name"] == pl["machine"]:
            e["position"]["x"] = e["position"]["x"] + 0.5
    crafts = pl["crafts"] * share
    inputs, outputs = [], []
    for ing in pl["fin"]:
        x, _ = mains[ing["name"]]
        inputs.append(Port("in", "pipe", ing["name"], "both", x - minx, H - 1, N, crafts * ing["amount"]))
    if pl["iin"]:
        inputs.append(Port("in", "belt", pl["iin"][0]["name"], "both", base_e + 1 - minx, H - 1, N, crafts * pl["iin"][0]["amount"]))
    for res in pl["fout"]:
        x, _ = mains[res["name"]]
        outputs.append(Port("out", "pipe", res["name"], "both", x - minx, H - 1, S, crafts * res["amount"]))
    if pl["iout"]:
        r = pl["iout"][0]
        amt = r["amount"] if "amount" in r else (r["amount_min"] + r["amount_max"]) / 2
        outputs.append(Port("out", "belt", r["name"], "left", base_e + 2 - minx, H - 1, S, crafts * amt * r.get("probability", 1.0)))
    inputs.sort(key=lambda p: p.x)
    outputs.sort(key=lambda p: p.x)
    tag = f" [{ci + 1}/{ctotal}]" if ctotal > 1 else ""
    notes = [f"{cnt}x {pl['machine']} {recipe['name']} ({crafts:.3g} crafts/s); fluid cell, belt {belt}"]
    return Module(name=f"{pl['item']} {pl['rate']:.3g}/s{tag}", width=width, height=H, entities=ents,
                  inputs=inputs, outputs=outputs, notes=notes, wires=wires)
