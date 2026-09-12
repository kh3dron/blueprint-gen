"""Route staged belt circuits through real machine ports on the surveyed grid.

Each item has one directed belt visiting its producer and consumer ports. Other
items cross below it through paired underground belts. Machines and future ports
are reserved before routing, so later stages cannot overwrite earlier routes.
"""
from collections import defaultdict
from copy import deepcopy
import heapq
import math

from .planning_world import PlanningWorld
from .science_layout import _cells

VECTORS = {0: (0, -1), 4: (1, 0), 8: (0, 1), 12: (-1, 0)}
DIRECTION = {v: k for k, v in VECTORS.items()}
SCIENCE = {"automation-science-pack", "logistic-science-pack"}


def point(entity):
    return entity["position"]["x"], entity["position"]["y"]


def inserter_count(plan):
    count = 1 + 2 * len(SCIENCE)  # Boiler, lab inputs and collection outputs.
    for e in plan["stages"][-1]["placements"]:
        if e["name"] == "burner-mining-drill":
            count += 1
        elif e.get("recipe"):
            node = plan["final_graph"]["nodes"][e["recipe"]]
            count += 1 + len(node["dependencies"])
    return count


class TransportLayout:
    def __init__(self, plan, observation, *, strategy="dense-first", corridor_length=18):
        self.plan = plan
        self.strategy = strategy
        self.corridor_length = corridor_length
        self.world = PlanningWorld(observation)
        self.stage_names = [s["id"] for s in plan["stages"]]
        self.stage_of = {e["address"]: i for i, s in enumerate(plan["stages"]) for e in s["additions"]}
        for e in plan["stages"][-1]["placements"]:
            self.world.add(e)
        self.ports = defaultdict(list)
        self.reserved = set()
        self.approaches = defaultdict(set)
        self.current_item = None
        self.active_port = None
        self.mining_ports = set()
        self.belts = {}
        self.pairs = []
        self.connections = []
        self.routes = {}
        self.starts = {item: max(3, min(self.stage_of[e["address"]] for e in self.world.entities
                        if e.get("recipe") == item or (e["name"] == "burner-mining-drill" and e["service"] == item)))
                       for item in plan["final_graph"]["nodes"]}

    def add(self, spec, stage):
        self.world.add(spec)
        self.stage_of[spec["address"]] = stage
        return spec["address"]

    def edge(self, source, target, item, kind):
        edge = {"from": source, "to": target, "item": item, "kind": kind}
        if kind in {"belt", "underground"}:
            entities = {e["address"]: e for e in self.world.entities}
            edge.update(from_position=list(point(entities[source])), to_position=list(point(entities[target])))
        self.connections.append(edge)

    def port(self, machine, item, role, belt, arm=None, direction=0):
        stage = max(self.stage_of[machine["address"]], self.starts[item])
        cell = (round(belt[0] - .5), round(belt[1] - .5))
        if cell in self.world.occupied or cell in self.reserved:
            raise ValueError(f"transport port overlaps another site: {machine['address']} {item} at {cell}")
        self.reserved.add(cell)
        if arm is None:
            self.mining_ports.add(cell)
        if role == "input" and machine["name"] == "assembling-machine-1":
            dx, dy = VECTORS[direction]
            for distance in (1, 2, 3):
                self.approaches[cell[0]+dx*distance, cell[1]+dy*distance].add((machine["address"], item))
        ident = machine["address"]
        if arm:
            ident += "." + role + "." + item
            self.add({"address": ident, "name": "inserter", "service": item,
                      "position": {"x": arm[0], "y": arm[1]}, "direction": direction}, stage)
            self.edge(machine["address"] if role == "output" else ident,
                      ident if role == "output" else machine["address"], item,
                      "pickup" if role == "output" else "drop")
        self.ports[item].append({"cell": cell, "machine": machine["address"], "entity": ident,
                                 "role": role, "stage": stage, "direct": arm is None,
                                 "terminal_direction": (direction+8)%16})

    def prepare_ports(self):
        original = list(self.world.entities)
        for machine in original:
            x, y = point(machine)
            if machine["name"] == "burner-mining-drill":
                self.port(machine, machine["service"], "output", (x-.5, y-1.5))
                self.port(machine, "coal", "input", (x-.5, y+2.5), (x-.5, y+1.5), 8)
            elif machine.get("recipe"):
                item = machine["recipe"]
                inputs = list(self.plan["final_graph"]["nodes"][item]["dependencies"])
                if machine["name"] == "stone-furnace":
                    for i, ingredient in enumerate(inputs):
                        self.port(machine, ingredient, "input", (x-2.5, y-.5+i), (x-1.5, y-.5+i), 12)
                    self.port(machine, item, "output", (x+2.5, y-.5), (x+1.5, y-.5), 12)
                else:
                    for i, ingredient in enumerate(inputs):
                        self.port(machine, ingredient, "input", (x-3, y-1+i), (x-2, y-1+i), 12)
                    self.port(machine, item, "output", (x+3, y), (x+2, y), 12)
            elif machine["name"] == "boiler":
                self.port(machine, "coal", "input", (x, y+2.5), (x, y+1.5), 8)
            elif machine["name"] == "lab":
                for i, item in enumerate(sorted(SCIENCE)):
                    self.port(machine, item, "input", (x+3, y-1+i*2), (x+2, y-1+i*2), 4)
        # The lab has priority along each science belt. Surplus continues to storage.
        for i, item in enumerate(sorted(SCIENCE)):
            lab = next(e for e in original if e["name"] == "lab")
            x, y = point(lab)
            chest = {"address": item + ".collection", "name": "wooden-chest", "service": item,
                     "position": {"x": x+8, "y": y-10+i*4}, "direction": 0}
            self.add(chest, self.starts[item])
            self.port(chest, item, "input", (x+8, y-8+i*4), (x+8, y-9+i*4), 8)

    def free(self, p, start, end):
        (xmin, ymin), (xmax, ymax) = self.world.survey["area"]
        if not (xmin <= p[0] and ymin <= p[1] and p[0]+1 <= xmax and p[1]+1 <= ymax):
            return False
        return p == start or (p not in self.world.occupied and (p == end or p not in self.reserved)
                              and not (self.approaches.get(p, set()) - {self.active_port}))

    def tunnel_clear(self, a, b, direction):
        axis = 0 if direction in (4, 12) else 1
        low, high = sorted((a[axis], b[axis]))
        for first, last, d in self.pairs:
            if d == direction and first[1-axis] == a[1-axis]:
                other_low, other_high = sorted((first[axis], last[axis]))
                if max(low, other_low) <= min(high, other_high):
                    return False
        return True

    def path(self, start, end, previous_direction=None, *, terminal=False, goal_direction=None):
        # State includes heading and whether an underground output forces the next
        # tile straight. Underground inputs and outputs can never turn in place.
        start_belt = self.belts.get(start, {})
        initial = (start, previous_direction, start_belt.get("type") == "output")
        queue = [(math.dist(start, end), 0, 0, initial)]
        cost, parent = {initial: 0}, {}
        serial = 0
        visits = 0
        while queue:
            _, distance, _, current = heapq.heappop(queue)
            if distance != cost[current]:
                continue
            visits += 1
            if visits > 16000:
                break
            p, heading, locked = current
            # Heading alone does not prevent a route looping back across itself
            # to approach a tunnel from another direction. Such a loop would
            # overwrite the first visit's belt direction when materialized.
            ancestor_cells, local_tunnels = {p}, []
            ancestor = current
            while ancestor != initial:
                prev, kind, direction = parent[ancestor]
                ancestor_cells.add(prev[0])
                if kind == "underground":
                    local_tunnels.append((prev[0], ancestor[0], direction))
                ancestor = prev
            if p == end:
                if goal_direction is not None and heading == (goal_direction+8)%16:
                    continue
                if locked and goal_direction is not None and heading != goal_direction:
                    continue
                if not terminal:
                    exits = []
                    for direction, (dx, dy) in VECTORS.items():
                        if direction == (heading+8)%16:
                            continue
                        exits.append(self.free((p[0]+dx, p[1]+dy), end, (-999, -999)))
                        if direction == heading:
                            for length in range(2, 6):
                                dest = (p[0]+dx*length, p[1]+dy*length)
                                exits.append(self.free(dest, end, (-999, -999)) and
                                             self.free((dest[0]+dx, dest[1]+dy), end, (-999, -999)) and
                                             self.tunnel_clear(p, dest, direction))
                    if not any(exits):
                        continue
                path = []
                while current != initial:
                    prev, kind, direction = parent[current]
                    path.append((prev[0], current[0], kind, direction))
                    current = prev
                return list(reversed(path))
            for direction, (dx, dy) in VECTORS.items():
                if heading is not None and (direction == (heading+8)%16 or (locked and direction != heading)):
                    continue
                steps = [(1, "belt")]
                if not locked and (p not in self.reserved or p == start) and (heading is None or heading == direction):
                    steps += [(n, "underground") for n in range(2, 6)]
                for length, kind in steps:
                    dest = (p[0]+dx*length, p[1]+dy*length)
                    if not self.free(dest, start, end) or dest in ancestor_cells:
                        continue
                    if kind == "underground" and ((dest in self.reserved and not (terminal and dest == end and direction == goal_direction)) or not self.tunnel_clear(p, dest, direction)):
                        continue
                    if kind == "underground":
                        axis = 0 if direction in (4, 12) else 1
                        low, high = sorted((p[axis], dest[axis]))
                        if any(d == direction and a[1-axis] == p[1-axis] and
                               max(low, min(a[axis], b[axis])) <= min(high, max(a[axis], b[axis]))
                               for a, b, d in local_tunnels):
                            continue
                    next_state = (dest, direction, kind == "underground")
                    new = distance + length + (4 if kind == "underground" else 0) + (.2 if heading != direction else 0)
                    if new < cost.get(next_state, float("inf")):
                        cost[next_state] = new
                        parent[next_state] = (current, kind, direction)
                        serial += 1
                        heapq.heappush(queue, (new+abs(end[0]-dest[0])+abs(end[1]-dest[1]), new, serial, next_state))
        raise ValueError(f"no dry belt route from {start} to {end}")

    def belt(self, item, cell, direction, stage, belt_type=None):
        if cell in self.belts:
            entity = self.belts[cell]
            if entity["service"] != item:
                raise ValueError("different items share a belt tile")
            entity["direction"] = direction
            if belt_type:
                entity.update(name="underground-belt", type=belt_type)
            return entity["address"]
        spec = {"address": f"transport.{item}.{cell[0]}.{cell[1]}",
                "name": "underground-belt" if belt_type else "transport-belt", "service": item,
                "position": {"x": cell[0]+.5, "y": cell[1]+.5}, "direction": direction}
        if belt_type:
            spec["type"] = belt_type
        self.add(spec, stage)
        self.belts[cell] = self.world.entities[-1]
        return spec["address"]

    def route_item(self, item):
        self.current_item = item
        self.active_port = None
        ports = self.ports[item]
        outputs = sorted([p for p in ports if p["role"] == "output"], key=lambda p: (p["stage"], p["cell"]))
        inputs = [p for p in ports if p["role"] == "input"]
        # The boiler receives fuel first; all other consumers are then visited in
        # stage order. Science storage follows the lab.
        if not outputs or not inputs:
            raise ValueError("a transport route needs producers and consumers: " + item)
        stage, direction = self.starts[item], None
        addresses = []
        def build(path):
            result = []
            for a, b, kind, d in path:
                source = self.belt(item, a, d, stage, "input" if kind == "underground" else None)
                target = self.belt(item, b, d, stage, "output" if kind == "underground" else None)
                self.edge(source, target, item, kind)
                if kind == "underground":
                    self.pairs.append((a, b, d))
                result += [source, target]
            addresses.extend(result)
        for first, last in zip(outputs, outputs[1:]):
            path = self.path(first["cell"], last["cell"], direction)
            build(path)
            direction = path[-1][-1]
        if len(inputs) == 1:
            port = inputs[0]
            self.active_port = (port["machine"], item)
            build(self.path(outputs[-1]["cell"], port["cell"], direction, terminal=True,
                            goal_direction=port["terminal_direction"]))
            self.belt(item, port["cell"], port["terminal_direction"], stage)
            self.finish_item(item, ports, addresses, stage)
            return
        # Only split the belt downstream of every producer, so every producer
        # can reach every consumer. Branches may themselves be split later.
        start = outputs[-1]["cell"]
        for d, (dx, dy) in VECTORS.items():
            end = (start[0]+dx*self.corridor_length, start[1]+dy*self.corridor_length)
            front = (end[0]+dx, end[1]+dy)
            if not self.free(end, start, end) or not self.free(front, start, end):
                continue
            try:
                extension = self.path(start, end, direction, terminal=True, goal_direction=d)
            except ValueError:
                continue
            build(extension)
            self.belt(item, end, d, stage)
            self.reserved.add(front)
            break
        else:
            raise ValueError("no distribution corridor for " + item)
        candidates = {p for a, b, kind, d in extension for p in (a, b)}
        for port in sorted(inputs, key=lambda p: (p["machine"].endswith(".collection"), p["machine"] != "power.boiler", p["stage"], p["cell"])):
            self.active_port = (port["machine"], item)
            end = port["cell"]
            options = []
            for cell in candidates:
                belt = self.belts[cell]
                if belt["name"] != "transport-belt" or cell in self.reserved:
                    continue
                dx, dy = VECTORS[belt["direction"]]
                prev, after = (cell[0]-dx, cell[1]-dy), (cell[0]+dx, cell[1]+dy)
                if not all(p in self.belts and self.belts[p]["service"] == item and self.belts[p]["direction"] == belt["direction"] for p in (prev, after)):
                    continue
                for side in (-1, 1):
                    other = (cell[0]-dy*side, cell[1]+dx*side)
                    branch = (other[0]+dx, other[1]+dy)
                    back = (other[0]-dx, other[1]-dy)
                    if any(not self.free(p, (-999,-999), end) for p in (other, branch, back)):
                        continue
                    options.append((math.dist(branch,end), cell, other, branch, belt["direction"]))
            for _, cell, other, branch, d in sorted(options):
                self.world.occupied.add(other)
                try:
                    path = self.path(branch, end, d, terminal=True, goal_direction=port["terminal_direction"])
                except ValueError:
                    self.world.occupied.remove(other)
                    continue
                splitter = self.belts[cell]
                splitter.update(name="splitter", position={"x": (cell[0]+other[0])/2+.5, "y": (cell[1]+other[1])/2+.5})
                if item in SCIENCE:
                    dx, dy = VECTORS[d]
                    side = (other[0]-cell[0])*(-dy)+(other[1]-cell[1])*dx
                    branch_priority = "right" if side > 0 else "left"
                    splitter["output_priority"] = ("left" if branch_priority == "right" else "right") if port["machine"].endswith(".collection") else branch_priority
                build(path)
                if not path:
                    addresses.append(self.belt(item, branch, d, stage))
                self.belt(item, end, port["terminal_direction"], stage)
                child = self.belts[branch]["address"]
                self.connections.append({"from": splitter["address"], "to": child, "item": item, "kind": "belt",
                    "from_position": [other[0]+.5, other[1]+.5], "to_position": [branch[0]+.5, branch[1]+.5]})
                if item not in SCIENCE:
                    candidates.update(p for a,b,kind,d in path for p in (a,b))
                break
            else:
                raise ValueError(f"no splitter branch for {port['machine']} {item} at {end} ({len(options)} candidates)")
        self.finish_item(item, ports, addresses, stage)

    def finish_item(self, item, ports, addresses, stage):
        for port in ports:
            belt = self.belts[port["cell"]]["address"]
            if port["role"] == "output":
                self.edge(port["entity"], belt, item, "direct-mining" if port["direct"] else "drop")
            else:
                self.edge(belt, port["entity"], item, "pickup")
        self.routes[item] = {"addresses": list(dict.fromkeys(addresses)),
                             "ports": [dict(port, cell=list(port["cell"])) for port in ports], "stage": stage,
                             "capacity_per_minute": 450, "capacity_basis": "One yellow-belt lane; rate check excludes inserter timing."}

    @staticmethod
    def supplied(consumer, pole):
        px, py = point(pole)
        return any(abs(x+.5-px) <= 2 and abs(y+.5-py) <= 2 for x, y in _cells(consumer))

    def power(self):
        poles = [e for e in self.world.entities if e["name"] == "small-electric-pole"]
        consumers = sorted([e for e in self.world.entities if e["name"] in {"inserter", "assembling-machine-1", "lab", "steam-engine"}],
                           key=lambda e: (self.stage_of[e["address"]], e["address"]))
        offsets = [(dx, dy) for dx in range(-7, 8) for dy in range(-7, 8) if 0 < dx*dx+dy*dy <= 49]
        for consumer in consumers:
            existing = next((p for p in poles if self.supplied(consumer, p)), None)
            stage = self.stage_of[consumer["address"]]
            if existing is None:
                candidates = {(x+.5+dx, y+.5+dy) for x, y in _cells(consumer) for dx in range(-2, 3) for dy in range(-2, 3)}
                targets = []
                for x, y in candidates:
                    spec = {"name": "small-electric-pole", "position": {"x": x, "y": y}}
                    if self.world.clear(spec):
                        targets.append((min(math.dist((x, y), point(p)) for p in poles), x, y))
                if not targets:
                    raise ValueError("no pole site can power " + consumer["address"])
                _, tx, ty = min(targets)
                end = (tx, ty)
                source = min(poles, key=lambda p: (math.dist(point(p), end), p["address"]))
                start = point(source)
                queue, costs, parent = [(math.dist(start, end)/7, 0, start)], {start: 0}, {}
                while queue:
                    _, cost, pos = heapq.heappop(queue)
                    if pos == end:
                        break
                    if cost != costs[pos]:
                        continue
                    for dx, dy in offsets:
                        dest = (pos[0]+dx, pos[1]+dy)
                        if not self.world.clear({"name": "small-electric-pole", "position": {"x": dest[0], "y": dest[1]}}):
                            continue
                        if cost+1 < costs.get(dest, float("inf")):
                            costs[dest], parent[dest] = cost+1, pos
                            heapq.heappush(queue, (cost+1+math.dist(dest, end)/7, cost+1, dest))
                else:
                    raise ValueError("no connected power route to " + consumer["address"])
                path = [end]
                while path[-1] != start:
                    path.append(parent[path[-1]])
                for x, y in reversed(path[:-1]):
                    spec = {"address": f"transport.pole.{len(poles)}", "name": "small-electric-pole",
                            "service": "power", "position": {"x": x, "y": y}, "direction": 0}
                    self.add(spec, stage)
                    self.edge(source["address"], spec["address"], "electricity", "wire")
                    poles.append(spec)
                    source = spec
                existing = source
            self.edge(existing["address"], consumer["address"], "electricity", "power")

    def compile(self):
        self.prepare_ports()
        # Dense mineral/fuel connections first, followed by the assembly chains.
        if self.strategy == "resources-first":
            order = sorted(self.ports, key=lambda item: (not item.endswith("-ore"), self.starts[item], -len(self.ports[item]), item))
        elif self.strategy == "assembly-first":
            order = sorted(self.ports, key=lambda item: (item in {"coal", "iron-ore", "copper-ore"}, -self.starts[item], len(self.ports[item]), item))
        else:
            order = sorted(self.ports, key=lambda item: (self.starts[item], -len(self.ports[item]), item))
        for item in order:
            self.route_item(item)
        self.power()
        schedule = {name: [] for name in self.stage_names}
        for entity in self.world.entities:
            schedule[self.stage_names[self.stage_of[entity["address"]]]].append(deepcopy(entity))
        return schedule, {"connections": self.connections, "routes": self.routes,
                          "strategy": self.strategy, "corridor_length": self.corridor_length,
                          "validation": validate_transport(self.world.entities, self.connections, self.routes)}


def validate_transport(placements, connections, routes):
    """Check physical adjacency, tunnel pairing, power reach and end-to-end flow."""
    entities = {e["address"]: e for e in placements}
    occupied = {}
    for entity in placements:
        for cell in _cells(entity):
            if cell in occupied:
                raise ValueError("overlapping transport footprints")
            occupied[cell] = entity
    for entity in placements:
        if entity["name"] not in {"transport-belt", "splitter"} and not (entity["name"] == "underground-belt" and entity.get("type") == "output"):
            continue
        dx, dy = VECTORS[entity["direction"]]
        for x, y in _cells(entity):
            other = occupied.get((x+dx, y+dy))
            if other and other["name"] in {"transport-belt", "underground-belt", "splitter"} and other["service"] != entity["service"]:
                raise ValueError("belt spills into a different item route: " + entity["address"])
    graph = defaultdict(set)
    power_graph = defaultdict(set)
    powered_types = {"inserter", "assembling-machine-1", "lab", "steam-engine"}
    underground = {}
    for edge in connections:
        if edge["from"] not in entities or edge["to"] not in entities:
            raise ValueError("connection references an absent entity")
        a, b = entities[edge["from"]], entities[edge["to"]]
        ax, ay = point(a)
        bx, by = point(b)
        kind = edge["kind"]
        if kind in {"belt", "underground"}:
            ax, ay = edge["from_position"]
            bx, by = edge["to_position"]
            if (math.floor(ax),math.floor(ay)) not in _cells(a) or (math.floor(bx),math.floor(by)) not in _cells(b):
                raise ValueError("belt connection uses a tile outside its entity")
            dx, dy = VECTORS[a["direction"]]
            length = abs(ax-bx)+abs(ay-by)
            if (bx-ax, by-ay) != (dx*length, dy*length) or (kind == "belt" and length != 1):
                raise ValueError("belt direction misses its downstream tile: " + a["address"])
            if kind == "underground":
                if not (2 <= length <= 5 and a.get("type") == "input" and b.get("type") == "output" and a["direction"] == b["direction"]):
                    raise ValueError("invalid underground belt pair")
                underground[a["address"]] = b["address"]
            if kind == "belt" and b["direction"] == (a["direction"]+8)%16:
                raise ValueError("belt feeds the front of another belt")
        elif kind == "pickup":
            dx, dy = VECTORS[b["direction"]]
            if (math.floor(bx+dx), math.floor(by+dy)) not in _cells(a):
                raise ValueError("inserter cannot reach pickup: " + b["address"])
        elif kind == "drop":
            dx, dy = VECTORS[a["direction"]]
            if (math.floor(ax-1.2*dx), math.floor(ay-1.2*dy)) not in _cells(b):
                raise ValueError("inserter cannot reach drop: " + a["address"])
        elif kind == "direct-mining":
            if a["direction"] != 0 or (math.floor(ax-.347), math.floor(ay-1.297)) not in _cells(b):
                raise ValueError("mining output misses belt")
        elif kind == "wire":
            if a["name"] != "small-electric-pole" or b["name"] != "small-electric-pole":
                raise ValueError("power wire must connect poles")
            if math.dist((ax, ay), (bx, by)) > 7:
                raise ValueError("power wire exceeds reach")
        elif kind == "power":
            if a["name"] != "small-electric-pole" or b["name"] not in powered_types or not TransportLayout.supplied(b, a):
                raise ValueError("electric consumer outside pole coverage")
        else:
            raise ValueError("unsupported physical connection")
        if kind not in {"wire", "power"}:
            graph[edge["item"], a["address"]].add(b["address"])
        else:
            power_graph[a["address"]].add(b["address"])
            power_graph[b["address"]].add(a["address"])
    generators = {e["address"] for e in placements if e["name"] == "steam-engine"}
    seen, pending = set(generators), list(generators)
    while pending:
        for target in power_graph[pending.pop()]:
            if target not in seen:
                seen.add(target)
                pending.append(target)
    required_power = {e["address"] for e in placements if e["name"] in powered_types | {"small-electric-pole"}}
    if required_power - seen:
        raise ValueError("electric equipment disconnected from generation: " + min(required_power - seen))
    for source, target in underground.items():
        a = entities[source]
        dx, dy = VECTORS[a["direction"]]
        candidates = [b for b in entities.values() if b["name"] == "underground-belt" and b.get("type") == "output"
                      and b["direction"] == a["direction"] and
                      0 < (point(b)[0]-point(a)[0])*dx+(point(b)[1]-point(a)[1])*dy <= 5 and
                      (point(b)[0]-point(a)[0])*dy == (point(b)[1]-point(a)[1])*dx]
        if not candidates or min(candidates, key=lambda b: math.dist(point(a), point(b)))["address"] != target:
            raise ValueError("underground belt pairs with the wrong output")
    for item, route in routes.items():
        cells = route["addresses"]
        if len(set(cells)) != len(cells):
            raise ValueError("belt route revisits a tile: " + item)
        for producer in (p for p in route["ports"] if p["role"] == "output"):
            source = producer["machine"]
            seen, pending = {source}, [source]
            while pending:
                for target in graph[item, pending.pop()]:
                    if target not in seen:
                        seen.add(target)
                        pending.append(target)
            for port in route["ports"]:
                if port["role"] == "input" and port["machine"] not in seen:
                    raise ValueError("unreachable consumer on " + item)
    return {"status": "passed", "checks": ["belt direction", "inserter pickup/drop", "mining output",
             "underground pairing", "power reach", "connected power network", "producer-to-consumer paths"],
            "scope": "Static geometry and connectivity; engine startup and throughput remain unverified."}
