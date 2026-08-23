"""Blueprint modules: a blueprint plus typed INPUT / OUTPUT ports.

A port is one lane of one belt tile (or one pipe tile) on the module's edge, carrying one item at
a rate. Module-local coordinates: tile (0, 0) is the top-left tile; entity positions follow the
Factorio convention (center of the footprint). Ports are listed left to right.

Serialization:
  Module JSON (.module.json): {"name", "width", "height", "blueprint": <vanilla blueprint object>,
                               "inputs": [Port...], "outputs": [Port...]}
  Blueprint string: vanilla; ports are written into the blueprint `description` as one
  `PORT ...` line each, so the string survives a round trip through the game.
"""
import base64
import json
import re
import zlib
from dataclasses import dataclass, asdict, field

DIR_NAME = {0: "N", 4: "E", 8: "S", 12: "W"}
DIR_CODE = {v: k for k, v in DIR_NAME.items()}
LANES = ("left", "right", "both")

PORT_RE = re.compile(
    r"^PORT (?P<io>IN|OUT) (?P<kind>belt|pipe) (?P<item>[a-z0-9-]+) (?P<lane>left|right|both) "
    r"\((?P<x>-?\d+),(?P<y>-?\d+)\) (?P<dir>[NESW]) (?P<rate>[0-9.]+)/s$")


@dataclass
class Port:
    io: str          # "in" | "out"
    kind: str        # "belt" | "pipe"
    item: str
    lane: str        # "left" | "right" | "both" (pipes: "both")
    x: int           # tile column
    y: int           # tile row
    direction: int   # 0 N, 4 E, 8 S, 12 W: direction of flow at the port tile
    rate: float      # items/s (fluids: units/s)

    def line(self):
        return (f"PORT {self.io.upper()} {self.kind} {self.item} {self.lane} "
                f"({self.x},{self.y}) {DIR_NAME[self.direction]} {self.rate:g}/s")

    @classmethod
    def parse(cls, line):
        m = PORT_RE.match(line.strip())
        if not m:
            return None
        return cls(io=m["io"].lower(), kind=m["kind"], item=m["item"], lane=m["lane"],
                   x=int(m["x"]), y=int(m["y"]), direction=DIR_CODE[m["dir"]], rate=float(m["rate"]))

    def compatible(self, other):
        """True if self (an OUT port) can feed other (an IN port)."""
        return (self.io == "out" and other.io == "in" and self.kind == other.kind
                and self.item == other.item and (other.lane == "both" or self.lane == other.lane))


@dataclass
class Module:
    name: str
    width: int
    height: int
    entities: list = field(default_factory=list)
    tiles: list = field(default_factory=list)
    inputs: list = field(default_factory=list)   # [Port]
    outputs: list = field(default_factory=list)  # [Port]
    notes: list = field(default_factory=list)    # free-text lines kept in the description
    wires: list = field(default_factory=list)    # [[e1, c1, e2, c2]] 1-based entity numbers
    no_mirror: bool = False                      # vertical mirroring would break it (fluid boxes)

    # ---- blueprint JSON ----------------------------------------------------------------
    def blueprint(self):
        """Vanilla blueprint object. Entities are shifted so module tile (0,0) is at world (0,0)."""
        notes = list(self.notes)
        if self.no_mirror and not any(n.startswith("NO-MIRROR") for n in notes):
            notes.append("NO-MIRROR vertical flip would swap fluid boxes")
        desc = "\n".join([f"SIZE {self.width}x{self.height}"]
                         + [p.line() for p in self.inputs + self.outputs] + notes)
        return {
            "item": "blueprint",
            "label": self.name,
            "description": desc,
            "version": 562949956239360,
            "entities": [dict(e, entity_number=i + 1) for i, e in enumerate(self.entities)],
            "tiles": list(self.tiles),
            "icons": self._icons(),
            "wires": list(self.wires),
        }

    def _icons(self):
        items = []
        for p in self.outputs + self.inputs:
            if p.item not in items:
                items.append(p.item)
        return [{"index": i + 1, "signal": {"name": it}} for i, it in enumerate(items[:4])]

    def to_string(self):
        payload = json.dumps({"blueprint": self.blueprint()}, separators=(",", ":")).encode()
        return "0" + base64.b64encode(zlib.compress(payload, 9)).decode()

    def render_json(self):
        """Blueprint JSON with a non-vanilla `ports` key for 02_blueprint_visualizer/render.py."""
        bp = self.blueprint()
        bp["ports"] = [asdict(p) for p in self.inputs + self.outputs]
        return {"blueprint": bp}

    # ---- module JSON -------------------------------------------------------------------
    def to_json(self):
        return {
            "name": self.name, "width": self.width, "height": self.height,
            "inputs": [asdict(p) for p in self.inputs], "outputs": [asdict(p) for p in self.outputs],
            "notes": self.notes, "entities": self.entities, "tiles": self.tiles, "wires": self.wires,
            "no_mirror": self.no_mirror,
        }

    @classmethod
    def from_json(cls, d):
        return cls(name=d["name"], width=d["width"], height=d["height"],
                   entities=d.get("entities", []), tiles=d.get("tiles", []),
                   inputs=[Port(**p) for p in d.get("inputs", [])],
                   outputs=[Port(**p) for p in d.get("outputs", [])],
                   notes=d.get("notes", []), wires=d.get("wires", []),
                   no_mirror=d.get("no_mirror", False))

    def save(self, path):
        with open(path, "w") as f:
            json.dump(self.to_json(), f, indent=1)

    @classmethod
    def load(cls, path):
        with open(path) as f:
            return cls.from_json(json.load(f))

    @classmethod
    def from_string(cls, s):
        """Rebuild a Module from a vanilla blueprint string whose description carries PORT lines."""
        s = s.strip()
        obj = json.loads(s) if s.startswith("{") else json.loads(zlib.decompress(base64.b64decode(s[1:])))
        bp = obj["blueprint"]
        ports, notes = [], []
        width = height = None
        for line in bp.get("description", "").splitlines():
            m = re.match(r"^SIZE (\d+)x(\d+)$", line.strip())
            if m:
                width, height = int(m[1]), int(m[2])
                continue
            p = Port.parse(line)
            (ports if p else notes).append(p or line)
        ents = bp.get("entities", [])
        tiles = bp.get("tiles", [])
        if width is None:  # no SIZE line: estimate from entity centers (undercounts by up to 1 tile per side)
            xs = [e["position"]["x"] for e in ents] + [t["position"]["x"] + 0.5 for t in tiles]
            ys = [e["position"]["y"] for e in ents] + [t["position"]["y"] + 0.5 for t in tiles]
            width = int(max(xs) - min(xs)) + 1 if xs else 0
            height = int(max(ys) - min(ys)) + 1 if ys else 0
        return cls(name=bp.get("label", "module"), width=width, height=height, entities=ents,
                   tiles=tiles, inputs=[p for p in ports if p.io == "in"],
                   outputs=[p for p in ports if p.io == "out"], notes=notes, wires=bp.get("wires", []),
                   no_mirror=any(n.startswith("NO-MIRROR") for n in notes))

    # ---- checks ------------------------------------------------------------------------
    def check(self):
        """Return a list of problems (empty list = ok)."""
        problems = []
        occupied = {}
        for e in self.entities:
            key = (e["position"]["x"], e["position"]["y"])
            if key in occupied and occupied[key] != e["name"]:
                problems.append(f"two entities at {key}: {occupied[key]}, {e['name']}")
            occupied[key] = e["name"]
        for w in self.wires:
            if not (1 <= w[0] <= len(self.entities) and 1 <= w[2] <= len(self.entities)):
                problems.append(f"wire {w} outside 1..{len(self.entities)}")
        for p in self.inputs + self.outputs:
            if not (0 <= p.x < self.width and 0 <= p.y < self.height):
                problems.append(f"port outside module: {p.line()}")
            if p.kind == "belt" and (p.x + 0.5, p.y + 0.5) not in occupied:
                problems.append(f"no entity under belt port: {p.line()}")
        return problems


FLIP_NS = {0: 8, 8: 0}


def mirror(mod):
    """Vertical mirror of a module: row y -> height-1-y. Belt/inserter/underground directions N<->S;
    ports move to the opposite edge with flipped flow direction. Entity order and wires are kept."""
    if mod.no_mirror:
        raise ValueError(f"{mod.name}: marked no_mirror (fluid boxes would swap), cannot be mirrored")
    H = mod.height
    ents = []
    for e in mod.entities:
        e = dict(e)
        e["position"] = {"x": e["position"]["x"], "y": H - e["position"]["y"]}
        d = e.get("direction", 0)
        if e["name"].endswith("splitter"):
            pass                                           # east/west splitters are symmetric
        else:
            e["direction"] = FLIP_NS.get(d, d)
        ents.append(e)

    def flip_port(p):
        return Port(p.io, p.kind, p.item, p.lane, p.x, H - 1 - p.y, FLIP_NS.get(p.direction, p.direction), p.rate)
    return Module(name=mod.name, width=mod.width, height=H, entities=ents, tiles=list(mod.tiles),
                  inputs=[flip_port(p) for p in mod.inputs], outputs=[flip_port(p) for p in mod.outputs],
                  notes=list(mod.notes), wires=[list(w) for w in mod.wires])


def port_summary(mod):
    """One row per (io, kind, item): how many ports carry it, their total rate, their column span.
    port_table() prints every port instead."""
    rows, order = {}, []
    for p in mod.inputs + mod.outputs:
        key = (p.io, p.kind, p.item)
        if key not in rows:
            rows[key] = [0, 0.0, p.x, p.x]
            order.append(key)
        r = rows[key]
        r[0] += 1
        r[1] += p.rate
        r[2], r[3] = min(r[2], p.x), max(r[3], p.x)
    out = [f"{'IO':<4}{'KIND':<6}{'ITEM':<26}{'PORTS':>6}{'RATE':>12}  COLUMNS"]
    for io, kind, item in order:
        n, rate, x0, x1 = rows[(io, kind, item)]
        span = f"{x0}" if x0 == x1 else f"{x0}-{x1}"
        out.append(f"{io.upper():<4}{kind:<6}{item:<26}{n:>6}{rate:>10.4g}/s  {span}")
    return "\n".join(out)


def port_table(mod):
    rows = [f"{'IO':<4}{'KIND':<6}{'ITEM':<24}{'LANE':<7}{'TILE':<9}{'DIR':<5}RATE"]
    for p in mod.inputs + mod.outputs:
        rows.append(f"{p.io.upper():<4}{p.kind:<6}{p.item:<24}{p.lane:<7}({p.x},{p.y})"
                    f"{'':<{max(1, 9 - len(f'({p.x},{p.y})'))}}{DIR_NAME[p.direction]:<5}{p.rate:g}/s")
    return "\n".join(rows)
