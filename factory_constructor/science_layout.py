"""Pure lowering of a bounded red-science recipe graph into additive geometry.

This method recognizes the surveyed north-edge iron/coal opening. It retains
that opening and routes its two iron outputs south of the original furnaces.
Machine quantities come from the supplied runtime rules; routing is deliberately
bounded to one gear assembler and at most two science assemblers.
"""
from collections import Counter
import heapq
import math


SIZES = {"burner-mining-drill": (2, 2), "stone-furnace": (2, 2),
         "assembling-machine-1": (3, 3), "lab": (3, 3),
         "steam-engine": (3, 5), "boiler": (3, 2), "splitter": (2, 1)}


def _position(entity):
    return entity["position"]["x"], entity["position"]["y"]


def _cells(entity):
    name = entity.get("name", entity.get("prototype"))
    width, height = SIZES.get(name, (1, 1))
    if entity.get("direction", 0) in (4, 12):
        width, height = height, width
    x, y = _position(entity)
    return {(math.floor(x-width/2)+dx, math.floor(y-height/2)+dy)
            for dx in range(width) for dy in range(height)}


def _amounts(values):
    if isinstance(values, dict):
        return values
    return {entry["name"]: entry["amount"] for entry in values
            if entry.get("type", "item") == "item"}


def layout(observation, deployment, rules, target_per_minute):
    """Return new placements and physical connections without mutating inputs.

    ``rules`` may be the compiler Rules instance or resolved-rules dictionary.
    Mining areas carry their resource name for native coal/copper accounting.
    Connections name real addresses, including retained iron and fuel endpoints.
    """
    if (isinstance(target_per_minute, bool) or not isinstance(target_per_minute, (int, float))
            or not math.isfinite(target_per_minute) or not 0 < target_per_minute <= 12):
        raise ValueError("science layout supports a positive finite target at most 12/min")
    if not deployment or deployment.get("service", {}).get("item") != "iron-plate":
        raise ValueError("science layout needs a verified two-output iron deployment")
    document = rules.document if hasattr(rules, "document") else rules
    recipes, machines = document["recipes"], document["machines"]
    science, gears, copper = (recipes[name] for name in
                            ("automation-science-pack", "iron-gear-wheel", "copper-plate"))
    si, gi, ci = (_amounts(recipe["inputs"]) for recipe in (science, gears, copper))
    so, go, co = (_amounts(recipe["outputs"]) for recipe in (science, gears, copper))
    if set(si) != {"copper-plate", "iron-gear-wheel"} or set(gi) != {"iron-plate"} or set(ci) != {"copper-ore"}:
        raise ValueError("science layout needs the supported copper/gear recipe graph")
    asm, furnace = machines["assembling-machine-1"], machines["stone-furnace"]
    def capacity(recipe, machine, item):
        return 60 * machine["speed"] * _amounts(recipe["outputs"])[item] / recipe["seconds"]
    caps = {"automation-science-pack": capacity(science, asm, "automation-science-pack"),
            "iron-gear-wheel": capacity(gears, asm, "iron-gear-wheel"),
            "copper-plate": capacity(copper, furnace, "copper-plate")}
    science_crafts = target_per_minute / so["automation-science-pack"]
    gear_rate, copper_rate = science_crafts * si["iron-gear-wheel"], science_crafts * si["copper-plate"]
    iron_rate = gear_rate / go["iron-gear-wheel"] * gi["iron-plate"]
    ore_rate = copper_rate / co["copper-plate"] * ci["copper-ore"]
    required = {"automation-science-pack": math.ceil(target_per_minute/caps["automation-science-pack"]),
                "iron-gear-wheel": math.ceil(gear_rate/caps["iron-gear-wheel"]),
                "copper-plate": math.ceil(copper_rate/caps["copper-plate"])}
    if required["automation-science-pack"] > 2 or required["iron-gear-wheel"] > 1 or required["copper-plate"] > 1 or ore_rate > 15:
        raise ValueError("runtime recipe rates exceed the bounded science geometry (2 science, 1 gear, 1 copper line)")
    if deployment["service"]["minimum_per_minute"] < iron_rate:
        raise ValueError("verified iron service cannot supply the science ingredient rate")
    survey, state = observation["capture"]["survey"], observation["state"]
    existing = {address: dict(entity, address=address) for address, entity in deployment["entities"].items()}
    for group in (state.get("iron", {}).get("entities", []), state.get("power_entities", []), state.get("coal", {}).get("entities", []),
                  state.get("feed", {}).get("entities", []), state.get("built", [])):
        for entity in group:
            existing[entity["address"]] = entity
    outputs = deployment["design"]["output"]["addresses"]
    if len(outputs) != 2 or any(existing[address]["name"] != "wooden-chest" for address in outputs):
        raise ValueError("science layout needs two retained iron collection chests")
    chests = sorted((existing[address] for address in outputs), key=lambda e: _position(e)[0])
    (left_x, chest_y), (right_x, right_y) = map(_position, chests)
    if right_y != chest_y or right_x-left_x != 6:
        raise ValueError("science layout needs the recognized six-tile iron line spacing")
    ore = [r for r in survey["resources"] if r["prototype"] == "copper-ore"]
    coal = [r for r in survey["resources"] if r["prototype"] == "coal"]
    if not ore or not coal or any(not r["minable"] or r["infinite"] or r["amount"] <= 0 for r in ore+coal):
        raise ValueError("science layout needs finite minable copper and coal")
    if any(r.get("mining_time") != 1 for r in ore+coal):
        raise ValueError("science layout mining capacity needs the observed one-second copper/coal mechanics")
    copper_x = math.floor(min(_position(r)[0] for r in ore)) + 1
    drill_y = math.floor(min(_position(r)[1] for r in ore)) + 1
    if drill_y-2.5 != chest_y or copper_x-right_x != 12.5:
        raise ValueError("science layout needs the observed copper patch east of the iron opening")
    ore_tiles = {_position(r) for r in ore}
    coal_tiles = {_position(r) for r in coal}
    def covered(x, y, tiles):
        return {(x-.5, y-.5), (x+.5, y-.5), (x-.5, y+.5), (x+.5, y+.5)} <= tiles
    if not covered(copper_x, drill_y, ore_tiles):
        raise ValueError("copper drill footprint lacks observed copper ore")

    # Reserve complete entity tiles, not merely collision boxes. Poles and belts
    # therefore never share cells; a belt crossing must be modeled explicitly.
    occupied = {}
    for entity in list(existing.values()) + survey.get("infrastructure", []) + survey.get("obstacles", []):
        if entity.get("entity_type") == "character":
            continue  # the walking builder is movable, not retained construction
        for cell in _cells(entity):
            occupied[cell] = entity.get("address", entity.get("id", "existing"))
    water = {(p["x"], p["y"]) for p in survey.get("water_tiles", [])}
    (xmin, ymin), (xmax, ymax) = survey["area"]
    placements, connections = [], []
    def clear(entity):
        return all(xmin <= x and ymin <= y and x+1 <= xmax and y+1 <= ymax
                   and (x, y) not in occupied and (x, y) not in water for x, y in _cells(entity))
    def add(address, name, x, y, direction=0, recipe=None):
        spec = {"address": address, "name": name, "position": {"x": x, "y": y}, "direction": direction}
        if recipe:
            spec["recipe"] = recipe
        if not clear(spec):
            raise ValueError(f"science layout site blocked, wet, or outside survey: {address} at {(x,y)}")
        placements.append(spec)
        for cell in _cells(spec):
            occupied[cell] = address
        return address
    def edge(source, target, item, kind="item-transfer"):
        connections.append({"from": source, "to": target, "item": item, "kind": kind})
    def line(points):
        result = [points[0]]
        for tx, ty in points[1:]:
            x, y = result[-1]
            if tx != x and ty != y:
                raise ValueError("belt routes must use orthogonal segments")
            while (x, y) != (tx, ty):
                x += (tx > x)-(tx < x)
                y += (ty > y)-(ty < y)
                result.append((x, y))
        return result
    belt_at = {}
    def belts(stem, corners, item, last_direction=4, into=None):
        points = line(corners)
        addresses = []
        for i, (x, y) in enumerate(points):
            nx, ny = points[i+1] if i+1 < len(points) else (x, y)
            direction = 4 if nx > x else 12 if nx < x else 8 if ny > y else 0 if ny < y else last_direction
            address = add(f"{stem}.{i}", "transport-belt", x, y, direction)
            addresses.append(address)
            belt_at[x, y] = address
        for source, target in zip(addresses, addresses[1:]):
            edge(source, target, item, "belt")
        if into:
            edge(addresses[-1], into, item, "belt")
        return addresses
    def inserter(address, x, y, direction, source, target, item, burner=False):
        add(address, "burner-inserter" if burner else "inserter", x, y, direction)
        edge(source, address, item, "pickup")
        edge(address, target, item, "drop")
    def retained_belt(x, y):
        match = [e for e in existing.values() if e["name"] == "transport-belt" and _position(e) == (x, y)]
        if len(match) != 1:
            raise ValueError("science layout needs the retained iron fuel route at " + str((x, y)))
        return match[0]["address"]

    # Merge both miners before the original coal chest. Injecting into the iron
    # trunk lets buffered chest output claim every upstream gap and starve the
    # added miner, while the boiler continues draining that finite chest stock.
    original_coal = existing.get("coal.drill")
    if not original_coal or original_coal["name"] != "burner-mining-drill" or original_coal["direction"] != 0:
        raise ValueError("additional coal supply needs the observed north-facing original coal drill")
    coal_x, original_coal_y = _position(original_coal)
    coal_y = original_coal_y+3
    if not covered(coal_x, coal_y, coal_tiles):
        raise ValueError("additional coal drill footprint lacks observed coal")
    coal_merge = retained_belt(coal_x-.5, original_coal_y-1.5)
    if existing[coal_merge]["direction"] != 4:
        raise ValueError("additional coal drill needs the original eastbound coal collection belt")
    add("science.coal.drill", "burner-mining-drill", coal_x, coal_y, 12)
    coal_route = belts("science.coal.output.belt", [(coal_x-1.5, coal_y+.5),
                       (coal_x-2.5, coal_y+.5), (coal_x-2.5, original_coal_y-1.5),
                       (coal_x-1.5, original_coal_y-1.5)], "coal", 4, coal_merge)
    edge("science.coal.drill", coal_route[0], "coal", "direct-mining")
    coal_chest = existing.get("coal.chest")
    if not coal_chest or _position(coal_chest) != (coal_x+2.5, coal_y+.5):
        raise ValueError("additional coal drill needs the observed shared coal chest beside its fuel inserter")
    # The shared chest starts this empty drill automatically and receives its
    # later output. An isolated output/refuel loop cannot start without a seed.
    inserter("science.coal.refuel.inserter", coal_x+1.5, coal_y+.5, 4,
             coal_chest["address"], "science.coal.drill", "coal", True)

    # Reuse the terminal iron fuel belt through an inserter branch. The new
    # northern copper corridor never crosses either retained iron line.
    fuel_source_x = right_x+5
    fuel_source = retained_belt(fuel_source_x, drill_y-.5)
    copper_fuel = belts("science.copper.fuel.belt", [(fuel_source_x+2, drill_y-.5),
                         (fuel_source_x+2, drill_y-6.5), (copper_x+2.5, drill_y-6.5),
                         (copper_x+2.5, drill_y-.5)], "coal", 8)
    inserter("science.copper.fuel.tap", fuel_source_x+1, drill_y-.5, 12,
             fuel_source, copper_fuel[0], "coal", True)
    add("science.copper.drill", "burner-mining-drill", copper_x, drill_y)
    add("science.copper.furnace", "stone-furnace", copper_x, drill_y-2)
    edge("science.copper.drill", "science.copper.furnace", "copper-ore", "direct-mining")
    for suffix, y in (("drill", drill_y-.5), ("furnace", drill_y-2.5)):
        inserter("science.copper."+suffix+"-fuel", copper_x+1.5, y, 4,
                 belt_at[copper_x+2.5, y], "science.copper."+suffix, "coal", True)

    # Production corridor below the ore patches. The detour west of the first
    # iron chest preserves the starter furnace centered three tiles below it.
    gear_x, machine_y = copper_x-4.5, drill_y+15.5
    iron_bus_y = machine_y-3
    iron0 = belts("science.iron.0.belt", [(left_x, chest_y+2), (left_x, drill_y+6.5),
                  (left_x-3, drill_y+6.5), (left_x-3, iron_bus_y), (gear_x, iron_bus_y)], "iron-plate")
    iron1 = belts("science.iron.1.belt", [(right_x, chest_y+2), (right_x, iron_bus_y-1)],
                  "iron-plate", 8, belt_at[right_x, iron_bus_y])
    for i, (chest, route) in enumerate(zip(chests, (iron0, iron1))):
        x, y = _position(chest)
        inserter(f"science.iron.{i}.extract", x, y+1, 0, chest["address"], route[0], "iron-plate")
    add("science.gears.assembler", "assembling-machine-1", gear_x, machine_y, recipe="iron-gear-wheel")
    inserter("science.gears.input", gear_x, machine_y-2, 0, iron0[-1], "science.gears.assembler", "iron-plate")
    count = required["automation-science-pack"]
    science_xs = [gear_x+8*(i+1) for i in range(count)]
    copper_belt = belts("science.copper.output.belt", [(copper_x-2.5, drill_y-2.5),
                         (copper_x-2.5, iron_bus_y), (science_xs[-1], iron_bus_y)], "copper-plate")
    inserter("science.copper.output", copper_x-1.5, drill_y-2.5, 4,
             "science.copper.furnace", copper_belt[0], "copper-plate")
    gear_belt = belts("science.gears.output.belt", [(gear_x+3, machine_y),
                       (gear_x+3, machine_y+3), (science_xs[-1], machine_y+3)], "iron-gear-wheel")
    inserter("science.gears.output", gear_x+2, machine_y, 12,
             "science.gears.assembler", gear_belt[0], "iron-gear-wheel")
    science_outputs = []
    storage_recipe = recipes.get("iron-chest", {})
    storage_unlocked = storage_recipe.get("enabled", False) or bool(
        set(storage_recipe.get("unlocked_by", [])) & set(state.get("researched", [])))
    storage = "iron-chest" if storage_unlocked else "wooden-chest"
    for i, x in enumerate(science_xs):
        assembler, chest = f"science.assembler.{i}", f"science.output.{i}.chest"
        add(assembler, "assembling-machine-1", x, machine_y, recipe="automation-science-pack")
        inserter(f"science.assembler.{i}.copper", x, machine_y-2, 0,
                 belt_at[x, iron_bus_y], assembler, "copper-plate")
        inserter(f"science.assembler.{i}.gears", x, machine_y+2, 8,
                 belt_at[x, machine_y+3], assembler, "iron-gear-wheel")
        add(chest, storage, x+3, machine_y)
        inserter(f"science.output.{i}.inserter", x+2, machine_y, 12,
                 assembler, chest, "automation-science-pack")
        science_outputs.append(chest)

    # Cover every electric inserter and assembler, then build a connected pole
    # tree from observed poles. Wire hops use conservative <=7-tile distance.
    consumers = [p for p in placements if p["name"] in {"inserter", "assembling-machine-1"}]
    anchor = next((p for p in state.get("power_entities", [])
                   if p["name"] == "small-electric-pole" and p.get("network_id") is not None), None)
    if anchor is None:
        raise ValueError("science layout needs an observed steam electric network")
    existing_poles = [e for e in existing.values() if e["name"] == "small-electric-pole"
                      and e.get("network_id") == anchor["network_id"]]
    observed_poles = [e for e in survey.get("infrastructure", []) if e["prototype"] == "small-electric-pole"]
    if any(p.get("supply_radius", 0) < 2.5 or p.get("max_wire_distance", 0) < 7 for p in observed_poles):
        raise ValueError("science layout pole coverage needs the observed small-pole mechanics")
    if not existing_poles:
        raise ValueError("science layout needs an observed electric pole network")
    poles = list(existing_poles)
    def supplied(consumer, pole):
        px, py = _position(pole)
        return any(abs(x+.5-px) <= 2 and abs(y+.5-py) <= 2 for x, y in _cells(consumer))
    uncovered = [p for p in consumers if not any(supplied(p, pole) for pole in poles)]
    coverage_targets = []
    while uncovered:
        candidates = set()
        for consumer in uncovered:
            for x, y in _cells(consumer):
                candidates.update((x+.5+dx, y+.5+dy) for dx in range(-2, 3) for dy in range(-2, 3))
        ranked = []
        for x, y in candidates:
            spec = {"name": "small-electric-pole", "position": {"x": x, "y": y}}
            if clear(spec):
                score = sum(supplied(p, spec) for p in uncovered)
                distance = min(math.dist((x, y), _position(p)) for p in poles)
                ranked.append((-score, distance, x, y, spec))
        if not ranked:
            raise ValueError("no clear electric pole site covers the production corridor")
        *_, spec = min(ranked)
        coverage_targets.append(spec)
        poles.append(spec)
        # Reserve targets before connecting them to prevent selecting duplicates.
        occupied.update({cell: "reserved pole" for cell in _cells(spec)})
        uncovered = [p for p in uncovered if not supplied(p, spec)]
    connected = list(existing_poles)
    def connect(target):
        end = _position(target)
        start_entity = min(connected, key=lambda p: (math.dist(_position(p), end), _position(p)))
        start = _position(start_entity)
        queue, costs, previous = [(math.dist(start, end)/7, 0, start)], {start: 0}, {}
        offsets = [(dx, dy) for dx in range(-7, 8) for dy in range(-7, 8) if 0 < dx*dx+dy*dy <= 49]
        while queue:
            _, cost, current = heapq.heappop(queue)
            if current == end:
                break
            if cost != costs[current]:
                continue
            for dx, dy in offsets:
                point = current[0]+dx, current[1]+dy
                spec = {"name": "small-electric-pole", "position": {"x": point[0], "y": point[1]}}
                if point != end and not clear(spec):
                    continue
                new = cost+1
                if new < costs.get(point, float("inf")):
                    costs[point], previous[point] = new, current
                    heapq.heappush(queue, (new+math.dist(point, end)/7, new, point))
        else:
            raise ValueError("no observed dry pole route joins the steam network")
        path = [end]
        while path[-1] != start:
            path.append(previous[path[-1]])
        source = start_entity["address"]
        for x, y in reversed(path[:-1]):
            if (x, y) == end:
                for cell in _cells(target):
                    occupied.pop(cell)
            address = add(f"science.pole.{len([p for p in placements if p['name'] == 'small-electric-pole'])}",
                          "small-electric-pole", x, y)
            edge(source, address, "electricity", "wire")
            source = address
            connected.append(placements[-1])
    for target in coverage_targets:
        connect(target)
    for consumer in consumers:
        pole = next(p for p in connected if supplied(consumer, p))
        edge(pole["address"], consumer["address"], "electricity", "power")

    machine_crafts = {"automation-science-pack": science_crafts,
                      "iron-gear-wheel": gear_rate/go["iron-gear-wheel"],
                      "copper-plate": copper_rate/co["copper-plate"]}
    electric_kw = sum(asm["electric_kw"] * machine_crafts[name] * recipes[name]["seconds"] / asm["speed"] / 60
                      for name in ("automation-science-pack", "iron-gear-wheel"))
    smelting_coal = furnace["fuel_kw"] * machine_crafts["copper-plate"] * copper["seconds"] / furnace["speed"] / document["fuel_kj"]["coal"]
    return {"method": "bounded additive coal, copper and automation-science recipe graph",
            "placements": placements, "bill": dict(Counter(p["name"] for p in placements)),
            "mining_areas": [{"resource": "coal", "area": [[coal_x-1, coal_y-1], [coal_x+1, coal_y+1]]},
                             {"resource": "copper-ore", "area": [[copper_x-1, drill_y-1], [copper_x+1, drill_y+1]]}],
            "connections": connections, "links": [[c["from"], c["to"]] for c in connections if c["kind"] not in {"wire", "power"}],
            "counts": {"required": required, "selected": dict(required), "additional_coal_drills": 1},
            "rates": {"items_per_minute": {"automation-science-pack": target_per_minute,
                      "iron-gear-wheel": gear_rate, "iron-plate": iron_rate, "copper-plate": copper_rate, "copper-ore": ore_rate},
                      "machine_capacity_per_minute": caps, "assembler_active_kw": electric_kw,
                      "copper_smelting_coal_per_minute": smelting_coal,
                      "additional_coal_drill_capacity_per_minute": 15,
                      "mining_capacity_basis": "verified opening burner method: speed 0.25, resource mining time 1s"},
            "components": {"coal": [p["address"] for p in placements if p["address"].startswith("science.coal.")],
                           "copper-plate": [p["address"] for p in placements if p["address"].startswith("science.copper.")],
                           "iron-gear-wheel": [p["address"] for p in placements if p["address"].startswith(("science.iron.", "science.gears."))],
                           "automation-science-pack": [p["address"] for p in placements if p["address"].startswith(("science.assembler.", "science.output."))],
                           "electricity": [p["address"] for p in placements if p["name"] == "small-electric-pole"]},
            "source": {"address": fuel_source, "id": existing[fuel_source]["id"], "item": "coal"},
            "iron_sources": [{"address": c["address"], "id": c["id"], "item": "iron-plate"} for c in chests],
            "power": {"address": anchor["address"], "id": anchor["id"], "network_id": anchor["network_id"]},
            "output": {"addresses": science_outputs, "item": "automation-science-pack", "minimum_per_min": target_per_minute},
            "seed_coal": {}, "measurement": {"warmup_ticks": 18000, "window_ticks": 3600, "windows": 5}}
