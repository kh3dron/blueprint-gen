"""Bus: eastbound belt lanes under a row of modules, with pull/push/merge and lane crossing.

Geometry (composite-local tiles, y grows south):

  columns 0..E-1        : external-input risers (lane j enters at column j, northbound)
  columns E+GAP ..      : modules, bottom-aligned on row `by`, GAP columns apart
  rows by+1 .. by+R     : routing band (jogs between a port column and its bus column)
  rows B0 .. B0+3L-1    : bus; lane j uses rows s_a(j)=B0+3j, s_b(j)=B0+3j+1, belt(j)=B0+3j+2
  columns > x_max       : export drops (lane j drops at d_j, deeper lanes further west), southbound

Lanes and capacity: an item may occupy several lanes (LANE_CAPACITY each). A module output is one
belt-lane wide; it is pushed onto the lane's left belt-lane (curve / splitter merge) or right
belt-lane (sideload from the south), whichever has more room, so two half-belt pushes fill a lane.
Pulls take the tightest lane whose unclaimed supply covers the port, else the largest (a shortfall is
a WARNING, not an error); leftover supply on a consumed item stays on its lane (belt backs up);
external pulls are first-fit on capacity, creating new external lanes as needed.

pull  : splitter on belt(j) at column bc-1; branch exits east into (bc, s_b(j)) and turns north.
        The last consumer of a lane takes the whole lane instead: belt(j) itself turns north.
push  : chain south from the port. At the target: S->E curve if the lane starts here, otherwise
        merge: curve east into the upper input of a splitter on the lane whose upper output tile is
        left empty (full merge).
crossing: a vertical chain tunnels (underground in/out around the belt row) only where the crossed
        lane actually has a belt at that column; otherwise it is a plain belt.
Ports of one module are grouped by proximity (gap <= 2 columns); each group gets its own bus
columns bc = first_px + 2*k and jog rows, so multi-column modules route without conflicts.
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from module import Module, Port  # noqa: E402

GAP = 2          # columns between modules
R = 4            # routing band rows
EPS = 1e-6
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
    def __init__(self, index, item, external, cap):
        self.index = index
        self.item = item
        self.external = external
        self.cap = cap
        self.left = 0.0        # items/s pushed onto the left belt-lane (internal lanes)
        self.right = 0.0       # items/s pushed onto the right belt-lane (sideloaded from below)
        self.claimed = 0.0     # items/s pulled off the lane
        self.start = None      # column of the first belt tile
        self.end = None        # column of the last belt tile (inclusive)
        self.pushes = []       # columns
        self.pulls = []        # columns

    @property
    def supply(self):
        return self.left + self.right

    @property
    def surplus(self):
        return self.supply - self.claimed


class Grid:
    """Tile occupancy + entity list for the composite."""

    def __init__(self, belt):
        self.ents = []
        self.occ = {}
        self.belt = belt

    def place(self, name, x, y, direction=N, **kw):
        key = (x, y)
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


def entity_tiles(e):
    """Tiles covered by an entity: machines 3x3, splitters 1x2/2x1, else 1x1."""
    x, y = e["position"]["x"], e["position"]["y"]
    if e["name"] in MACHINE_NAMES:
        cx, cy = int(x - 1.5), int(y - 1.5)
        return [(cx + dx, cy + dy) for dx in range(3) for dy in range(3)]
    if e["name"].endswith("splitter"):
        if e.get("direction", 0) in (E, W):
            return [(int(x - 0.5), int(y) - 1), (int(x - 0.5), int(y))]
        return [(int(x) - 1, int(y - 0.5)), (int(x), int(y - 0.5))]
    return [(int(x - 0.5), int(y - 0.5))]


def port_groups(ports):
    """Group a module's ports (sorted by x) into runs with column gaps <= 2. Returns [(group_first_px, k_local)]."""
    out, first, k, prev = [], None, 0, None
    for p in ports:
        if prev is None or p.x - prev > 2:
            first, k = p.x, 0
        else:
            k += 1
        out.append((first, k))
        prev = p.x
    return out


def allocate(modules, belt):
    """Assign every port to a lane. Returns (lanes, pull_lane, push_lane, warnings).
    pull_lane: (mi, pi) -> Lane.  push_lane: (mi, oi) -> (Lane, side) with side in {"start", "left", "right"}."""
    cap = LANE_CAPACITY[belt]
    half = cap / 2
    produced = {p.item for m in modules for p in m.outputs}
    lanes, pull_lane, push_lane, warnings = [], {}, {}, []

    def new_lane(item, external):
        ln = Lane(len(lanes), item, external, cap)
        lanes.append(ln)
        return ln

    for mi, m in enumerate(modules):
        for pi, p in enumerate(m.inputs):
            if p.item in produced:
                cands = [ln for ln in lanes if ln.item == p.item and not ln.external]
                if not cands:
                    raise ValueError(f"{m.name}: {p.item} is produced but no lane carries it yet; "
                                     f"order producers before consumers")
                fit = [ln for ln in cands if ln.surplus >= p.rate - EPS]
                if fit:
                    ln = min(fit, key=lambda ln: ln.surplus)    # best fit: tightest lane that can serve it
                else:
                    ln = max(cands, key=lambda ln: ln.surplus)  # nothing fits: largest, and warn
                if ln.surplus < p.rate - EPS:
                    warnings.append(f"WARNING {m.name}: {p.item} port needs {p.rate:.3g}/s, lane {ln.index} has "
                                    f"{max(ln.surplus, 0):.3g}/s unclaimed (short {p.rate - ln.surplus:.3g}/s)")
            else:
                cands = [ln for ln in lanes if ln.item == p.item and ln.external and ln.cap - ln.claimed >= p.rate - EPS]
                ln = cands[0] if cands else new_lane(p.item, True)
            ln.claimed += p.rate
            pull_lane[(mi, pi)] = ln
        for oi, p in enumerate(m.outputs):
            # a module output is one belt-lane wide: it lands on the left side (curve / splitter merge)
            # or the right side (sideload from below); pick the side with the most room
            best = None
            for ln in lanes:
                if ln.item != p.item or ln.external:
                    continue
                for side, used in (("left", ln.left), ("right", ln.right)):
                    room = half - used
                    if room >= p.rate - EPS and (best is None or room > best[0]):
                        best = (room, ln, side)
            if best is None:
                ln, side = new_lane(p.item, False), "start"
            else:
                _, ln, side = best
            if side == "right":
                ln.right += p.rate
            else:
                ln.left += p.rate
            push_lane[(mi, oi)] = (ln, side)
    lanes.sort(key=lambda ln: (not ln.external, ln.index))
    for i, ln in enumerate(lanes):
        ln.index = i
    return lanes, pull_lane, push_lane, warnings


def compose(name, modules, belt="transport-belt", exports=None):
    """Stitch modules (list of Module, producers before consumers) over a bus. Returns a Module."""
    exports = set(exports or [])
    lanes, pull_lane, push_lane, warnings = allocate(modules, belt)
    for w in warnings:
        print(w, file=sys.stderr)
    L = len(lanes)
    Ecount = sum(1 for ln in lanes if ln.external)
    consumed = {p.item for m in modules for p in m.inputs}
    exported = [ln for ln in lanes if not ln.external and ln.surplus > EPS
                and (ln.item not in consumed or ln.item in exports)]

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
    def nearest_pole(m, x0, gx):
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
            best = nearest_pole(m, x0, gx)
            if best and best[0] <= POLE_REACH["medium-electric-pole"]:
                wires.append([gid + 1, 5, best[1] + 1, 5])
            elif best:
                print(f"WARNING gap pole at {gx} cannot reach {m.name} pole ({best[0]:.1f} tiles)", file=sys.stderr)

    # ---- bus columns for every port --------------------------------------------------
    pulls = []   # (module, port, lane, bc, px, k_local)
    pushes = []  # (module, port, lane, col)
    for mi, (m, x0, y0) in enumerate(placements):
        for pi, (p, (first, k)) in enumerate(zip(m.inputs, port_groups(m.inputs))):
            ln = pull_lane[(mi, pi)]
            bc = x0 + first + 2 * k
            ln.pulls.append(bc)
            pulls.append((m, p, ln, bc, x0 + p.x, k))
        for oi, p in enumerate(m.outputs):
            ln, side = push_lane[(mi, oi)]
            ln.pushes.append(x0 + p.x)
            pushes.append((m, p, ln, x0 + p.x, side))

    # ---- lane starts / ends ----------------------------------------------------------
    for ln in lanes:
        ln.start = ln.index if ln.external else min(ln.pushes)
        last_pull = max(ln.pulls) if ln.pulls else ln.start
        last_merge = max((c + 2 for c in ln.pushes if c > ln.start), default=ln.start)
        ln.end = max(ln.start, last_pull, last_merge)
    drops = {}
    for ln in exported:
        d = x_max + 3 + (L - 1 - ln.index)
        drops[ln.index] = d
        ln.end = d

    def present(ln, x):
        return ln.start <= x <= ln.end

    # ---- pulls (splitters sit on the lane, so place them before the lane belts) -----
    for m, p, ln, bc, px, k in pulls:
        j = ln.index
        if bc - 1 <= ln.start:
            raise ValueError(f"{m.name}: input {p.item} at column {px} is west of lane {j} start {ln.start}; "
                             f"order producers before consumers")
        r = B0 - 1 - k
        blocked = {belt_row(o.index) for o in lanes if o.index < j and present(o, bc)}
        if bc == ln.end:
            grid.belt_tile(bc, belt_row(j), N)          # last consumer: the lane itself turns north
            rows = list(range(s_b(j), r, -1))
        else:
            grid.splitter_east(bc - 1, s_b(j))
            grid.belt_tile(bc, belt_row(j), E)          # lane continues after the splitter
            grid.belt_tile(bc, s_b(j), N)               # branch: curve E->N
            rows = list(range(s_a(j), r, -1))
        grid.vertical(bc, rows, N, blocked)
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
    for m, p, ln, col, side in pushes:
        j = ln.index
        blocked = {belt_row(o.index) for o in lanes if o.index < j and present(o, col)}
        if ln.start == col:
            grid.vertical(col, list(range(by + 1, s_b(j))), S, blocked)
            grid.belt_tile(col, s_b(j), S)   # new lane: S->E curve at belt(j)
        elif side == "left":
            grid.vertical(col, list(range(by + 1, s_b(j))), S, blocked)
            grid.belt_tile(col, s_b(j), E)   # merge: into the upper input of a splitter on the lane
            grid.splitter_east(col + 1, s_b(j))
        else:
            # right belt-lane: tunnel under the lane, come back up one column east and sideload from the south
            grid.vertical(col, list(range(by + 1, s_b(j + 1))), S, blocked | {belt_row(j)})
            grid.belt_tile(col, s_b(j + 1), E)
            grid.belt_tile(col + 1, s_b(j + 1), N)
            grid.belt_tile(col + 1, s_a(j + 1), N)

    # ---- lane belts ------------------------------------------------------------------
    for ln in lanes:
        for xx in range(ln.start, ln.end + 1):
            if (xx, belt_row(ln.index)) not in grid.occ:
                grid.belt_tile(xx, belt_row(ln.index), E)

    # ---- external input risers -------------------------------------------------------
    inputs = []
    for ln in lanes:
        if not ln.external:
            continue
        j = ln.index
        for yy in range(H - 1, belt_row(j), -1):
            grid.belt_tile(j, yy, N)
        inputs.append(Port("in", "belt", ln.item, "both", j, H - 1, N, ln.claimed))

    # ---- export drops ----------------------------------------------------------------
    outputs = []
    for ln in exported:
        d = drops[ln.index]
        grid.ents = [e for e in grid.ents if not (e["position"] == {"x": d + 0.5, "y": belt_row(ln.index) + 0.5})]
        grid.occ.pop((d, belt_row(ln.index)))
        grid.belt_tile(d, belt_row(ln.index), S)
        for yy in range(belt_row(ln.index) + 1, H):
            grid.belt_tile(d, yy, S)
        outputs.append(Port("out", "belt", ln.item, "both", d, H - 1, S, ln.surplus))
    outputs.sort(key=lambda p: p.x)

    Wc = max(tx for tx, _ in grid.occ) + 1
    notes = [f"bus: {L} lanes, {belt}, rows {B0}-{H - 1}; modules: " + ", ".join(m.name for m in modules)]
    for ln in lanes:
        kind = "external" if ln.external else ("export" if ln in exported else "internal")
        flow = ln.claimed if ln.external else ln.supply
        bal = "" if ln.external else f" (L {ln.left:.3g} R {ln.right:.3g}, claimed {ln.claimed:.3g})"
        notes.append(f"lane {ln.index} {ln.item} {kind} {flow:.3g}/{ln.cap:g}/s cols {ln.start}-{ln.end}{bal}")
    return Module(name=name, width=Wc, height=H, entities=grid.ents, inputs=inputs, outputs=outputs,
                  notes=notes, wires=wires)
