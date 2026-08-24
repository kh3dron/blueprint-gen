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

R_MAX = 5        # routing band rows per side, worst case (jog rows B0-2-k, k = 0..3, plus row B0-1
                 # for lane-0 branch curves). band_rows() takes the ports actually there instead
EPS = 1e-6
N, E, S, W = 0, 4, 8, 12
MACHINE_SIZE = {"assembling-machine-1": 3, "assembling-machine-2": 3, "assembling-machine-3": 3,
                "electric-furnace": 3, "chemical-plant": 3, "oil-refinery": 5}
UNDERGROUND = {"transport-belt": "underground-belt", "fast-transport-belt": "fast-underground-belt",
               "express-transport-belt": "express-underground-belt", "turbo-transport-belt": "turbo-underground-belt"}
SPLITTER = {"transport-belt": "splitter", "fast-transport-belt": "fast-splitter",
            "express-transport-belt": "express-splitter", "turbo-transport-belt": "turbo-splitter"}
POLE_REACH = {"small-electric-pole": 7.5, "medium-electric-pole": 9.0, "big-electric-pole": 30.0}
MAX_GAP = {"transport-belt": 4, "fast-transport-belt": 6, "express-transport-belt": 8, "turbo-transport-belt": 10}
TIERS = ["transport-belt", "fast-transport-belt", "express-transport-belt", "turbo-transport-belt"]
SEARCH = ((3, 2), (3, 3), (4, 3), (4, 4), (5, 4), (6, 5))   # (chain spacing, module gap) candidates
RISER_GAP = 3           # columns between the external input risers of a nested composite
PIPE_GAP = 9            # pipe-to-ground: max distance 10 -> 9 tiles between
PIPE_CAP = 1e9          # pipe throughput is not modelled
LANE_CAPACITY = {"transport-belt": 15.0, "fast-transport-belt": 30.0, "express-transport-belt": 45.0,
                 "turbo-transport-belt": 60.0}


class PackError(ValueError):
    pass


WARNINGS = []           # filled during compose(); the caller prints them grouped and keeps them in the notes


def warn(msg):
    WARNINGS.append(msg)


def progress(stage, ex):
    """Called when a (spacing, gap) candidate fails. Replaced by compose.py to fold it into its report."""
    print(f"{stage}: {ex}; retrying", file=sys.stderr)


class Lane:
    def __init__(self, index, item, external, cap, kind="belt"):
        self.index = index
        self.kind = kind
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
    """Tiles covered by an entity: machines MACHINE_SIZE^2, roboports 4x4, splitters 1x2/2x1, else 1x1."""
    x, y = e["position"]["x"], e["position"]["y"]
    if e["name"] in MACHINE_SIZE:
        n = MACHINE_SIZE[e["name"]]
        cx, cy = int(x - n / 2), int(y - n / 2)
        return [(cx + dx, cy + dy) for dx in range(n) for dy in range(n)]
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


def run_plan(x0, x1, busy, kind, belt):
    """Tiles for a straight run along one row from column x0 towards x1 (the turn at x1 is the caller's),
    ducking under every `busy` column on the way. [(name, column, direction, kw)] or None if it cannot
    be routed: a run must start on a free tile and have a free tile to surface on past each obstacle."""
    step = 1 if x1 > x0 else -1
    d = E if step > 0 else W
    back = (d + 8) % 16
    tiers = TIERS[TIERS.index(belt):]
    out, x = [], x0
    while x != x1:
        if x in busy:
            return None
        nxt = x + step
        if nxt == x1 or nxt not in busy:
            out.append((belt if kind == "belt" else "pipe", x, d, {}))
            x = nxt
            continue
        end = nxt                                        # run of busy columns: duck from x to end
        while end != x1 and end in busy:
            end += step
        if end == x1:
            return None
        span = abs(end - x) - 1
        if kind == "pipe":
            if span > PIPE_GAP:
                return None
            out.append(("pipe-to-ground", x, back, {}))          # opening back along the run
            out.append(("pipe-to-ground", end, d, {}))
        else:
            tier = next((t for t in tiers if MAX_GAP[t] >= span), None)
            if tier is None:
                return None
            out.append((UNDERGROUND[tier], x, d, {"type": "input"}))
            out.append((UNDERGROUND[tier], end, d, {"type": "output"}))
        x = end + step
    return out


def solo_items(modules, belt="transport-belt"):
    """item -> (producer module, output index, consumer module, input index) for every item carried by
    exactly one output port and one input port, the producer covering the consumer's rate, where a run
    coming from the west can actually reach that input port past the module's other port chains. Those
    can go straight from one module to the next along the row under them, with no bus lane at all."""
    prod, cons = {}, {}
    for mi, m in enumerate(modules):
        for oi, p in enumerate(m.outputs):
            prod.setdefault(p.item, []).append((mi, oi, p))
        for pi, p in enumerate(m.inputs):
            cons.setdefault(p.item, []).append((mi, pi, p))
    out = {}
    for item, ps in prod.items():
        cs = cons.get(item, [])
        if len(ps) != 1 or len(cs) != 1:
            continue
        (pm, oi, pp), (cm, pi, cp) = ps[0], cs[0]
        if pp.kind != cp.kind or pm == cm or pp.rate + EPS < cp.rate:
            continue
        m = modules[cm]
        busy = {p.x for q, p in enumerate(m.inputs) if q != pi} | {p.x for p in m.outputs}
        if run_plan(-1, cp.x, busy, cp.kind, belt) is None:      # blocked by its own neighbours
            continue
        out[item] = (pm, oi, cm, pi)
    return out


def allocate(modules, sides, belt, linked=()):
    """Assign every port to a lane. Returns (lanes, pull_lane, push_lane, warnings).
    pull_lane: (mi, pi) -> Lane.  push_lane: (mi, oi) -> (Lane, belt_lane) with belt_lane in {left, right}."""
    cap = LANE_CAPACITY[belt]
    half = cap / 2
    produced = {p.item for m in modules for p in m.outputs}
    lanes, pull_lane, push_lane, warnings = [], {}, {}, []

    def new_lane(item, external, kind="belt"):
        ln = Lane(len(lanes), item, external, PIPE_CAP if kind == "pipe" else cap, kind)
        lanes.append(ln)
        return ln

    for mi, m in enumerate(modules):
        for pi, p in enumerate(m.inputs):
            if ("in", mi, pi) in linked:
                continue                                  # fed straight from the module next door
            if p.kind == "pipe":
                cands = [ln for ln in lanes if ln.item == p.item and ln.kind == "pipe"]
                if not cands:
                    if p.item in produced:
                        raise ValueError(f"{m.name}: {p.item} is produced but no lane carries it yet; "
                                         f"order producers before consumers")
                    cands = [new_lane(p.item, True, "pipe")]
                ln = cands[0]
                if not ln.external and ln.surplus < p.rate - EPS:
                    warnings.append(f"WARNING {m.name}: {p.item} pipe needs {p.rate:.3g}/s, lane {ln.index} has "
                                    f"{max(ln.surplus, 0):.3g}/s unclaimed (short {p.rate - ln.surplus:.3g}/s)")
                ln.claimed += p.rate
                pull_lane[(mi, pi)] = ln
                continue
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
            if ("out", mi, oi) in linked:
                continue                                  # goes straight to the module next door
            if p.kind == "pipe":
                cands = [ln for ln in lanes if ln.item == p.item and ln.kind == "pipe" and not ln.external]
                ln = cands[0] if cands else new_lane(p.item, False, "pipe")
                ln.left += p.rate
                push_lane[(mi, oi)] = (ln, "left")
                continue
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


def compose(name, modules, belt="transport-belt", exports=None, roboport=None, two_sided=True, nested=False,
            direct=True):
    """Stitch modules (producers before consumers) over a bus; retries (spacing, gap) candidates until
    every lane can duck under its crossings. `nested` = this composite will itself be a module on
    another bus: its external input risers are spread RISER_GAP apart so the parent can bring a chain
    up to each of them, and it gets a pole on each end of its bottom edge so the parent's pole chain
    can reach its network. Returns a Module."""
    last = None
    for spacing, gap in SEARCH:
        WARNINGS.clear()                       # a failed candidate leaves nothing behind
        try:
            return _layout(name, modules, belt, set(exports or []), spacing, gap, roboport, two_sided,
                           nested, direct)
        except PackError as ex:
            last = ex
            progress(f"spacing {spacing} gap {gap}", ex)
    raise ValueError(f"bus does not pack with (spacing, gap) in {SEARCH}: {last}")


def _layout(name, modules, belt, exports, spacing, gap, rp=None, two_sided=True, nested=False, direct=True):
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

    def riser_columns(lns):
        cols, col, prev_pipe = {}, x_start, False
        for ln in lns:
            if not ln.external:
                continue
            if ln.kind == "pipe" and prev_pipe:
                col += 1                          # two pipe risers must not touch
            while forbidden(col) or (ln.kind == "pipe" and forbidden(col - 1) and prev_pipe):
                col += 1                          # keep out of roboport bands
            cols[ln.index] = col
            prev_pipe = ln.kind == "pipe"
            col += RISER_GAP if nested else 1     # nested: input ports far enough apart that a parent
        return cols, col - x_start                # bus can bring a chain up to each of them
    riser0, Espan = riser_columns(lanes0)
    Ecount = Espan
    # item -> the riser column a pull for it has to stay east of. North modules may start over the
    # riser wall (risers only run below the bus); south modules share those rows, so they may not.
    riser_x, riser_lane, lane_idx = {}, {}, {}
    for ln in lanes0:
        lane_idx[ln.item] = max(lane_idx.get(ln.item, -1), ln.index)   # deepest lane the item may use
        if ln.external:
            riser_x[ln.item] = max(riser_x.get(ln.item, -1), riser0[ln.index])
            riser_lane[riser0[ln.index]] = ln.index                    # column -> the lane rising there
    deep = max(lane_idx.values(), default=0) + 1                       # deeper than every lane
    # north modules may sit over the riser wall (risers only run below the bus); south modules share
    # those rows, so they start east of it. Sides are dealt on progress, not on absolute column.
    # a nested composite spreads its risers RISER_GAP apart, which leaves the lane rows under the wall
    # too crowded for a lane to duck through, so there its modules start east of the wall as well
    start = {"N": x_start + (Espan + gap if nested else 0), "S": x_start + Espan + gap}
    cursor = dict(start)
    reserved = set()                   # bus columns claimed by placed modules (both sides)
    solo = solo_items(modules, belt) if direct else {}
    feeder = {}                        # consumer module -> producers it could be fed directly by,
    for pm, _, cm, pi in sorted(solo.values(), key=lambda v: modules[v[2]].inputs[v[3]].x):
        feeder.setdefault(cm, []).append(pm)      # westmost port first: the one a link can reach
    last_on = {"N": None, "S": None}   # last module placed on each side
    for mi, m in enumerate(modules):
        side = "N" if (not two_sided or m.no_mirror
                       or cursor["N"] - start["N"] <= cursor["S"] - start["S"]) else "S"
        for pm in feeder.get(mi, []):  # follow a producer that is still the last module on its side,
            if last_on[sides[pm]] == pm and not m.no_mirror:   # so the two end up next to each other
                side = sides[pm]
                break
        x = cursor[side]
        for p in m.inputs:
            if p.item in produced_at:                      # a linked item needs no push column, just
                x = max(x, produced_at[p.item] + (1 if p.item in solo else 3))
            elif p.item in riser_x:
                x = max(x, riser_x[p.item] + 2 - p.x)      # its pull must sit east of the riser
        ext = extent_of(m)
        if rp and ext + 1 > rp - 6:
            raise ValueError(f"{m.name} is {ext} columns wide; only {rp - 7} fit between roboport bands {rp} apart")

        def bus_cols(x):
            cols = set()                       # ports of a solo item are left out: they are likely to
            for p in m.outputs:                # be linked, and then they claim no bus column at all
                if p.item in solo:
                    continue
                if p.kind == "pipe":
                    cols.update(range(x + p.x - 1, x + p.x + 2))                   # pipe chain and both neighbours
                else:
                    cols.update(range(x + p.x, x + p.x + 3))                       # push, merge splitter, sideload
            belt_ports = [p for p in m.inputs if p.kind == "belt" and p.item not in solo]
            for p, (first, k) in zip(belt_ports, port_groups(belt_ports)):
                cols.update((x + first + spacing * k - 1, x + first + spacing * k))   # splitter + nominal chain
            for p in m.inputs:
                if p.kind == "pipe" and p.item not in solo:
                    cols.update(range(x + p.x - 1, x + p.x + 2))
            return cols
        def over_riser(x):
            """True if a chain of this module would run down a column where a lane above it rises."""
            for p in m.inputs + m.outputs:
                if p.item in solo:
                    continue            # likely linked: no chain at all
                idx = lane_idx.get(p.item, deep) if p in m.inputs else deep
                cols = ([x + p.x] if p.kind == "pipe" else
                        list(range(x + p.x, x + p.x + 3)) if p in m.outputs else [x + p.x])
                if p.kind == "belt" and p in m.inputs:
                    first, k = dict(zip([id(q) for q in belt_in], port_groups(belt_in)))[id(p)]
                    cols += [x + first + spacing * k - 1, x + first + spacing * k]
                # the column itself and its neighbours: a lane ducking under this chain needs a free
                # tile on each side of it, and a riser column is not free
                if any(riser_lane.get(c + d, deep) < idx for c in cols for d in (-1, 0, 1)):
                    return True
            return False

        belt_in = [p for p in m.inputs if p.kind == "belt" and p.item not in solo]
        while (any(forbidden(c) for c in range(x, x + ext + 1)) or bus_cols(x) & reserved
               or over_riser(x)):
            x += 1                      # roboport band, a bus column already used by the other side,
                                        # or a column a lane above this module rises in
        reserved.update(bus_cols(x))
        sides[mi], xs[mi] = side, x
        last_on[side] = mi
        for p in m.outputs:
            produced_at[p.item] = max(produced_at.get(p.item, -1), x + p.x)
        cursor[side] = x + ext + gap

    # ---- direct links: producer and consumer next to each other on the same side ----------
    links, linked, taken_link = [], set(), {"N": set(), "S": set()}
    for item, (pm, oi, cm, pi) in sorted(solo.items(), key=lambda kv: xs[kv[1][0]]):
        side = sides[pm]
        if sides[cm] != side or xs[pm] >= xs[cm]:
            continue
        if any(sides[i] == side and xs[pm] < xs[i] < xs[cm] for i in range(n_mod)):
            continue                                     # not next door
        x0 = xs[pm] + modules[pm].outputs[oi].x
        x1 = xs[cm] + modules[cm].inputs[pi].x
        busy = set(taken_link[side])
        for mj, port, io in ((pm, "outputs", "out"), (pm, "inputs", "in"), (cm, "outputs", "out"), (cm, "inputs", "in")):
            for q, p in enumerate(getattr(modules[mj], port)):
                if (io, mj, q) not in linked and (mj, q, io) != (pm, oi, "out") and (mj, q, io) != (cm, pi, "in"):
                    busy.add(xs[mj] + p.x)               # another port's chain comes down this column
        busy |= {c for c in range(x0 + 1, x1) if forbidden(c)}
        kind = modules[pm].outputs[oi].kind
        run = run_plan(x0, x1, busy, kind, belt)
        if run is None:
            continue
        links.append((item, pm, oi, cm, pi, side, x0, x1, run, kind))
        linked |= {("out", pm, oi), ("in", cm, pi)}
        taken_link[side] |= set(range(x0, x1 + 1))
    lanes, pull_lane, push_lane, warnings = allocate(modules, sides, belt, linked)
    for w in warnings:
        warn(w)
    L = len(lanes)
    riser_col, Espan = riser_columns(lanes)
    consumed = {p.item for m in modules for p in m.inputs}
    exported = [ln for ln in lanes if not ln.external and ln.surplus > EPS
                and (ln.item not in consumed or ln.item in exports)]
    has_south = any(s == "S" for s in sides)

    # ---- rows ---------------------------------------------------------------------------
    link_n = any(lk[5] == "N" for lk in links)
    link_s = any(lk[5] == "S" for lk in links)

    def band_rows(side):
        """Rows the routing band needs on `side`: one jog row per belt input port of the widest port
        group there, plus the branch-curve row. A side of 2-port modules does not need the 5 rows a
        4-port template would."""
        k = 0
        for mi, m in enumerate(modules):
            if sides[mi] != side:
                continue
            ports = [p for pi, p in enumerate(m.inputs) if p.kind == "belt" and ("in", mi, pi) not in linked]
            for _, kk in port_groups(ports):
                k = max(k, kk)
        return k + 2

    RN, RS = band_rows("N"), band_rows("S")
    by = max([m.height for m, s in zip(modules, sides) if s == "N"] + [1]) - 1
    B0 = by + RN + 1 + link_n                  # row by+1 is the link row, clear of every jog row
    lane_rows, yy_ = [], B0
    for i, ln in enumerate(lanes):
        if ln.kind == "pipe" and i > 0 and lanes[i - 1].kind == "pipe":
            yy_ += 1                               # blank row: adjacent pipe lanes would connect
        lane_rows.append(yy_)
        yy_ += 1
    row = lambda j: lane_rows[j]        # noqa: E731
    spare = yy_
    if has_south:
        bys = spare + RS + 1 + link_s
        H = bys + max(m.height for m, s in zip(modules, sides) if s == "S")
    else:
        bys = None
        H = spare + 1
    x_max = max(xs[i] + extent_of(modules[i]) - 1 for i in range(n_mod))
    grid = Grid(belt)
    wires = []
    own = {ln.index: set() for ln in lanes}
    plain = {ln.index: set() for ln in lanes}

    def lane_tile(ln, x, dirn):
        own[ln.index].add((x, row(ln.index)))
        if ln.kind == "pipe":
            return grid.place("pipe", x, row(ln.index))
        return grid.belt_tile(x, row(ln.index), dirn)

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
        if B0 <= cy < spare:                       # on a lane row: leave room for the lane to duck under
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
                        warn(f"WARNING gap pole at {gx} cannot reach {ma.name} pole ({best[0]:.1f} tiles)")
                else:
                    wires.append([prev + 1, 5, gid + 1, 5])
                best = nearest_pole(mb, xb, gx, prow, n_module_ents)
                if best and best[0] <= reach:
                    wires.append([gid + 1, 5, best[1] + 1, 5])
                    break
                if gx + int(reach) >= xb + mb.width:
                    warn(f"WARNING pole chain at {gx} cannot reach {mb.name} pole")
                    break
                prev = gid
                gx += int(reach)
    # ---- bus columns for every port ----------------------------------------------------
    pulls, pushes = [], []
    for mi, (m, x0, y0, side) in enumerate(placements):
        belt_ports = [p for pi, p in enumerate(m.inputs) if p.kind == "belt" and ("in", mi, pi) not in linked]
        groups = dict(zip([id(p) for p in belt_ports], port_groups(belt_ports)))
        for pi, p in enumerate(m.inputs):
            if ("in", mi, pi) in linked:
                continue                                   # fed by a direct link, no bus column
            if p.kind == "pipe":
                pulls.append((m, pull_lane[(mi, pi)], x0 + p.x, x0 + p.x, 0, p, side))
            else:
                first, k = groups[id(p)]
                pulls.append((m, pull_lane[(mi, pi)], x0 + first + spacing * k, x0 + p.x, k, p, side))
        for oi, p in enumerate(m.outputs):
            if ("out", mi, oi) in linked:
                continue
            ln, bl = push_lane[(mi, oi)]
            ln.pushes.append(x0 + p.x)
            pushes.append((m, p, ln, x0 + p.x, bl, side))

    for ln in lanes:
        ln.start = riser_col[ln.index] if ln.external else min(ln.pushes)
    drops = {}
    d, prev_pipe = x_max + 3, False
    for ln in sorted(exported, key=lambda ln: -ln.index):
        if ln.kind == "pipe" and prev_pipe:
            d += 1                                 # two pipe drops must not touch
        while forbidden(d):
            d += 1
        drops[ln.index] = d
        prev_pipe = ln.kind == "pipe"
        d += 1

    # ---- pushes (first, so pull chains route around them) -------------------------------
    for m, p, ln, col, bl, side in pushes:
      try:
        j = ln.index
        if p.kind == "pipe":
            rows_ = range(by + 1, row(j)) if side == "N" else range(bys - 1, row(j), -1)
            for yy in rows_:
                grid.place("pipe", col, yy)
            lane_tile(ln, col, E)                                            # tee (or lane start)
            continue
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
        raise PackError(f"push {m.name} {p.item} col {col} side {side} lane {ln.index} "
                        f"({bl}, start {ln.start}): {ex}")

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

    def jog(bc, px, r, into):
        """Horizontal run of a pull chain from bus column `bc` to port column `px` on jog row `r`,
        ending with a belt into the module (`into` = N or S). Anything already on the row is ducked
        under with an underground pair: the module's own push chain, or a pipe chain of a neighbouring
        port (vertical chains never tunnel, so it is the horizontal run that goes under). The tile the
        chain turns on and the tile it enters the module on must be free."""
        step = 1 if px > bc else -1
        d = E if step > 0 else W
        tiers_ = TIERS[TIERS.index(belt):]
        x = bc
        while x != px:
            if (x, r) in grid.occ:
                raise ValueError(f"jog row {r} blocked at column {x} by {grid.occ[(x, r)]}")
            nxt = x + step
            if nxt == px or (nxt, r) not in grid.occ:
                grid.belt_tile(x, r, d)
                x = nxt
                continue
            end = nxt                                    # run of foreign tiles: duck from x to `end`
            while end != px and (end, r) in grid.occ:
                end += step
            if end == px:
                raise ValueError(f"jog row {r}: {grid.occ[(nxt, r)]} at column {nxt} reaches the port column")
            gap_ = abs(end - x) - 1
            tier = next((t for t in tiers_ if MAX_GAP[t] >= gap_), None)
            if tier is None:
                raise ValueError(f"jog row {r} must duck under {gap_} tiles from column {x}, "
                                 f"more than any underground spans ({MAX_GAP[tiers_[-1]]})")
            grid.place(UNDERGROUND[tier], x, r, d, type="input")
            grid.place(UNDERGROUND[tier], end, r, d, type="output")
            x = end + step
        grid.belt_tile(px, r, into)

    def place_pull(ln, bc, px, k, whole, side):
        j = ln.index
        if ln.kind == "pipe":
            lane_tile(ln, bc, E)                                             # tee
            rows_ = range(row(j) - 1, by, -1) if side == "N" else range(row(j) + 1, bys)
            for yy in rows_:
                grid.place("pipe", bc, yy)
            return
        # duck feasibility: the lane must be able to surface just before this pull's splitter / turn,
        # and this chain must not sit right beside another lane's splitter or turn on any row it crosses
        feed = bc - 1 if whole else bc - 2
        if foreign(feed, row(j), j):
            raise ValueError("lane cannot surface before the pull")
        crossed = range(B0, row(j)) if side == "N" else range(row(j) + 1, spare)
        for y in crossed:
            if y not in lane_of_row:
                continue
            o = lanes[lane_of_row[y]]
            if o.start < bc < o.end and (structural(bc - 1, y) or structural(bc + 1, y)):
                raise ValueError("chain would block a neighbouring lane structure")
        if side == "N":
            r = B0 - 2 - k
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
                jog(bc, px, r, N)
            for yy in range(r - 1, by, -1):
                grid.belt_tile(px, yy, N)
        else:
            r = spare + 2 + k
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
                jog(bc, px, r, S)
            for yy in range(r + 1, bys):
                grid.belt_tile(px, yy, S)

    pulls.sort(key=lambda t: t[5].kind != "pipe")   # a pipe chain is a straight pipe at the port
                                                   # column with no alternative, so it goes down first
    for m, ln, bc0, px, k, p, side in pulls:
        if bc0 - 1 <= ln.start:
            raise ValueError(f"{m.name}: input {p.item} at column {px} is west of lane {ln.index} start {ln.start}; "
                             f"order producers before consumers")
        whole = ln.index not in drops and bc0 == last_bc[ln.index] and ln.end == bc0
        placed = False
        reasons = []
        cands = [bc0] if p.kind == "pipe" else list(range(bc0, bc0 + spacing))
        if p.kind != "pipe":
            # fall back west, toward the port column: a nominal column east of the module's own push
            # column cannot be reached, because the jog row would have to cross that push chain.
            # A whole-lane pull ends the lane where it turns, so it may not move west of anything
            # the lane still has to reach (its merges and the pulls already placed on it).
            floor = px if not whole else max([px, ln.start + 1] + [c + 2 for c in ln.pushes if c > ln.start] + ln.pulls)
            cands += list(range(bc0 - 1, floor - 1, -1))
        for bc in cands:
            if forbidden(bc) or (p.kind != "pipe" and forbidden(bc - 1)):
                reasons.append(f"{bc}: roboport band")
                continue
            if bc - 1 <= ln.start:
                reasons.append(f"{bc}: west of lane {ln.index} start {ln.start}")
                continue
            grid.begin()
            try:
                place_pull(ln, bc, px, k, whole, side)
            except ValueError as ex:
                reasons.append(f"{bc}: {ex}")
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
            raise PackError(f"{m.name}: no bus column for {p.item} in {min(cands)}..{max(cands)} "
                            f"({'; '.join(reasons)})")

    # ---- direct links: one row under the modules, ducking under the chains that cross it ----
    for item, pm, oi, cm, pi, side, x0, x1, run, kind in links:
        y = by + 1 if side == "N" else bys - 1
        try:
            for nm, xx, dirn, kw in run:
                grid.place(nm, xx, y, dirn, **kw)
            grid.place(belt if kind == "belt" else "pipe", x1, y, N if side == "N" else S)
        except ValueError as ex:
            raise PackError(f"direct link {item} {x0}->{x1} on row {y}: {ex}")

    # ---- power bridge south -> north (after the chains, so it routes around them) ----------
    if has_south:
        north_ids = [i for i, e in enumerate(grid.ents) if e["name"].endswith("electric-pole") and e["position"]["y"] < B0]
        south = [(i, e) for i, e in enumerate(grid.ents) if e["name"].endswith("electric-pole") and e["position"]["y"] > spare]
        if south and north_ids:
            i, e = min(south, key=lambda t: (t[1]["position"]["y"], t[1]["position"]["x"]))
            if not power_path(i, int(e["position"]["x"] - 0.5), int(e["position"]["y"] - 0.5), north_ids):
                warn("WARNING could not bridge the south pole network to the north one")

    # ---- external input risers and export drops ------------------------------------------
    inputs, outputs = [], []
    for ln in lanes:
        if ln.external:
            j, rc = ln.index, riser_col[ln.index]
            for yy in range(H - 1, row(j), -1):
                grid.place("pipe", rc, yy) if ln.kind == "pipe" else grid.belt_tile(rc, yy, N)
            lane_tile(ln, rc, E)
            inputs.append(Port("in", ln.kind, ln.item, "both", rc, H - 1, N, ln.claimed))
    for ln in exported:
        d = drops[ln.index]
        lane_tile(ln, d, S)
        for yy in range(row(ln.index) + 1, H):
            grid.place("pipe", d, yy) if ln.kind == "pipe" else grid.belt_tile(d, yy, S)
        outputs.append(Port("out", ln.kind, ln.item, "both", d, H - 1, S, ln.surplus))
    outputs.sort(key=lambda p: p.x)

    # ---- roboport grid --------------------------------------------------------------------
    n_rp = unpowered_rp = skipped_rp = 0
    if rp:
        network = [i for i, e in enumerate(grid.ents) if e["name"].endswith("electric-pole")]   # connected poles
        W_now = max(tx for tx, _ in grid.occ) + 1
        rows = list(range(H - 4, -1, -rp))
        chain_rows = [r for r in (by, bys) if r is not None]     # module pole chains run right across
        dy = next((d for d in range(12)
                   if all(not (yt - d <= pr <= yt - d + 3) for yt in rows for pr in chain_rows)), 0)
        spots = [(xl, yt - dy) for yt in rows if yt - dy >= 0 for xl in range(0, W_now, rp)]
        pole_ids = []
        placed_spots = []
        for xl, yt in spots:                        # all roboports and their poles first (paths route around them)
            tiles = [(tx, ty) for tx in range(xl, xl + 4) for ty in range(yt, yt + 4)] + [(xl + 4, yt + 3)]
            held = next(((t, grid.occ[t]) for t in tiles if t in grid.occ), None)
            if held:                                # a pole chain or power path got there first
                warn(f"WARNING roboport at ({xl}, {yt}) skipped: tile {held[0]} holds {held[1]}")
                skipped_rp += 1
                continue
            for t in tiles[:16]:
                grid._take(t, "roboport")
            grid.ents.append({"name": "roboport", "position": {"x": xl + 2, "y": yt + 2}, "direction": N})
            pole_ids.append(len(grid.ents))
            grid.place("medium-electric-pole", xl + 4, yt + 3)
            placed_spots.append((xl, yt))
            n_rp += 1
        for (xl, yt), pid in zip(placed_spots, pole_ids):
            via = (xl + 4, B0 - 2) if xl < x_start + Ecount and yt + 3 >= B0 else None   # west of the riser wall: up past the bus first
            n_before = len(grid.ents)
            if power_path(pid, xl + 4, yt + 3, network, via=via):
                network.append(pid)
                network.extend(i for i in range(n_before, len(grid.ents)) if grid.ents[i]["name"].endswith("electric-pole"))
            else:
                unpowered_rp += 1
                warn(f"WARNING roboport at ({xl}, {yt}) has no pole path to the network: {last_path[0]}")

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
            if ln.kind == "pipe":
                if b - a + 1 > PIPE_GAP:
                    raise PackError(f"lane {j} {ln.item} (pipe) must duck under columns {a}-{b} ({b - a + 1} tiles) "
                                    f"but pipe-to-ground spans at most {PIPE_GAP}")
                ug_tiers["pipe"] = ug_tiers.get("pipe", 0) + 1
                for xx, dirn in ((a - 1, W), (b + 1, E)):        # opening away from the run, tunnel under it
                    if not ln.start < xx < ln.end or (xx, y) in grid.occ:
                        raise PackError(f"lane {j} {ln.item} (pipe): no free tile at column {xx} to tunnel "
                                        f"around columns {a}-{b} (holds {grid.occ.get((xx, y))})")
                    grid.place("pipe-to-ground", xx, y, dirn)
                ug_count += 1
                continue
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
                grid.place("pipe", xx, y) if ln.kind == "pipe" else grid.belt_tile(xx, y, E)

    if nested:
        # bottom-edge poles, so a parent bus can reach this composite's network from its pole chain
        net = [i for i, e in enumerate(grid.ents) if e["name"].endswith("electric-pole")]
        W_now = max(tx for tx, _ in grid.occ) + 1
        free = [x for x in range(W_now) if (x, H - 1) not in grid.occ]
        for cands in (free[:12], free[-12:][::-1]):        # one pole near each end of the bottom edge
            for xx in cands:
                pid, w0 = len(grid.ents), len(wires)
                grid.begin()
                grid.place("medium-electric-pole", xx, H - 1)
                via = (xx, B0 - 2) if xx < x_start + Ecount else None    # west of the riser wall
                if power_path(pid, xx, H - 1, net, via=via):
                    grid.commit()
                    net.append(pid)
                    break
                grid.rollback()
                del wires[w0:]                                           # drop the failed path's wires
            else:
                warn(f"WARNING no bottom-edge pole could reach the network from columns "
                     f"{cands[0]}-{cands[-1]}: {last_path[0]}")

    Wc = max(tx for tx, _ in grid.occ) + 1
    duck_txt = ", ".join(f"{n} {t.replace('-transport-belt', '') or 'yellow'}" for t, n in ug_tiers.items())
    pipes = sum(1 for ln in lanes if ln.kind == "pipe")
    n_s = sum(1 for s in sides if s == "S")
    notes = [f"bus: {L} lanes ({pipes} pipe), {belt}, rows {B0}-{spare - 1}, chain spacing {spacing}, gap {gap}, "
             f"{ug_count} lane ducks ({duck_txt}), {len(links)} direct links, "
             f"{n_mod - n_s} modules north / {n_s} south"
             + (f", {n_rp} roboports every {rp} tiles ({unpowered_rp} with no pole in reach, "
                f"{skipped_rp} spots skipped)" if rp else ""),
             "modules: " + ", ".join(f"{m.name}({s})" for m, s in zip(modules, sides))]
    for ln in lanes:
        kind = "external" if ln.external else ("export" if ln in exported else "internal")
        flow = ln.claimed if ln.external else ln.supply
        bal = "" if ln.external or ln.kind == "pipe" else f" (L {ln.left:.3g} R {ln.right:.3g}, claimed {ln.claimed:.3g})"
        cap = "pipe" if ln.kind == "pipe" else f"{ln.cap:g}/s"
        notes.append(f"lane {ln.index} {ln.item} {ln.kind} {kind} {flow:.3g}/{cap} cols {ln.start}-{ln.end}{bal}")
    notes += WARNINGS
    out = Module(name=name, width=Wc, height=H, entities=grid.ents, inputs=inputs, outputs=outputs,
                 notes=notes, wires=wires, no_mirror=any(m.no_mirror for m in modules))
    # not part of the model: what the CLI compares layouts by and what bench.py records
    out.links = len(links)
    out.stats = {"lanes": L, "pipe_lanes": pipes, "links": len(links), "modules": n_mod,
                 "north": n_mod - n_s, "south": n_s, "ducks": ug_count, "roboports": n_rp,
                 "spacing": spacing, "gap": gap}
    return out
