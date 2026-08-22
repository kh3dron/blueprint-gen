"""Bus: eastbound belt lanes under a row of modules, with pull/push/merge and lane crossing.

Geometry (composite-local tiles, y grows south):

  columns 0..E-1        : external-input risers (lane j enters at column j, northbound)
  columns E+GAP ..      : modules, bottom-aligned on row `by`, GAP columns apart
  rows by+1 .. by+R     : routing band (jogs between a port column and its bus column)
  rows B0 .. B0+L-1     : bus; lane j is row B0+j (one row per lane); row B0+L is a spare row
  columns > x_max       : export drops (lane j drops at d_j, deeper lanes further west), southbound

Lanes and capacity: an item may occupy several lanes (LANE_CAPACITY each). A module output is one
belt-lane wide; it is pushed onto the lane's left belt-lane (curve / splitter merge) or right
belt-lane (sideload from the south), whichever has more room, so two half-belt pushes fill a lane.
Pulls take the tightest lane whose unclaimed supply covers the port, else the largest (a shortfall is
a WARNING, not an error); leftover supply on a consumed item stays on its lane (belt backs up);
external pulls are first-fit on capacity, creating new external lanes as needed.

pull  : splitter on the lane at column bc-1 (rows j-1, j); branch exits east into (bc, j-1) and turns
        north. The last consumer of a lane takes the whole lane instead: the lane turns north at bc.
push  : chain south from the port. At the target: S->E curve if the lane starts here; left merge:
        curve east at row j-1 into the upper input of a splitter at (col+1, rows j-1..j) whose upper
        output is blocked; right merge: through the lane row (the lane ducks), east along row j+1,
        north at col+2 to sideload the lane from the south.
crossing: vertical chains run straight. Every lane ducks underground (in/out on the lane row) under
        each run of foreign tiles in its row: crossing chains, other lanes' splitters, merge feeders.
        Runs separated by one free tile merge; a run longer than MAX_GAP[belt] is a PackError.
Ports of one module are grouped by proximity (gap <= 2 columns); each group gets its own bus
columns bc = first_px + spacing*k and jog rows. compose() searches spacing 3..6 until the pack fits.
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
MAX_GAP = {"transport-belt": 4, "fast-transport-belt": 6, "express-transport-belt": 8, "turbo-transport-belt": 10}
SEARCH = ((3, 3), (4, 3), (4, 4), (5, 4), (6, 5))   # (chain spacing, module gap) candidates, in order
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
        self.log = None        # keys placed since begin(), for rollback()

    def begin(self):
        self.log = []
        self.n_ents = len(self.ents)

    def rollback(self):
        for key in self.log:
            self.occ.pop(key, None)
        del self.ents[self.n_ents:]
        self.log = None

    def commit(self):
        self.log = None

    def _take(self, key, name):
        if key in self.occ:
            raise ValueError(f"tile {key} already holds {self.occ[key]}, cannot place {name}")
        self.occ[key] = name
        if self.log is not None:
            self.log.append(key)

    def place(self, name, x, y, direction=N, **kw):
        self._take((x, y), name)
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
            self._take((x, y_top + dy), SPLITTER[self.belt])
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




class PackError(ValueError):
    pass


def compose(name, modules, belt="transport-belt", exports=None):
    """Stitch modules (producers before consumers) over a bus; retries with wider chain spacing
    until every lane can duck under its crossings. Returns a Module."""
    last = None
    for spacing, gap in SEARCH:
        try:
            return _layout(name, modules, belt, set(exports or []), spacing, gap)
        except PackError as ex:
            last = ex
            print(f"spacing {spacing} gap {gap}: {ex}; retrying", file=sys.stderr)
    raise ValueError(f"bus does not pack with (spacing, gap) in {SEARCH}: {last}")


def _layout(name, modules, belt, exports, spacing, gap):
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
    row = lambda j: B0 + j              # noqa: E731
    H = B0 + L + 1                      # one spare row under the last lane (right merges, ports)
    grid = Grid(belt)
    wires = []
    own = {ln.index: set() for ln in lanes}   # (x, row) tiles placed on a lane row that belong to that lane
    plain = {ln.index: set() for ln in lanes} # own tiles that are plain eastbound belts (may become undergrounds)

    # ---- place modules; a module's footprint also covers its bus columns ---------------
    x = Ecount + gap
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
        extent = m.width
        for p, (first, k) in zip(m.inputs, port_groups(m.inputs)):
            extent = max(extent, first + spacing * k + spacing + 2)   # room for candidate shifts
        x += extent + gap
    x_max = x - gap - 1

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
    pulls, pushes = [], []
    for mi, (m, x0, y0) in enumerate(placements):
        for pi, (p, (first, k)) in enumerate(zip(m.inputs, port_groups(m.inputs))):
            pulls.append((m, pull_lane[(mi, pi)], x0 + first + spacing * k, x0 + p.x, k, p))
        for oi, p in enumerate(m.outputs):
            ln, side = push_lane[(mi, oi)]
            ln.pushes.append(x0 + p.x)
            pushes.append((m, p, ln, x0 + p.x, side))

    for ln in lanes:
        ln.start = ln.index if ln.external else min(ln.pushes)
    drops = {}
    for ln in exported:
        d = x_max + 3 + (L - 1 - ln.index)
        drops[ln.index] = d

    def lane_tile(ln, x, d):
        own[ln.index].add((x, row(ln.index)))
        return grid.belt_tile(x, row(ln.index), d)

    # ---- pushes (placed first so pull chains route around them) -----------------------
    for m, p, ln, col, side in pushes:
        j = ln.index
        if ln.start == col:
            for yy in range(by + 1, row(j)):
                grid.belt_tile(col, yy, S)
            lane_tile(ln, col, E)                     # new lane: S->E curve
        elif side == "left":
            for yy in range(by + 1, row(j) - 1):
                grid.belt_tile(col, yy, S)
            grid.belt_tile(col, row(j) - 1, E)        # feeder into the splitter's upper input
            grid.splitter_east(col + 1, row(j) - 1)   # upper output blocked -> full merge onto the lane
            own[j].add((col + 1, row(j)))
        else:
            for yy in range(by + 1, row(j) + 1):
                grid.belt_tile(col, yy, S)            # through the lane row; the lane ducks under it
            grid.belt_tile(col, row(j) + 1, E)
            grid.belt_tile(col + 1, row(j) + 1, E)
            grid.belt_tile(col + 2, row(j) + 1, N)    # sideloads the lane from the south: right belt-lane

    # ---- pulls: candidate bus columns bc, bc+1, ... with rollback on collision --------
    def place_pull(ln, bc, px, k, whole):
        j = ln.index
        r = B0 - 1 - k
        if whole:
            lane_tile(ln, bc, N)                      # last consumer: the lane turns north
            top = row(j) - 1
        else:
            grid.splitter_east(bc - 1, row(j) - 1)
            own[j].add((bc - 1, row(j)))
            lane_tile(ln, bc, E)                      # lane continues after the splitter
            plain[j].add((bc, row(j)))
            grid.belt_tile(bc, row(j) - 1, N)         # branch: curve E->N
            top = row(j) - 2
        for yy in range(top, r, -1):
            grid.belt_tile(bc, yy, N)
        if px == bc:
            if (bc, r) not in grid.occ:               # lane-0 branch curve already sits on row B0-1
                grid.belt_tile(bc, r, N)
        else:
            step = 1 if px > bc else -1
            grid.belt_tile(bc, r, E if step > 0 else W)
            for xx in range(bc + step, px, step):
                grid.belt_tile(xx, r, E if step > 0 else W)
            grid.belt_tile(px, r, N)
        for yy in range(r - 1, by, -1):
            grid.belt_tile(px, yy, N)

    # the last consumer of a lane (largest nominal bc) takes the whole lane
    last_bc = {}
    for m, ln, bc, px, k, p in pulls:
        last_bc[ln.index] = max(last_bc.get(ln.index, -1), bc)
    for ln in lanes:
        last_merge = max((c + 2 for c in ln.pushes if c > ln.start), default=ln.start)
        ln.end = max(ln.start, last_bc.get(ln.index, ln.start), last_merge, drops.get(ln.index, ln.start))
    for m, ln, bc0, px, k, p in pulls:
        if bc0 - 1 <= ln.start:
            raise ValueError(f"{m.name}: input {p.item} at column {px} is west of lane {ln.index} start {ln.start}; "
                             f"order producers before consumers")
        whole = ln.index not in drops and bc0 == last_bc[ln.index] and ln.end == bc0
        placed = False
        for bc in range(bc0, bc0 + spacing):
            grid.begin()
            try:
                place_pull(ln, bc, px, k, whole)
                own_snapshot = None
            except ValueError:
                grid.rollback()
                own[ln.index].discard((bc, row(ln.index)))
                own[ln.index].discard((bc - 1, row(ln.index)))
                plain[ln.index].discard((bc, row(ln.index)))
                continue
            grid.commit()
            ln.pulls.append(bc)
            if whole:
                ln.end = bc
            else:
                ln.end = max(ln.end, bc)
            placed = True
            break
        if not placed:
            raise PackError(f"{m.name}: no bus column for {p.item} in {bc0}..{bc0 + spacing - 1}")

    # ---- external input risers and export drops ---------------------------------------
    inputs, outputs = [], []
    for ln in lanes:
        if ln.external:
            j = ln.index
            for yy in range(H - 1, row(j), -1):
                grid.belt_tile(j, yy, N)
            lane_tile(ln, j, E)                       # N->E curve starts the lane
            inputs.append(Port("in", "belt", ln.item, "both", j, H - 1, N, ln.claimed))
    for ln in exported:
        d = drops[ln.index]
        lane_tile(ln, d, S)                           # E->S curve ends the lane
        for yy in range(row(ln.index) + 1, H):
            grid.belt_tile(d, yy, S)
        outputs.append(Port("out", "belt", ln.item, "both", d, H - 1, S, ln.surplus))
    outputs.sort(key=lambda p: p.x)

    # ---- lanes: duck under foreign tiles, then fill -----------------------------------
    max_gap = MAX_GAP[belt]
    ug_count = 0
    for ln in lanes:
        j, y = ln.index, row(ln.index)
        blocked = [x for x in range(ln.start, ln.end + 1) if (x, y) in grid.occ and (x, y) not in own[j]]
        runs = []
        for x in blocked:
            if runs and x - runs[-1][1] <= 2:         # adjacent, or one free tile between: same run
                runs[-1][1] = x
            else:
                runs.append([x, x])
        for a, b in runs:
            if b - a + 1 > max_gap:
                raise PackError(f"lane {j} {ln.item} must duck under columns {a}-{b} ({b - a + 1} tiles) "
                                f"but {belt} spans at most {max_gap}")
            for xx, kind in ((a - 1, "input"), (b + 1, "output")):
                if (xx, y) in plain[j]:               # a plain lane belt: replace it with the underground
                    grid.ents = [e for e in grid.ents if e["position"] != {"x": xx + 0.5, "y": y + 0.5}]
                    grid.occ.pop((xx, y))
                    plain[j].discard((xx, y))
                if not ln.start < xx < ln.end or (xx, y) in grid.occ:
                    held = grid.occ.get((xx, y))
                    raise PackError(f"lane {j} {ln.item}: no free tile at column {xx} for an underground {kind} "
                                    f"around columns {a}-{b} (tile holds {held}, own={(xx, y) in own[j]}; lane cols "
                                    f"{ln.start}-{ln.end}, pushes {ln.pushes}, pulls {ln.pulls}; run tiles "
                                    f"{[grid.occ.get((c, y)) for c in range(a, b + 1)]})")
            grid.ug(a - 1, y, E, "input")
            grid.ug(b + 1, y, E, "output")
            ug_count += 1
        for xx in range(ln.start, ln.end + 1):
            if (xx, y) not in grid.occ:
                grid.belt_tile(xx, y, E)

    Wc = max(tx for tx, _ in grid.occ) + 1
    notes = [f"bus: {L} lanes, {belt}, rows {B0}-{H - 1}, chain spacing {spacing}, {ug_count} lane ducks; modules: "
             + ", ".join(m.name for m in modules)]
    for ln in lanes:
        kind = "external" if ln.external else ("export" if ln in exported else "internal")
        flow = ln.claimed if ln.external else ln.supply
        bal = "" if ln.external else f" (L {ln.left:.3g} R {ln.right:.3g}, claimed {ln.claimed:.3g})"
        notes.append(f"lane {ln.index} {ln.item} {kind} {flow:.3g}/{ln.cap:g}/s cols {ln.start}-{ln.end}{bal}")
    return Module(name=name, width=Wc, height=H, entities=grid.ents, inputs=inputs, outputs=outputs,
                  notes=notes, wires=wires)
