"""Bus: eastbound belt lanes under a row of modules, with pull/push/merge and lane crossing.

Geometry (composite-local tiles, y grows south):

  columns 0..E-1        : external-input risers (lane j enters at column j, northbound)
  columns E+GAP ..      : modules, bottom-aligned on row `by`, GAP columns apart
  rows by+1 .. by+R     : routing band (jogs between a port column and its bus column)
  rows B0 .. B0+3L-1    : bus; lane j uses rows s_a(j)=B0+3j, s_b(j)=B0+3j+1, belt(j)=B0+3j+2
  columns > x_max       : export drops (lane j drops at d_j, deeper lanes further west), southbound

pull  : splitter on belt(j) at column bc-1; branch exits east into (bc, s_b(j)) and turns north.
        The last consumer of a lane takes the whole lane instead: belt(j) itself turns north.
push  : chain south from the port.
crossing: a vertical chain tunnels (underground in/out around the belt row) only where the crossed
        lane actually has a belt at that column; otherwise it is a plain belt. At the target: belt south into belt(j): curve if the lane starts here,
        sideload (merge) if it already exists.
"""
import copy
import os
import sys
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from module import Module, Port  # noqa: E402

GAP = 2          # columns between modules
R = 4            # routing band rows
N, E, S, W = 0, 4, 8, 12
MACHINE_NAMES = {"assembling-machine-1", "assembling-machine-2", "assembling-machine-3", "electric-furnace"}
UNDERGROUND = {"transport-belt": "underground-belt", "fast-transport-belt": "fast-underground-belt",
               "express-transport-belt": "express-underground-belt", "turbo-transport-belt": "turbo-underground-belt"}
SPLITTER = {"transport-belt": "splitter", "fast-transport-belt": "fast-splitter",
            "express-transport-belt": "express-splitter", "turbo-transport-belt": "turbo-splitter"}
POLE_REACH = {"small-electric-pole": 7.5, "medium-electric-pole": 9.0, "big-electric-pole": 30.0}
LANE_CAPACITY = {"transport-belt": 15.0, "fast-transport-belt": 30.0, "express-transport-belt": 45.0,
                 "turbo-transport-belt": 60.0}


class Lane:
    def __init__(self, index, item, external):
        self.index = index
        self.item = item
        self.external = external
        self.start = None      # column of the first belt tile
        self.end = None        # column of the last belt tile (inclusive)
        self.rate = 0.0        # items/s carried
        self.pushes = []       # columns
        self.pulls = []        # columns


class Grid:
    """Tile occupancy + entity list for the composite."""

    def __init__(self, belt):
        self.ents = []
        self.occ = {}
        self.belt = belt

    def place(self, name, x, y, direction=N, footprint=((0, 0),), **kw):
        for dx, dy in footprint:
            key = (x + dx, y + dy)
            if key in self.occ:
                raise ValueError(f"tile {key} already holds {self.occ[key]}, cannot place {name}")
            self.occ[key] = name
        e = {"name": name, "position": {"x": x + 0.5, "y": y + 0.5}, "direction": direction}
        e.update(kw)
        self.ents.append(e)
        return e

    def belt_tile(self, x, y, d):
        return self.place(self.belt, x, y, d)

    def ug(self, x, y, d, kind):
        return self.place(UNDERGROUND[self.belt], x, y, d, type=kind)

    def vertical(self, x, rows, d, blocked):
        """Belt chain down `rows` (in travel order) at column x, travelling d. Rows in `blocked` hold a
        lane belt and are tunnelled under: underground in on the tile before, out on the tile after."""
        for i, y in enumerate(rows):
            if y in blocked:
                continue
            nxt = rows[i + 1] if i + 1 < len(rows) else None
            prv = rows[i - 1] if i > 0 else None
            if nxt in blocked:
                self.ug(x, y, d, "input")
            elif prv in blocked:
                self.ug(x, y, d, "output")
            else:
                self.belt_tile(x, y, d)

    def splitter_east(self, x, y_top):
        """Splitter facing east occupying (x, y_top) and (x, y_top+1); center at (x+0.5, y_top+1)."""
        for dy in (0, 1):
            key = (x, y_top + dy)
            if key in self.occ:
                raise ValueError(f"tile {key} already holds {self.occ[key]}, cannot place splitter")
            self.occ[key] = SPLITTER[self.belt]
        e = {"name": SPLITTER[self.belt], "position": {"x": x + 0.5, "y": y_top + 1}, "direction": E}
        self.ents.append(e)
        return e


class Bus:
    def __init__(self, belt="transport-belt"):
        self.belt = belt
        self.lanes = OrderedDict()   # item -> Lane

    def lane(self, item, external=False):
        if item not in self.lanes:
            self.lanes[item] = Lane(len(self.lanes), item, external)
        return self.lanes[item]

    @property
    def count(self):
        return len(self.lanes)


def compose(name, modules, belt="transport-belt", exports=None):
    """Stitch modules (list of Module, producers before consumers) over a bus. Returns a Module."""
    exports = set(exports or [])
    produced = {p.item for m in modules for p in m.outputs}
    consumed = {p.item for m in modules for p in m.inputs}
    bus = Bus(belt)
    # lanes: external inputs first (order of first use), then produced items (order of production)
    for m in modules:
        for p in m.inputs:
            if p.item not in produced:
                bus.lane(p.item, external=True)
    for m in modules:
        for p in m.outputs:
            bus.lane(p.item, external=False)
    L = bus.count
    Ecount = sum(1 for ln in bus.lanes.values() if ln.external)
    exported = [ln for ln in bus.lanes.values()
                if not ln.external and (ln.item not in consumed or ln.item in exports)]

    by = max(m.height for m in modules) - 1
    B0 = by + R + 1
    s_a = lambda j: B0 + 3 * j            # noqa: E731
    s_b = lambda j: B0 + 3 * j + 1        # noqa: E731
    belt_row = lambda j: B0 + 3 * j + 2   # noqa: E731
    H = B0 + 3 * L
    grid = Grid(belt)
    wires = []

    # ---- place modules ---------------------------------------------------------------
    x = Ecount + GAP
    placements = []
    for m in modules:
        x0, y0 = x, by - m.height + 1
        base = len(grid.ents)
        for e in m.entities:
            e = copy.deepcopy(e)
            e["position"] = {"x": e["position"]["x"] + x0, "y": e["position"]["y"] + y0}
            for tx, ty in entity_tiles(e):
                if (tx, ty) in grid.occ:
                    raise ValueError(f"module {m.name} overlaps at {(tx, ty)}")
                grid.occ[(tx, ty)] = e["name"]
            grid.ents.append(e)
        for w in m.wires:
            wires.append([w[0] + base, w[1], w[2] + base, w[3]])
        placements.append((m, x0, y0))
        x += m.width + GAP
    x_max = x - GAP - 1
    # a medium pole in each inter-module gap (bottom module row), wired to the nearest pole of each neighbour
    def nearest_pole(m, x0):
        best = None
        for i, e in enumerate(grid.ents):
            if e["name"].endswith("electric-pole") and x0 <= e["position"]["x"] < x0 + m.width:
                d = ((e["position"]["x"] - gx - 0.5) ** 2 + (e["position"]["y"] - by - 0.5) ** 2) ** 0.5
                if best is None or d < best[0]:
                    best = (d, i)
        return best
    for (ma, xa, ya), (mb, xb, yb) in zip(placements, placements[1:]):
        gx = xa + ma.width
        gid = len(grid.ents)
        grid.place("medium-electric-pole", gx, by)
        for m, x0 in ((ma, xa), (mb, xb)):
            best = nearest_pole(m, x0)
            if best and best[0] <= POLE_REACH["medium-electric-pole"]:
                wires.append([gid + 1, 5, best[1] + 1, 5])
            elif best:
                print(f"WARNING gap pole at {gx} cannot reach {m.name} pole ({best[0]:.1f} tiles)", file=sys.stderr)

    # ---- lane starts / ends ----------------------------------------------------------
    for ln in bus.lanes.values():
        if ln.external:
            ln.start = ln.index
    for m, x0, y0 in placements:
        for p in m.outputs:
            ln = bus.lane(p.item)
            col = x0 + p.x
            ln.pushes.append(col)
            ln.rate += p.rate
            if ln.start is None or col < ln.start:
                ln.start = col
        for k, p in enumerate(m.inputs):
            ln = bus.lane(p.item)
            bc = x0 + 2 * k
            ln.pulls.append(bc)
            if ln.external:
                ln.rate += p.rate
    for ln in bus.lanes.values():
        last_pull = max(ln.pulls) if ln.pulls else ln.start
        last_merge = max((c + 2 for c in ln.pushes if c > ln.start), default=ln.start)
        ln.end = max(ln.start, last_pull, last_merge)
    drops = {}
    for ln in exported:
        d = x_max + 3 + (L - 1 - ln.index)
        drops[ln.item] = d
        ln.end = d
    for ln in bus.lanes.values():
        if ln.start is None:
            raise ValueError(f"lane {ln.item} has no source")
        if ln.start > ln.end:
            ln.end = ln.start
    for ln in bus.lanes.values():
        if ln.rate > LANE_CAPACITY[belt] + 1e-9:
            print(f"WARNING lane {ln.index} {ln.item} {ln.rate:.3g}/s exceeds {belt} capacity {LANE_CAPACITY[belt]:g}/s",
                  file=sys.stderr)

    # ---- pulls (splitters sit on the lane, so place them before the lane belts) -----
    for m, x0, y0 in placements:
        for k, p in enumerate(m.inputs):
            ln = bus.lane(p.item)
            j = ln.index
            bc = x0 + 2 * k
            px = x0 + p.x
            if bc - 1 <= ln.start:
                raise ValueError(f"{m.name}: input {p.item} at column {px} is west of lane {j} start {ln.start}; "
                                 f"order producers before consumers")
            r = B0 - 1 - k
            blocked = {belt_row(o.index) for o in bus.lanes.values() if o.index < j and o.start <= bc <= o.end}
            if bc == ln.end:
                # last consumer: the lane itself turns north, no splitter
                grid.belt_tile(bc, belt_row(j), N)
                rows = list(range(s_b(j), r, -1))
            else:
                grid.splitter_east(bc - 1, s_b(j))
                grid.belt_tile(bc, belt_row(j), E)          # lane continues after the splitter
                grid.belt_tile(bc, s_b(j), N)               # branch: curve E->N
                rows = list(range(s_a(j), r, -1))
            grid.vertical(bc, rows, N, blocked)
            # routing band: row r turns toward px, then up to by+1
            if px == bc:
                grid.belt_tile(bc, r, N)
            else:
                step = 1 if px > bc else -1
                grid.belt_tile(bc, r, E if step > 0 else W)
                for xx in range(bc + step, px, step):
                    grid.belt_tile(xx, r, E if step > 0 else W)
                grid.belt_tile(px, r, N)
            for yy in range(r - 1, by, -1):
                grid.belt_tile(px, yy, N)

    # ---- pushes ----------------------------------------------------------------------
    for m, x0, y0 in placements:
        for p in m.outputs:
            ln = bus.lane(p.item)
            j = ln.index
            col = x0 + p.x
            blocked = {belt_row(o.index) for o in bus.lanes.values() if o.index < j and o.start <= col <= o.end}
            grid.vertical(col, list(range(by + 1, s_b(j))), S, blocked)
            if ln.start == col:
                grid.belt_tile(col, s_b(j), S)   # new lane: S->E curve at belt(j)
            else:
                # merge: curve east into the upper input of a splitter on the lane; the upper output
                # tile (col+2, s_b) stays empty so the whole flow leaves on the lane
                grid.belt_tile(col, s_b(j), E)
                grid.splitter_east(col + 1, s_b(j))

    # ---- lane belts ------------------------------------------------------------------
    for ln in bus.lanes.values():
        for xx in range(ln.start, ln.end + 1):
            if (xx, belt_row(ln.index)) not in grid.occ:
                grid.belt_tile(xx, belt_row(ln.index), E)

    # ---- external input risers -------------------------------------------------------
    inputs = []
    for ln in bus.lanes.values():
        if not ln.external:
            continue
        j = ln.index
        col = ln.index
        for yy in range(H - 1, belt_row(j), -1):
            grid.belt_tile(col, yy, N)
        # belt(j) at col was placed eastbound by the lane loop; it is the N->E curve
        inputs.append(Port("in", "belt", ln.item, "both", col, H - 1, N, ln.rate))

    # ---- export drops ----------------------------------------------------------------
    outputs = []
    for ln in exported:
        d = drops[ln.item]
        # lane belt at d was placed eastbound; replace with the E->S curve
        grid.ents = [e for e in grid.ents if not (e["position"] == {"x": d + 0.5, "y": belt_row(ln.index) + 0.5})]
        grid.occ.pop((d, belt_row(ln.index)))
        grid.belt_tile(d, belt_row(ln.index), S)
        for yy in range(belt_row(ln.index) + 1, H):
            grid.belt_tile(d, yy, S)
        consumed_rate = sum(p.rate for m in modules for p in m.inputs if p.item == ln.item)
        outputs.append(Port("out", "belt", ln.item, "both", d, H - 1, S, ln.rate - consumed_rate))
    outputs.sort(key=lambda p: p.x)

    Wc = max(tx for tx, _ in grid.occ) + 1
    notes = [f"bus: {L} lanes, {belt}, rows {B0}-{H - 1}; modules: " + ", ".join(m.name for m in modules)]
    for ln in bus.lanes.values():
        kind = "external" if ln.external else ("export" if ln in exported else "internal")
        notes.append(f"lane {ln.index} {ln.item} {kind} {ln.rate:.3g}/s cols {ln.start}-{ln.end}")
    return Module(name=name, width=Wc, height=H, entities=grid.ents, inputs=inputs, outputs=outputs,
                  notes=notes, wires=wires)


def entity_tiles(e):
    """Tiles covered by an entity (module-placed entities only: machines 3x3, splitters 1x2/2x1, else 1x1)."""
    x, y = e["position"]["x"], e["position"]["y"]
    if e["name"] in MACHINE_NAMES:
        cx, cy = int(x - 1.5), int(y - 1.5)
        return [(cx + dx, cy + dy) for dx in range(3) for dy in range(3)]
    if e["name"].endswith("splitter"):
        if e.get("direction", 0) in (E, W):
            return [(int(x - 0.5), int(y) - 1), (int(x - 0.5), int(y))]
        return [(int(x) - 1, int(y - 0.5)), (int(x), int(y - 0.5))]
    return [(int(x - 0.5), int(y - 0.5))]
