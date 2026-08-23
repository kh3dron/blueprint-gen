"""Generated cells for fluid machines: chemical plant, oil refinery, and the assembling machine on
crafting-with-fluid recipes (fluid and item ingredients in the same cell).

Layout of one column (columns are machine-relative, machines stacked every `pitch` rows, A = size//2 + 1
is the external column beside the machine):

  fluid ports    : the machine faces so that its input boxes are west and its output boxes east. Box k
                   of a side connects at its external tile (column +-A) and runs to a vertical main
                   further out. With no item belt on that side box 0 uses a plain pipe stub and its main
                   sits at A+1; every other box tunnels out with a pipe-to-ground pair. With b item belts
                   on the side every box tunnels past them and the first main sits at A+2+b. Mains are 2
                   columns apart so they never touch.
  item ports     : at most 2 per side. Belt column A+1 is reached by an inserter at A, column A+2 by a
                   long-handed inserter at A; input belts run north, output belts south. Inserters sit on
                   the rows of column A that no fluid box uses, so a side offers at most as many slots as
                   it has free rows. Item ingredients fill the west slots and item results the east ones
                   (inputs west, outputs east, as the fluid mains already are); a port that does not fit
                   its own side takes the far slot of the other one.
  power          : medium pole on a free row of column A (west first), else on a spare row added under
                   the machine (pitch = size + 1); poles wired in a chain, plus one on the bottom row
                   east of the machine, reachable by the bus pole chains.
  ports          : bottom row; pipe mains (kind "pipe", inputs flow N, outputs flow S), belts.

Fluid boxes are taken from data/base/prototypes/entity/entities.lua (direction north) and rotated.
A cell is marked no_mirror unless every fluid box it uses sits on the machine's centre row: a recipe
binds fluid ingredient k to box k, so a vertical mirror would land each fluid on its neighbour's box.
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
    "assembling-machine-2": {"size": 3, "speed": 0.75, "orient": W,
                             "inputs": [(0, -1, N)], "outputs": [(0, 1, S)]},
    "assembling-machine-3": {"size": 3, "speed": 1.25, "orient": W,
                             "inputs": [(0, -1, N)], "outputs": [(0, 1, S)]},
}
CATEGORY_MACHINE = {"chemistry": "chemical-plant", "oil-processing": "oil-refinery",
                    "crafting-with-fluid": "assembling-machine-2"}
BELT_IN_CAP = {"transport-belt": 15.0, "fast-transport-belt": 30.0, "express-transport-belt": 45.0,
               "turbo-transport-belt": 60.0}
SLOTS_PER_SIDE = 2      # belt at A+1 (inserter), belt at A+2 (long-handed inserter)


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


def machine_for(recipe, machine=None):
    if machine:
        return machine
    cats = recipe.get("categories") or []
    m = next((CATEGORY_MACHINE[c] for c in cats if c in CATEGORY_MACHINE), None)
    if m is None:
        raise ValueError(f"{recipe['name']}: categories {cats} have no fluid machine")
    return m


def layout(machine, n_fin, n_fout, n_iin, n_iout, what=None):
    """Geometry of one machine cell: columns relative to the machine's centre column, rows relative to
    its centre row. Raises ValueError when the cell cannot hold that many ports.

    fluid: [{io, index, side, row, main}]  (order: inputs then outputs, box order within each)
    slots: [{side, row, belt, inserter}]   (order: item ingredients then item results)

    Item ingredients take the west slots first and results the east ones, so the cell keeps the bus
    convention (inputs west, outputs east) that fluid mains already follow; within a side the nearer
    belt column is the westerly one. Ports that spill over take the far slots of the other side.
    """
    what = what or machine
    m = MACHINES[machine]
    size = m["size"]
    half = size // 2
    A = half + 1
    if n_fin > len(m["inputs"]):
        raise ValueError(f"{what}: {n_fin} fluid ingredients, {machine} has {len(m['inputs'])} input boxes")
    if n_fout > len(m["outputs"]):
        raise ValueError(f"{what}: {n_fout} fluid results, {machine} has {len(m['outputs'])} output boxes")
    ins_ext, outs_ext = boxes(machine)
    fluid = []
    for io, ext in (("in", ins_ext[:n_fin]), ("out", outs_ext[:n_fout])):
        for k, (x, y) in enumerate(ext):
            if abs(x) != A:
                raise ValueError(f"{machine}: fluid box {io} {k} connects at column {x}, expected +-{A}")
            fluid.append({"io": io, "index": k, "side": 1 if x > 0 else -1, "row": y})
    busy = {s: {f["row"] for f in fluid if f["side"] == s} for s in (1, -1)}
    free = {s: [r for r in range(-half, half + 1) if r not in busy[s]] for s in (1, -1)}
    cap = {s: min(SLOTS_PER_SIDE, len(free[s])) for s in (1, -1)}
    w_in = min(cap[-1], n_iin)
    e_in = n_iin - w_in
    e_out = min(max(0, cap[1] - e_in), n_iout)
    w_out = n_iout - e_out
    if e_in > cap[1] or w_in + w_out > cap[-1]:
        raise ValueError(f"{what}: {n_iin + n_iout} item ports, a {machine} cell with {n_fin + n_fout} "
                         f"fluid ports fits {cap[1] + cap[-1]}")
    order = ([(-1, k) for k in range(w_in)] + [(1, k) for k in range(e_in)]
             + [(1, e_in + k) for k in range(e_out)] + [(-1, w_in + k) for k in range(w_out)])
    used = {s: sum(1 for t, _ in order if t == s) for s in (1, -1)}
    # outer rows first, so a middle row is left for the pole
    taken = {s: sorted(sorted(free[s], key=lambda r: (-abs(r), r))[:used[s]]) for s in (1, -1)}
    slots = [{"side": s, "row": taken[s][k], "belt": s * (A + 1 + k),
              "inserter": "inserter" if k == 0 else "long-handed-inserter"} for s, k in order]
    for s in (1, -1):
        first = A + 1 if not used[s] else A + 2 + used[s]
        for k, f in enumerate([f for f in fluid if f["side"] == s]):
            f["main"] = s * (first + 2 * k)
    pitch, pole = size, None
    for s in (-1, 1):
        rest = [r for r in free[s] if r not in taken[s]]
        if rest:
            pole = (s * A, min(rest, key=lambda r: (abs(r), r)))
            break
    if pole is None:
        pitch, pole = size + 1, (-A, half + 1)
    cols = {-half, half, A, pole[0]}
    for f in fluid:
        cols.update((f["side"] * A, f["main"]))
    for sl in slots:
        cols.update((sl["side"] * A, sl["belt"]))
    return {"machine": machine, "size": size, "half": half, "A": A, "pitch": pitch, "pole": pole,
            "fluid": fluid, "slots": slots, "min_col": min(cols), "max_col": max(cols),
            "width": max(cols) - min(cols) + 1,
            "no_mirror": any(f["row"] != 0 for f in fluid)}


def plan(recipe, crafts, rt, belt="transport-belt", machine=None):
    """Sizing for a fluid recipe at `crafts` crafts/s. Mirrors templates.plan()."""
    machine = machine_for(recipe, machine)
    fin = [i for i in recipe["ingredients"] if i["type"] == "fluid"]
    iin = [i for i in recipe["ingredients"] if i["type"] == "item"]
    fout = [r for r in recipe["results"] if r["type"] == "fluid"]
    iout = [r for r in recipe["results"] if r["type"] == "item"]
    lay = layout(machine, len(fin), len(fout), len(iin), len(iout), what=recipe["name"])
    m = MACHINES[machine]
    time = recipe.get("energy_required", 0.5)
    n = max(1, -(-int(crafts * time / m["speed"] * 1e9) // 10**9))
    iout_amt = [rt.expected_amount(r) for r in iout]
    # columns: only item belts have a capacity (input belt: full belt; output: one lane)
    scale = BELT_IN_CAP[belt] / 15.0
    per_col = n
    for amt, cap in ([(i["amount"], 15.0 * scale) for i in iin] + [(a, 7.5 * scale) for a in iout_amt]):
        r = crafts * amt
        if r > 0:
            per_col = min(per_col, int(cap * n / r + 1e-9))
    per_col = max(1, per_col)
    primary = iout[0] if iout else fout[0]
    return {"kind": "fluid", "recipe": recipe, "machine": machine, "belt": belt, "crafts": crafts, "n": n,
            "fin": fin, "iin": iin, "fout": fout, "iout": iout, "iout_amt": iout_amt, "layout": lay,
            "c_min": -(-n // per_col), "width": lay["width"], "base_height": lay["pitch"] + 1,
            "item": primary["name"], "rate": crafts * (iout_amt[0] if iout else fout[0]["amount"])}


def build_from_plan(pl, columns=None):
    n = pl["n"]
    c = max(pl["c_min"], min(columns or 1, n))
    q, rem = divmod(n, c)
    counts = [q + 1 if i < rem else q for i in range(c)]
    return [_column(pl, cnt, ci, c) for ci, cnt in enumerate(counts)]


def _column(pl, cnt, ci, ctotal):
    lay = pl["layout"]
    A, half, pitch = lay["A"], lay["half"], lay["pitch"]
    belt, recipe = pl["belt"], pl["recipe"]
    off = -lay["min_col"]                    # machine-relative column -> module column
    H = cnt * pitch + 1
    ents, pole_ids = [], []
    fluids = pl["fin"] + pl["fout"]          # same order as lay["fluid"]
    items = pl["iin"] + pl["iout"]           # same order as lay["slots"]

    def ent(name, col, row, d=N, **kw):
        e = {"name": name, "position": {"x": col + off + 0.5, "y": row + 0.5}, "direction": d}
        e.update(kw)
        ents.append(e)
        return e

    for k in range(cnt):
        cy = k * pitch + half                # machine centre row
        ent(pl["machine"], 0, cy, MACHINES[pl["machine"]]["orient"], recipe=recipe["name"])
        for f in lay["fluid"]:
            s, y = f["side"], cy + f["row"]
            if abs(f["main"]) == A + 1:
                ent("pipe", s * A, y)                                  # main is next door
            else:
                ent("pipe-to-ground", s * A, y, E if s < 0 else W)     # opening toward the machine
                ent("pipe-to-ground", f["main"] - s, y, W if s < 0 else E)
        for i, sl in enumerate(lay["slots"]):
            into, east = i < len(pl["iin"]), sl["side"] > 0
            ent(sl["inserter"], sl["side"] * A, cy + sl["row"], (E if east else W) if into else (W if east else E))
        pole_ids.append(len(ents))
        ent("medium-electric-pole", lay["pole"][0], cy + lay["pole"][1])
    pole_ids.append(len(ents))
    ent("medium-electric-pole", A, H - 1)    # bottom-east pole: reachable by the bus pole chains
    wires = [[a + 1, 5, b + 1, 5] for a, b in zip(pole_ids, pole_ids[1:])]
    for f in lay["fluid"]:                   # mains and belts run from the top to the bottom row
        for y in range(H):
            ent("pipe", f["main"], y)
    for i, sl in enumerate(lay["slots"]):
        for y in range(H):
            ent(belt, sl["belt"], y, N if i < len(pl["iin"]) else S)

    crafts = pl["crafts"] * cnt / pl["n"]
    inputs, outputs = [], []
    for f, spec in zip(lay["fluid"], fluids):
        x = f["main"] + off
        if f["io"] == "in":
            inputs.append(Port("in", "pipe", spec["name"], "both", x, H - 1, N, crafts * spec["amount"]))
        else:
            outputs.append(Port("out", "pipe", spec["name"], "both", x, H - 1, S, crafts * spec["amount"]))
    for i, sl in enumerate(lay["slots"]):
        it, x = items[i], sl["belt"] + off
        if i < len(pl["iin"]):
            inputs.append(Port("in", "belt", it["name"], "both", x, H - 1, N, crafts * it["amount"]))
        else:
            lane = "left" if sl["side"] > 0 else "right"   # inserters drop on the belt's far lane
            outputs.append(Port("out", "belt", it["name"], lane, x, H - 1, S,
                               crafts * pl["iout_amt"][i - len(pl["iin"])]))
    inputs.sort(key=lambda p: p.x)
    outputs.sort(key=lambda p: p.x)
    tag = f" [{ci + 1}/{ctotal}]" if ctotal > 1 else ""
    notes = [f"{cnt}x {pl['machine']} {recipe['name']} ({crafts:.3g} crafts/s); fluid cell, belt {belt}"]
    if lay["no_mirror"]:
        notes.append("NO-MIRROR fluid boxes off the machine centre row; a vertical flip would swap them")
    return Module(name=f"{pl['item']} {pl['rate']:.3g}/s{tag}", width=lay["width"], height=H, entities=ents,
                  inputs=inputs, outputs=outputs, notes=notes, wires=wires, no_mirror=lay["no_mirror"])
