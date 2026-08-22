"""Bus: eastbound belt lanes with modules on both sides, pull/push/merge, lane crossing, roboports.

Geometry (composite-local tiles, y grows south):

  columns x_start..x_start+E-1 : external-input risers (lane j enters at its own column, northbound)
  north modules                : bottom-aligned on row `by`, rows 0..by
  north routing band           : rows by+1 .. by+R
  bus                          : one row per lane, row(j) = B0+j, B0 = by+R+1; spare row B0+L below
  south routing band           : rows B0+L+1 .. B0+L+R          (only if south modules exist)
  south modules (mirrored)     : top-aligned on row `bys` = B0+L+R+1
  export drops                 : columns east of everything, southbound to the bottom row

Sides: modules are dealt to the side whose x cursor is further west, in producer-before-consumer
order; a consumer is never placed west of its lanes' starts. South modules are mirrored vertically
(module.mirror): their ports sit on the top edge, inputs flowing south, outputs flowing north.

Lanes and capacity: an item may occupy several lanes (LANE_CAPACITY each). A module output is one
belt-lane wide. A north module lands on the lane's LEFT belt-lane with a curve / splitter merge and on
the RIGHT belt-lane with a sideload from below; a south module the other way round. Pushes pick the
belt-lane with the most room. Pulls take the tightest lane whose unclaimed supply covers the port, else
the largest (WARNING on shortfall); external pulls are first-fit on capacity.

pull  : north: splitter on the lane at bc-1 (rows j-1, j), branch exits east into (bc, j-1), north.
        south: splitter at bc-1 (rows j, j+1), branch exits east into (bc, j+1), south.
        The last consumer of a lane takes the whole lane: the lane itself turns toward the module.
        Placement is a candidate search (bc, bc+1, ...) in a grid transaction, rolled back on collision.
push  : chain from the port to the lane. New lane: curve into row(j). Merge on the natural belt-lane:
        feeder into the module-side input of a splitter at col+1 whose other output is blocked. Merge on
        the far belt-lane: chain through the lane row (the lane ducks), two tiles east on the far-side
        row, back to sideload the lane.
crossing: vertical chains never tunnel; each lane ducks (underground pair, slowest tier whose span
        covers the run) under every run of foreign tiles in its row. PackError if no tier spans it or no
        free tile exists to surface; compose() then retries with the next (spacing, gap).
power : pole chains along the module rows; south network bridged to the north one; every roboport pole
        connected by a pole path.
roboports: optional grid, first at the bottom-left; 6-column bands kept clear, lanes duck under them.
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from module import Module, Port, mirror  # noqa: E402

R = 4            # routing band rows per side
EPS = 1e-6
N, E, S, W = 0, 4, 8, 12
MACHINE_NAMES = {"assembling-machine-1", "assembling-machine-2", "assembling-machine-3", "electric-furnace"}
UNDERGROUND = {"transport-belt": "underground-belt", "fast-transport-belt": "fast-underground-belt",
               "express-transport-belt": "express-underground-belt", "turbo-transport-belt": "turbo-underground-belt"}
SPLITTER = {"transport-belt": "splitter", "fast-transport-belt": "fast-splitter",
            "express-transport-belt": "express-splitter", "turbo-transport-belt": "turbo-splitter"}
POLE_REACH = {"small-electric-pole": 7.5, "medium-electric-pole": 9.0, "big-electric-pole": 30.0}
MAX_GAP = {"transport-belt": 4, "fast-transport-belt": 6, "express-transport-belt": 8, "turbo-transport-belt": 10}
TIERS = ["transport-belt", "fast-transport-belt", "express-transport-belt", "turbo-transport-belt"]
SEARCH = ((3, 2), (3, 3), (4, 3), (4, 4), (5, 4), (6, 5))   # (chain spacing, module gap) candidates
LANE_CAPACITY = {"transport-belt": 15.0, "fast-transport-belt": 30.0, "express-transport-belt": 45.0,
                 "turbo-transport-belt": 60.0}


class PackError(ValueError):
    pass


class Lane:
    def __init__(self, index, item, external, cap):
        self.index = index
        self.item = item
        self.external = external
        self.cap = cap
        self.left = 0.0        # items/s on the left belt-lane
        self.right = 0.0       # items/s on the right belt-lane
        self.claimed = 0.0     # items/s pulled off the lane
        self.start = None
        self.end = None
        self.pushes = []       # columns
        self.pulls = []        # columns

    @property
    def supply(self):
        return self.left + self.right

    @property
    def surplus(self):
        return self.supply - self.claimed


class Grid:
    """Tile occupancy + entity list for the composite, with transactions for candidate search."""

    def __init__(self, belt):
        self.ents = []
        self.occ = {}
        self.belt = belt
        self.log = None

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

    def splitter_east(self, x, y_top):
        """Splitter facing east occupying (x, y_top) and (x, y_top+1); center at (x+0.5, y_top+1)."""
        for dy in (0, 1):
            self._take((x, y_top + dy), SPLITTER[self.belt])
        e = {"name": SPLITTER[self.belt], "position": {"x": x + 0.5, "y": y_top + 1}, "direction": E}
        self.ents.append(e)
        return e


def entity_tiles(e):
    """Tiles covered by an entity: machines 3x3, roboports 4x4, splitters 1x2/2x1, else 1x1."""
    x, y = e["position"]["x"], e["position"]["y"]
    if e["name"] in MACHINE_NAMES:
        cx, cy = int(x - 1.5), int(y - 1.5)
        return [(cx + dx, cy + dy) for dx in range(3) for dy in range(3)]
    if e["name"] == "roboport":
        cx, cy = int(x - 2), int(y - 2)
        return [(cx + dx, cy + dy) for dx in range(4) for dy in range(4)]
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


def allocate(modules, sides, belt):
    """Assign every port to a lane. Returns (lanes, pull_lane, push_lane, warnings).
    pull_lane: (mi, pi) -> Lane.  push_lane: (mi, oi) -> (Lane, belt_lane) with belt_lane in {left, right}."""
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
                ln = min(fit, key=lambda ln: ln.surplus) if fit else max(cands, key=lambda ln: ln.surplus)
                if ln.surplus < p.rate - EPS:
                    warnings.append(f"WARNING {m.name}: {p.item} port needs {p.rate:.3g}/s, lane {ln.index} has "
                                    f"{max(ln.surplus, 0):.3g}/s unclaimed (short {p.rate - ln.surplus:.3g}/s)")
            else:
                cands = [ln for ln in lanes if ln.item == p.item and ln.external and ln.cap - ln.claimed >= p.rate - EPS]
                ln = cands[0] if cands else new_lane(p.item, True)
            ln.claimed += p.rate
            pull_lane[(mi, pi)] = ln
        natural = "left" if sides[mi] == "N" else "right"
        for oi, p in enumerate(m.outputs):
            best = None
            for ln in lanes:
                if ln.item != p.item or ln.external:
                    continue
                for side, used in (("left", ln.left), ("right", ln.right)):
                    room = half - used
                    if room >= p.rate - EPS and (best is None or room > best[0] or (room == best[0] and side == natural)):
                        best = (room, ln, side)
            if best is None:
                ln, side = new_lane(p.item, False), natural
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


def compose(name, modules, belt="transport-belt", exports=None, roboport=None, two_sided=True):
    """Stitch modules (producers before consumers) over a bus; retries (spacing, gap) candidates until
    every lane can duck under its crossings. Returns a Module."""
    last = None
    for spacing, gap in SEARCH:
        try:
            return _layout(name, modules, belt, set(exports or []), spacing, gap, roboport, two_sided)
        except PackError as ex:
            last = ex
            print(f"spacing {spacing} gap {gap}: {ex}; retrying", file=sys.stderr)
    raise ValueError(f"bus does not pack with (spacing, gap) in {SEARCH}: {last}")


def _layout(name, modules, belt, exports, spacing, gap, rp=None, two_sided=True):
    def forbidden(x):
        return rp is not None and (x + 1) % rp <= 5      # roboport bands: columns rp*i-1 .. rp*i+4

    def extent_of(m):
        ext = m.width
        for p, (first, k) in zip(m.inputs, port_groups(m.inputs)):
            ext = max(ext, first + spacing * k + 2)
        return ext

    # ---- sides and x positions (producers before consumers on each side) --------------
    n_mod = len(modules)
    sides, xs = [None] * n_mod, [0] * n_mod
    produced_at = {}                   # item -> max push column so far (consumers must be east of it)
    x_start = 5 if rp else 0
    # external lane count decides where modules begin; allocate with provisional sides first
    lanes0, _, _, _ = allocate(modules, ["N"] * n_mod, belt)
    Ecount = sum(1 for ln in lanes0 if ln.external)
    cursor = {"N": x_start + Ecount + gap, "S": x_start + Ecount + gap}
    reserved = set()                   # bus columns claimed by placed modules (both sides)
    for mi, m in enumerate(modules):
        side = "N" if (not two_sided or cursor["N"] <= cursor["S"]) else "S"
        x = cursor[side]
        for p in m.inputs:
            if p.item in produced_at:
                x = max(x, produced_at[p.item] + 3)
        ext = extent_of(m)
        if rp and ext + 1 > rp - 6:
            raise ValueError(f"{m.name} is {ext} columns wide; only {rp - 7} fit between roboport bands {rp} apart")

        def bus_cols(x):
            cols = set()
            for p in m.outputs:
                cols.update(range(x + p.x, x + p.x + 3))                       # push, merge splitter, sideload
            for p, (first, k) in zip(m.inputs, port_groups(m.inputs)):
                cols.update((x + first + spacing * k - 1, x + first + spacing * k))   # splitter + nominal chain
            return cols
        while any(forbidden(c) for c in range(x, x + ext + 1)) or bus_cols(x) & reserved:
            x += 1                      # roboport band, or a bus column already used by the other side
        reserved.update(bus_cols(x))
        sides[mi], xs[mi] = side, x
        for p in m.outputs:
            produced_at[p.item] = max(produced_at.get(p.item, -1), x + p.x)
        cursor[side] = x + ext + gap
    lanes, pull_lane, push_lane, warnings = allocate(modules, sides, belt)
    for w in warnings:
        print(w, file=sys.stderr)
    L = len(lanes)
    consumed = {p.item for m in modules for p in m.inputs}
    exported = [ln for ln in lanes if not ln.external and ln.surplus > EPS
                and (ln.item not in consumed or ln.item in exports)]
    has_south = any(s == "S" for s in sides)

    # ---- rows ---------------------------------------------------------------------------
    by = max([m.height for m, s in zip(modules, sides) if s == "N"] + [1]) - 1
    B0 = by + R + 1
    row = lambda j: B0 + j              # noqa: E731
    spare = B0 + L
    if has_south:
        bys = spare + R + 1
        H = bys + max(m.height for m, s in zip(modules, sides) if s == "S")
    else:
        bys = None
        H = spare + 1
    x_max = max(xs[i] + extent_of(modules[i]) - 1 for i in range(n_mod))
    grid = Grid(belt)
    wires = []
    own = {ln.index: set() for ln in lanes}
    plain = {ln.index: set() for ln in lanes}

    # ---- place modules ------------------------------------------------------------------
    placements = []
    for mi, m in enumerate(modules):
        if sides[mi] == "S":
            m = mirror(m)
        x0 = xs[mi]
        y0 = by - m.height + 1 if sides[mi] == "N" else bys
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
        placements.append((m, x0, y0, sides[mi]))
    n_module_ents = len(grid.ents)

    # ---- power: pole chains along each module row, south bridged to north ----------------
    reach = POLE_REACH["medium-electric-pole"]

    def nearest_pole(m, x0, gx, gy, limit):
        best = None
        for i, e in enumerate(grid.ents[:limit]):
            if e["name"].endswith("electric-pole") and x0 <= e["position"]["x"] < x0 + m.width:
                d = ((e["position"]["x"] - gx - 0.5) ** 2 + (e["position"]["y"] - gy - 0.5) ** 2) ** 0.5
                if best is None or d < best[0]:
                    best = (d, i)
        return best

    def nearest_in(x, y, ids):
        best = None
        for i in ids:
            e = grid.ents[i]
            d = ((e["position"]["x"] - x - 0.5) ** 2 + (e["position"]["y"] - y - 0.5) ** 2) ** 0.5
            if best is None or d < best[0]:
                best = (d, i)
        return best

    def usable(cx, cy):
        if cx < 0 or cy < 0 or cy >= H or (cx, cy) in grid.occ:
            return False
        if B0 <= cy < B0 + L:                      # on a lane row: leave room for the lane to duck under
            return all((cx + d, cy) not in grid.occ for d in (-2, -1, 1, 2))
        return True

    last_path = [""]

    def power_path(pid, x, y, targets, via=None):
        """Connect pole `pid` at (x, y) to the network formed by the pole entity ids in `targets`: wire
        if in reach, else run medium poles toward the nearest target (vertical first, then horizontal,
        steps never longer than the remaining distance). `via` = (x, y) waypoint to pass within reach of
        first (used to get around the riser wall). True if wired."""
        for _ in range(96):
            if via is not None:
                if ((via[0] - x) ** 2 + (via[1] - y) ** 2) ** 0.5 <= reach - 1:
                    via = None
                    continue
                tx, ty = via
            else:
                best = nearest_in(x, y, targets)
                if best is None:
                    return False
                if best[0] <= reach:
                    wires.append([pid + 1, 5, best[1] + 1, 5])
                    return True
                tx, ty = int(grid.ents[best[1]]["position"]["x"] - 0.5), int(grid.ents[best[1]]["position"]["y"] - 0.5)
            vertical = ty != y
            span = abs(ty - y) if vertical else abs(tx - x)
            found = None
            for k in range(min(int(reach), span), 0, -1):
                if vertical:
                    cy, cx0 = y + (k if ty > y else -k), x
                else:
                    cy, cx0 = y, x + (k if tx > x else -k)
                for dx in (0, 1, -1, 2, -2, 3, -3, 4, -4):
                    if usable(cx0 + dx, cy):
                        found = (cx0 + dx, cy)
                        break
                if found:
                    break
            if not found:
                return False
            nid = len(grid.ents)
            grid.place("medium-electric-pole", *found)
            wires.append([pid + 1, 5, nid + 1, 5])
            pid, (x, y) = nid, found
        return False

    for side, prow in (("N", by), ("S", bys)):
        chain = [(m, x0) for m, x0, y0, s in placements if s == side]
        chain.sort(key=lambda t: t[1])
        for (ma, xa), (mb, xb) in zip(chain, chain[1:]):
            prev, gx = None, xa + ma.width
            while True:
                while (gx, prow) in grid.occ:
                    gx += 1
                gid = len(grid.ents)
                grid.place("medium-electric-pole", gx, prow)
                if prev is None:
                    best = nearest_pole(ma, xa, gx, prow, n_module_ents)
                    if best and best[0] <= reach:
                        wires.append([gid + 1, 5, best[1] + 1, 5])
                    elif best:
                        print(f"WARNING gap pole at {gx} cannot reach {ma.name} pole ({best[0]:.1f} tiles)", file=sys.stderr)
                else:
                    wires.append([prev + 1, 5, gid + 1, 5])
                best = nearest_pole(mb, xb, gx, prow, n_module_ents)
                if best and best[0] <= reach:
                    wires.append([gid + 1, 5, best[1] + 1, 5])
                    break
                if gx + int(reach) >= xb + mb.width:
                    print(f"WARNING pole chain at {gx} cannot reach {mb.name} pole", file=sys.stderr)
                    break
                prev = gid
                gx += int(reach)
    # ---- bus columns for every port ----------------------------------------------------
    pulls, pushes = [], []
    for mi, (m, x0, y0, side) in enumerate(placements):
        for pi, (p, (first, k)) in enumerate(zip(m.inputs, port_groups(m.inputs))):
            pulls.append((m, pull_lane[(mi, pi)], x0 + first + spacing * k, x0 + p.x, k, p, side))
        for oi, p in enumerate(m.outputs):
            ln, bl = push_lane[(mi, oi)]
            ln.pushes.append(x0 + p.x)
            pushes.append((m, p, ln, x0 + p.x, bl, side))

    for ln in lanes:
        ln.start = x_start + ln.index if ln.external else min(ln.pushes)
    drops = {}
    d = x_max + 3
    for ln in sorted(exported, key=lambda ln: -ln.index):
        while forbidden(d):
            d += 1
        drops[ln.index] = d
        d += 1

    def lane_tile(ln, x, dirn):
        own[ln.index].add((x, row(ln.index)))
        return grid.belt_tile(x, row(ln.index), dirn)

    # ---- pushes (first, so pull chains route around them) -------------------------------
    for m, p, ln, col, bl, side in pushes:
      try:
        j = ln.index
        natural = "left" if side == "N" else "right"
        if side == "N":
            rows_to = lambda stop: range(by + 1, stop)                       # noqa: E731
            dirn, far_row, near_row = S, row(j) + 1, row(j) - 1
        else:
            rows_to = lambda stop: range(bys - 1, stop, -1)                  # noqa: E731
            dirn, far_row, near_row = N, row(j) - 1, row(j) + 1
        if ln.start == col:
            for yy in rows_to(row(j)):
                grid.belt_tile(col, yy, dirn)
            lane_tile(ln, col, E)                                            # new lane: curve into the lane
        elif bl == natural:
            for yy in rows_to(near_row):
                grid.belt_tile(col, yy, dirn)
            grid.belt_tile(col, near_row, E)                                 # feeder into the splitter's module-side input
            grid.splitter_east(col + 1, min(near_row, row(j)))               # other output blocked -> full merge
            own[j].add((col + 1, row(j)))
        else:
            for yy in rows_to(far_row):
                grid.belt_tile(col, yy, dirn)                                # through the lane row; the lane ducks
            grid.belt_tile(col, far_row, E)
            grid.belt_tile(col + 1, far_row, E)
            grid.belt_tile(col + 2, far_row, N if side == "N" else S)        # sideload from the far side
      except ValueError as ex:
        raise ValueError(f"push {m.name} {p.item} col {col} side {side} lane {ln.index} ({bl}, start {ln.start}): {ex}")

    # ---- pulls: candidate bus columns with rollback --------------------------------------
    last_bc = {}
    for m, ln, bc, px, k, p, side in pulls:
        last_bc[ln.index] = max(last_bc.get(ln.index, -1), bc)
    for ln in lanes:
        last_merge = max((c + 2 for c in ln.pushes if c > ln.start), default=ln.start)
        ln.end = max(ln.start, last_bc.get(ln.index, ln.start), last_merge, drops.get(ln.index, ln.start))

    lane_of_row = {row(ln.index): ln.index for ln in lanes}

    def structural(x, y):
        """True if (x, y) is an own tile of its lane that cannot become an underground (splitter / turn / curve)."""
        j = lane_of_row.get(y)
        return j is not None and (x, y) in own[j] and (x, y) not in plain[j]

    def foreign(x, y, j):
        return (x, y) in grid.occ and (x, y) not in own[j]

    def place_pull(ln, bc, px, k, whole, side):
        j = ln.index
        # duck feasibility: the lane must be able to surface just before this pull's splitter / turn,
        # and this chain must not sit right beside another lane's splitter or turn on any row it crosses
        feed = bc - 1 if whole else bc - 2
        if foreign(feed, row(j), j):
            raise ValueError("lane cannot surface before the pull")
        crossed = range(B0, row(j)) if side == "N" else range(row(j) + 1, B0 + L)
        for y in crossed:
            o = lanes[lane_of_row[y]]
            if o.start < bc < o.end and (structural(bc - 1, y) or structural(bc + 1, y)):
                raise ValueError("chain would block a neighbouring lane structure")
        if side == "N":
            r = B0 - 1 - k
            if whole:
                lane_tile(ln, bc, N)
                top = row(j) - 1
            else:
                grid.splitter_east(bc - 1, row(j) - 1)
                own[j].add((bc - 1, row(j)))
                lane_tile(ln, bc, E)
                plain[j].add((bc, row(j)))
                grid.belt_tile(bc, row(j) - 1, N)
                top = row(j) - 2
            for yy in range(top, r, -1):
                grid.belt_tile(bc, yy, N)
            if px == bc:
                if (bc, r) not in grid.occ:
                    grid.belt_tile(bc, r, N)
            else:
                step = 1 if px > bc else -1
                grid.belt_tile(bc, r, E if step > 0 else W)
                for xx in range(bc + step, px, step):
                    grid.belt_tile(xx, r, E if step > 0 else W)
                grid.belt_tile(px, r, N)
            for yy in range(r - 1, by, -1):
                grid.belt_tile(px, yy, N)
        else:
            r = spare + 1 + k
            if whole:
                lane_tile(ln, bc, S)
                top = row(j) + 1
            else:
                grid.splitter_east(bc - 1, row(j))
                own[j].add((bc - 1, row(j)))
                lane_tile(ln, bc, E)
                plain[j].add((bc, row(j)))
                grid.belt_tile(bc, row(j) + 1, S)
                top = row(j) + 2
            for yy in range(top, r):
                grid.belt_tile(bc, yy, S)
            if px == bc:
                if (bc, r) not in grid.occ:
                    grid.belt_tile(bc, r, S)
            else:
                step = 1 if px > bc else -1
                grid.belt_tile(bc, r, E if step > 0 else W)
                for xx in range(bc + step, px, step):
                    grid.belt_tile(xx, r, E if step > 0 else W)
                grid.belt_tile(px, r, S)
            for yy in range(r + 1, bys):
                grid.belt_tile(px, yy, S)

    for m, ln, bc0, px, k, p, side in pulls:
        if bc0 - 1 <= ln.start:
            raise ValueError(f"{m.name}: input {p.item} at column {px} is west of lane {ln.index} start {ln.start}; "
                             f"order producers before consumers")
        whole = ln.index not in drops and bc0 == last_bc[ln.index] and ln.end == bc0
        placed = False
        for bc in range(bc0, bc0 + spacing):
            if forbidden(bc) or forbidden(bc - 1):
                continue
            grid.begin()
            try:
                place_pull(ln, bc, px, k, whole, side)
            except ValueError:
                grid.rollback()
                own[ln.index].discard((bc, row(ln.index)))
                own[ln.index].discard((bc - 1, row(ln.index)))
                plain[ln.index].discard((bc, row(ln.index)))
                continue
            grid.commit()
            ln.pulls.append(bc)
            ln.end = bc if whole else max(ln.end, bc)
            placed = True
            break
        if not placed:
            raise PackError(f"{m.name}: no bus column for {p.item} in {bc0}..{bc0 + spacing - 1}")

    # ---- power bridge south -> north (after the chains, so it routes around them) ----------
    if has_south:
        north_ids = [i for i, e in enumerate(grid.ents) if e["name"].endswith("electric-pole") and e["position"]["y"] < B0]
        south = [(i, e) for i, e in enumerate(grid.ents) if e["name"].endswith("electric-pole") and e["position"]["y"] > spare]
        if south and north_ids:
            i, e = min(south, key=lambda t: (t[1]["position"]["y"], t[1]["position"]["x"]))
            if not power_path(i, int(e["position"]["x"] - 0.5), int(e["position"]["y"] - 0.5), north_ids):
                print("WARNING could not bridge the south pole network to the north one", file=sys.stderr)

    # ---- external input risers and export drops ------------------------------------------
    inputs, outputs = [], []
    for ln in lanes:
        if ln.external:
            j = ln.index
            for yy in range(H - 1, row(j), -1):
                grid.belt_tile(x_start + j, yy, N)
            lane_tile(ln, x_start + j, E)
            inputs.append(Port("in", "belt", ln.item, "both", x_start + j, H - 1, N, ln.claimed))
    for ln in exported:
        d = drops[ln.index]
        lane_tile(ln, d, S)
        for yy in range(row(ln.index) + 1, H):
            grid.belt_tile(d, yy, S)
        outputs.append(Port("out", "belt", ln.item, "both", d, H - 1, S, ln.surplus))
    outputs.sort(key=lambda p: p.x)

    # ---- roboport grid --------------------------------------------------------------------
    n_rp = unpowered_rp = 0
    if rp:
        network = [i for i, e in enumerate(grid.ents) if e["name"].endswith("electric-pole")]   # connected poles
        W_now = max(tx for tx, _ in grid.occ) + 1
        spots = [(xl, yt) for yt in range(H - 4, -1, -rp) for xl in range(0, W_now, rp)]
        pole_ids = []
        for xl, yt in spots:                        # all roboports and their poles first (paths route around them)
            for tx in range(xl, xl + 4):
                for ty in range(yt, yt + 4):
                    grid._take((tx, ty), "roboport")
            grid.ents.append({"name": "roboport", "position": {"x": xl + 2, "y": yt + 2}, "direction": N})
            pole_ids.append(len(grid.ents))
            grid.place("medium-electric-pole", xl + 4, yt + 3)
            n_rp += 1
        for (xl, yt), pid in zip(spots, pole_ids):
            via = (xl + 4, B0 - 2) if xl < x_start + Ecount and yt + 3 >= B0 else None   # west of the riser wall: up past the bus first
            n_before = len(grid.ents)
            if power_path(pid, xl + 4, yt + 3, network, via=via):
                network.append(pid)
                network.extend(i for i in range(n_before, len(grid.ents)) if grid.ents[i]["name"].endswith("electric-pole"))
            else:
                unpowered_rp += 1
                print(f"WARNING roboport at ({xl}, {yt}) has no pole path to the network: {last_path[0]}", file=sys.stderr)

    # ---- lanes: duck under foreign tiles, then fill ----------------------------------------
    tiers = TIERS[TIERS.index(belt):]
    max_gap = MAX_GAP[tiers[-1]]
    ug_count, ug_tiers = 0, {}
    for ln in lanes:
        j, y = ln.index, row(ln.index)
        blocked = [x for x in range(ln.start, ln.end + 1) if (x, y) in grid.occ and (x, y) not in own[j]]
        runs = []
        for x in blocked:
            if runs and x - runs[-1][1] <= 2:
                runs[-1][1] = x
            else:
                runs.append([x, x])
        for a, b in runs:
            if b - a + 1 > max_gap:
                raise PackError(f"lane {j} {ln.item} must duck under columns {a}-{b} ({b - a + 1} tiles) "
                                f"but no underground spans more than {max_gap}")
            tier = next(t for t in tiers if MAX_GAP[t] >= b - a + 1)
            ug_name = UNDERGROUND[tier]
            ug_tiers[tier] = ug_tiers.get(tier, 0) + 1
            for xx, kind in ((a - 1, "input"), (b + 1, "output")):
                if (xx, y) in plain[j]:
                    e = next(e for e in grid.ents if e["position"] == {"x": xx + 0.5, "y": y + 0.5})
                    e["name"], e["type"], e["direction"] = ug_name, kind, E
                    grid.occ[(xx, y)] = e["name"]
                    plain[j].discard((xx, y))
                    continue
                if ln.start < xx < ln.end and (xx, y) not in grid.occ:
                    grid.place(ug_name, xx, y, E, type=kind)
                    continue
                held = grid.occ.get((xx, y))
                raise PackError(f"lane {j} {ln.item}: no free tile at column {xx} for an underground {kind} "
                                f"around columns {a}-{b} (tile holds {held}, own={(xx, y) in own[j]}; lane cols "
                                f"{ln.start}-{ln.end}, pushes {ln.pushes}, pulls {ln.pulls})")
            ug_count += 1
        for xx in range(ln.start, ln.end + 1):
            if (xx, y) not in grid.occ:
                grid.belt_tile(xx, y, E)

    Wc = max(tx for tx, _ in grid.occ) + 1
    duck_txt = ", ".join(f"{n} {t.replace('-transport-belt', '') or 'yellow'}" for t, n in ug_tiers.items())
    n_s = sum(1 for s in sides if s == "S")
    notes = [f"bus: {L} lanes, {belt}, rows {B0}-{B0 + L - 1}, chain spacing {spacing}, gap {gap}, {ug_count} lane ducks ({duck_txt}), "
             f"{n_mod - n_s} modules north / {n_s} south"
             + (f", {n_rp} roboports every {rp} tiles ({unpowered_rp} with no pole in reach)" if rp else "") + "; modules: "
             + ", ".join(f"{m.name}({s})" for m, s in zip(modules, sides))]
    for ln in lanes:
        kind = "external" if ln.external else ("export" if ln in exported else "internal")
        flow = ln.claimed if ln.external else ln.supply
        bal = "" if ln.external else f" (L {ln.left:.3g} R {ln.right:.3g}, claimed {ln.claimed:.3g})"
        notes.append(f"lane {ln.index} {ln.item} {kind} {flow:.3g}/{ln.cap:g}/s cols {ln.start}-{ln.end}{bal}")
    return Module(name=name, width=Wc, height=H, entities=grid.ents, inputs=inputs, outputs=outputs,
                  notes=notes, wires=wires)
