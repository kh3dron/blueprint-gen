"""Bounded resource procurement and direct connection observations, without flow inference."""

from collections import defaultdict, deque
from copy import deepcopy
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from .game_import import digest, sequence, validate_capture
from .model import integer, number

MINERALS = {"iron-ore", "copper-ore", "coal", "stone"}


def position(value, field):
    if not isinstance(value, dict) or set(value) != {"x", "y"}:
        raise ValueError(f"{field} must contain x and y")
    for component in value.values():
        if (
            isinstance(component, bool)
            or not isinstance(component, (int, float))
            or not math.isfinite(component)
        ):
            raise ValueError(f"{field} must be finite")
    return value


def survey_data(capture):
    validate_capture(capture)
    data = capture.get("survey")
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError(
            "capture has no supported survey; run /advisor-survey with observer 0.2.0 or 0.3.0"
        )
    if data.get("tick") != capture["tick"] or data.get("area") != capture["scope"].get(
        "area"
    ):
        raise ValueError("survey tick/area must match its enclosing capture")
    area = data.get("area")
    if (
        not isinstance(area, list)
        or len(area) != 2
        or any(not isinstance(p, list) or len(p) != 2 for p in area)
    ):
        raise ValueError("survey area must have two [x, y] corners")
    for p in area:
        position(dict(zip(("x", "y"), p)), "survey.area")
    if any(not 0 < area[1][i] - area[0][i] <= 128 for i in (0, 1)):
        raise ValueError("survey dimensions must be positive and at most 128 tiles")
    actor = position(capture["player"].get("position"), "player.position")
    if not inside(actor, area):
        raise ValueError("survey player position lies outside the captured area")
    for field, limit in (
        ("resources", 8192),
        ("infrastructure", 2048),
        ("obstacles", 4096),
        ("water_tiles", 16641),
        ("ungenerated_chunks", 25),
    ):
        entries = sequence(data.get(field), "survey." + field)
        if len(entries) > limit:
            raise ValueError(f"survey.{field} exceeds the observer limit")
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(f"survey.{field} entries must be objects")
            position(
                entry
                if field in ("water_tiles", "ungenerated_chunks")
                else entry.get("position"),
                field + ".position",
            )
            if field in ("water_tiles", "ungenerated_chunks"):
                continue
            if (
                not isinstance(entry.get("id"), str)
                or not entry["id"]
                or entry["id"] in seen
            ):
                raise ValueError(f"survey.{field} ids must be unique strings")
            seen.add(entry["id"])
            if not isinstance(entry.get("prototype"), str):
                raise ValueError(f"survey.{field} requires prototype identity")
    occupied = set()
    for resource in data["resources"]:
        integer(resource.get("amount"), "resource.amount")
        number(resource.get("mining_time"), "resource.mining_time", positive=True)
        if not inside(resource["position"], area):
            raise ValueError("resource is outside the surveyed area")
        cell = (
            resource["prototype"],
            resource["position"]["x"],
            resource["position"]["y"],
        )
        if cell in occupied:
            raise ValueError("duplicate resource position would double-count stock")
        occupied.add(cell)
        for flag in ("minable", "infinite", "standable"):
            if type(resource.get(flag)) is not bool:
                raise ValueError(f"resource.{flag} must be boolean")
        sequence(resource.get("products"), "resource.products")
        if any(not isinstance(p, dict) for p in resource["products"]):
            raise ValueError("resource.products entries must be objects")
    for entity in data["infrastructure"]:
        if not isinstance(entity.get("status"), str) or not isinstance(
            entity.get("entity_type"), str
        ):
            raise ValueError("infrastructure requires status and entity_type")
        number(entity.get("energy_j"), "infrastructure.energy_j")
        if entity.get("electric_network_id") is not None:
            integer(
                entity["electric_network_id"],
                "infrastructure.electric_network_id",
                positive=True,
            )
        if entity["entity_type"] == "inserter":
            for side in ("pickup", "drop"):
                position(entity.get(side + "_position"), side + ".position")
                target = entity.get(side + "_target")
                if target is not None:
                    position(target.get("position"), side + ".target.position")
        for neighbour in sequence(
            entity.get("copper_neighbours", []), "copper_neighbours"
        ):
            position(neighbour.get("position"), "copper_neighbour.position")
    for obstacle in data["obstacles"]:
        box = obstacle.get("bounding_box")
        if not isinstance(box, dict):
            raise ValueError("obstacle requires a bounding_box")
        for corner in ("left_top", "right_bottom"):
            position(box.get(corner), "obstacle." + corner)
        if any(
            box["left_top"][axis] > box["right_bottom"][axis] for axis in ("x", "y")
        ):
            raise ValueError("obstacle bounding_box corners are reversed")
    return data


def inside(p, area):
    return area[0][0] <= p["x"] < area[1][0] and area[0][1] <= p["y"] < area[1][1]


def distance(a, b):
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def hand_product(resource):
    """Only reviewed finite, one-item-per-cycle base mineral resources are supported."""
    products = resource["products"]
    if (
        resource["infinite"]
        or not resource["minable"]
        or resource.get("required_fluid")
        or len(products) != 1
    ):
        return None
    p = products[0]
    if (
        p.get("name") not in MINERALS
        or p.get("type", "item") != "item"
        or p.get("amount") != 1
        or p.get("probability", 1) != 1
        or p.get("independent_probability", 1) != 1
        or p.get("shared_probability", {"min": 0, "max": 1}) != {"min": 0, "max": 1}
        or "amount_min" in p
        or "amount_max" in p
    ):
        return None
    return p["name"]


def patches(capture):
    """Four-neighbour resource components clipped to the actual observation area."""
    data = survey_data(capture)
    by_cell = {
        (r["prototype"], r["position"]["x"], r["position"]["y"]): r
        for r in data["resources"]
    }
    result, visited = [], set()
    origin = capture["player"]["position"]
    for seed in sorted(by_cell):
        if seed in visited:
            continue
        queue, members = deque([seed]), []
        visited.add(seed)
        while queue:
            cell = queue.popleft()
            members.append(by_cell[cell])
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                neighbour = (cell[0], cell[1] + dx, cell[2] + dy)
                if neighbour in by_cell and neighbour not in visited:
                    visited.add(neighbour)
                    queue.append(neighbour)
        nearest = min(members, key=lambda r: (distance(origin, r["position"]), r["id"]))
        result.append(
            {
                "resource": seed[0],
                "tiles": len(members),
                "units_observed": sum(r["amount"] for r in members),
                "infinite": any(r["infinite"] for r in members),
                "hand_mineable_units": sum(
                    r["amount"] for r in members if hand_product(r) and r["standable"]
                ),
                "nearest_position": nearest["position"],
                "straight_line_distance": distance(origin, nearest["position"]),
                "touches_scope_edge": any(
                    not inside(
                        {"x": r["position"]["x"] + dx, "y": r["position"]["y"] + dy},
                        data["area"],
                    )
                    for r in members
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                ),
            }
        )
    return sorted(
        result,
        key=lambda p: (
            p["straight_line_distance"],
            p["resource"],
            p["nearest_position"]["x"],
            p["nearest_position"]["y"],
        ),
    )


def inspect(capture):
    data = survey_data(capture)
    facts, networks = [], defaultdict(list)
    records = list(capture["machines"]) + list(data["infrastructure"])
    for entity in records:
        mid, pos = entity["id"], entity["position"]
        network = entity.get("electric_network_id")
        if network is not None:
            networks[str(network)].append(mid)
        status = entity["status"]
        if status in ("no_power", "no_fuel", "full_output", "full_burnt_result_output"):
            instructions = {
                "no_power": "Inspect the electrical connection and generation serving this entity.",
                "no_fuel": "Inspect and refill this entity's fuel inventory.",
                "full_output": "Clear this entity's output destination and inspect its removal path.",
                "full_burnt_result_output": "Empty this entity's burnt-result inventory.",
            }
            facts.append(
                {
                    "entity_id": mid,
                    "position": pos,
                    "status": status,
                    "instruction": instructions[status],
                }
            )
        if entity.get("entity_type") == "inserter":
            for side in ("pickup", "drop"):
                if entity.get(side + "_target") is None:
                    facts.append(
                        {
                            "entity_id": mid,
                            "position": entity[side + "_position"],
                            "status": "no_" + side + "_entity",
                            "instruction": f"Inspect the {side} point: no target entity was observed. Ground-item transfers may be intentional.",
                        }
                    )
    return {
        "capture_sha256": digest(capture),
        "tick": capture["tick"],
        "scope": deepcopy(capture["scope"]),
        "patches": patches(capture),
        "diagnostics": facts,
        "network_members_in_scope": dict(sorted(networks.items())),
        "water_tile_count": len(data["water_tiles"]),
        "obstacle_count": len(data["obstacles"]),
        "ungenerated_chunks": list(data["ungenerated_chunks"]),
        "limits": [
            "Distances are straight-line; walking routes and mining reach are not established.",
            "Resources may continue outside the surveyed area; absent resources are not absent from the map.",
            "Direct inserter endpoints do not establish item compatibility, sustained supply, or transport capacity.",
            "Network membership and generator prototype ratings do not establish available generation.",
        ],
    }


def gather(capture, requested):
    """Allocate additional hand-mined minerals; never reuse finite stock or create supply."""
    data = survey_data(capture)
    if not isinstance(requested, dict) or not requested:
        raise ValueError("request at least one additional mineral quantity")
    for item, quantity in requested.items():
        if item not in MINERALS:
            raise ValueError(
                f"hand-mining targets currently support {', '.join(sorted(MINERALS))}; unsupported: {item}"
            )
        integer(quantity, item, positive=True)
    remaining = dict(requested)
    current = capture["player"]["position"]
    candidates = {
        r["id"]: r
        for r in data["resources"]
        if hand_product(r) in requested and r["standable"] and r["amount"] > 0
    }
    steps, distance_total = [], 0.0
    while any(remaining.values()) and candidates:
        useful = [r for r in candidates.values() if remaining[hand_product(r)] > 0]
        if not useful:
            break
        resource = min(
            useful, key=lambda r: (distance(current, r["position"]), r["id"])
        )
        item = hand_product(resource)
        quantity = min(remaining[item], resource["amount"])
        leg = distance(current, resource["position"])
        steps.append(
            {
                "kind": "hand_mine",
                "item": item,
                "quantity": quantity,
                "resource_id": resource["id"],
                "position": deepcopy(resource["position"]),
                "observed_resource_units": resource["amount"],
                "straight_line_distance": leg,
                "route_command": f"/advisor-route {resource['position']['x']:g} {resource['position']['y']:g} {quantity:g}",
                "instruction": f"Approach {resource['position']['x']:g}, {resource['position']['y']:g} and hand-mine {quantity:g} additional {item} from this tile.",
                "completion_check": f"Confirm {quantity:g} newly collected {item}; export again if the tile depleted or access changed.",
            }
        )
        distance_total += leg
        current = resource["position"]
        remaining[item] -= quantity
        del candidates[resource["id"]]
    unplanned = {item: quantity for item, quantity in remaining.items() if quantity}
    return {
        "capture_sha256": digest(capture),
        "tick": capture["tick"],
        "requested_additional": dict(requested),
        "steps": steps,
        "unplanned": unplanned,
        "all_quantities_located": not unplanned,
        "straight_line_distance_total": distance_total,
        "changes_snapshot": False,
        "preconditions": [
            "Check a safe walking route and mining reach before approaching each marked tile.",
            "Keep inventory space for the requested items; existing inventory does not reduce this additional-gather request.",
        ],
        "limits": [
            "Targets are a greedy local sequence, not a verified walking path or an optimal route.",
            "Only finite one-item-per-cycle iron ore, copper ore, coal and stone are allocated.",
            "Tiles obstructing local character placement are excluded; mining them from adjacent positions is not yet planned.",
            "Unplanned quantities require another survey, a larger area, or cleared access. No automatic extraction rate is inferred.",
        ],
    }


def write_map(capture, destination, plan=None):
    """Standalone SVG of observed geometry; arrows are entity endpoints, never inferred belts."""
    data = survey_data(capture)
    (x0, y0), (x1, y1) = data["area"]
    scale, pad = 9, 35
    patch_list = patches(capture)
    shown_patches = patch_list[:12]
    steps = (plan or {}).get("steps", [])
    shown_steps = steps[:8]
    map_right, map_bottom = pad + (x1 - x0) * scale, pad + (y1 - y0) * scale
    width = max(720, map_right + 300)
    height = max(
        map_bottom + 115, 180 + len(shown_patches) * 32 + len(shown_steps) * 38
    )
    root = ET.Element(
        "svg",
        xmlns="http://www.w3.org/2000/svg",
        width=str(width),
        height=str(height),
        viewBox=f"0 0 {width} {height}",
    )
    layer = root

    def node(tag, **attrs):
        return ET.SubElement(
            layer, tag, {k.replace("_", "-"): str(v) for k, v in attrs.items()}
        )

    def xy(p):
        return pad + (p["x"] - x0) * scale, pad + (p["y"] - y0) * scale

    def label(x, y, text, **attrs):
        node(
            "text",
            x=x,
            y=y,
            font_size=11,
            font_family="sans-serif",
            fill="#e2e8f0",
            **attrs,
        ).text = text

    def line(a, b, color, width=1):
        ax, ay = xy(a)
        bx, by = xy(b)
        node("line", x1=ax, y1=ay, x2=bx, y2=by, stroke=color, stroke_width=width)

    node("rect", x=0, y=0, width=width, height=height, fill="#0f172a")
    label(pad, 20, f"Nauvis survey — tick {capture['tick']} (north ↑)")
    definitions = ET.SubElement(root, "defs")
    clip = ET.SubElement(definitions, "clipPath", id="world")
    ET.SubElement(
        clip,
        "rect",
        x=str(pad),
        y=str(pad),
        width=str(map_right - pad),
        height=str(map_bottom - pad),
    )
    layer = ET.SubElement(root, "g", {"clip-path": "url(#world)"})
    node(
        "rect",
        x=pad,
        y=pad,
        width=(x1 - x0) * scale,
        height=(y1 - y0) * scale,
        fill="#253b32",
    )
    for coordinate in range(math.ceil(x0 / 8) * 8, math.ceil(x1 / 8) * 8, 8):
        x, _ = xy({"x": coordinate, "y": y0})
        node(
            "line",
            x1=x,
            x2=x,
            y1=pad,
            y2=map_bottom,
            stroke="#40554a",
            stroke_width=0.5,
        )
    for coordinate in range(math.ceil(y0 / 8) * 8, math.ceil(y1 / 8) * 8, 8):
        _, y = xy({"x": x0, "y": coordinate})
        node(
            "line", x1=pad, x2=map_right, y1=y, y2=y, stroke="#40554a", stroke_width=0.5
        )
    for tile in data["water_tiles"]:
        x, y = xy(tile)
        node("rect", x=x, y=y, width=scale, height=scale, fill="#2563a8")
    colors = {
        "iron-ore": "#93a7bd",
        "copper-ore": "#ed965a",
        "coal": "#101010",
        "stone": "#dccd9b",
        "uranium-ore": "#b5e61d",
        "crude-oil": "#ab75c3",
    }
    for resource in data["resources"]:
        x, y = xy(resource["position"])
        tile = node(
            "rect",
            x=x - scale * 0.43,
            y=y - scale * 0.43,
            width=scale * 0.86,
            height=scale * 0.86,
            fill=colors.get(resource["prototype"], "#aaa"),
        )
        ET.SubElement(
            tile, "title"
        ).text = f"{resource['prototype']}: {resource['amount']} units at {resource['position']}"
    for obstacle in data["obstacles"]:
        box = obstacle["bounding_box"]
        a, b = box["left_top"], box["right_bottom"]
        x, y = xy(a)
        shape = node(
            "rect",
            x=x,
            y=y,
            width=(b["x"] - a["x"]) * scale,
            height=(b["y"] - a["y"]) * scale,
            fill="#556466",
            stroke="#a7b8b8",
            stroke_width=0.6,
        )
        ET.SubElement(shape, "title").text = f"{obstacle['prototype']} {obstacle['id']}"
    drawn = set()
    for a, b in zip((plan or {}).get("route", []), (plan or {}).get("route", [])[1:]):
        line(a, b, "#fbbf24", 2)
    if (plan or {}).get("stand_position"):
        x, y = xy(plan["stand_position"])
        node("circle", cx=x, cy=y, r=4, fill="#fff", stroke="#0f172a", stroke_width=1)
    for entity in data["infrastructure"]:
        for neighbour in entity.get("copper_neighbours", []):
            edge = tuple(sorted((entity["id"], neighbour["id"])))
            if (
                edge not in drawn
                and neighbour.get("built")
                and inside(neighbour["position"], data["area"])
            ):
                line(entity["position"], neighbour["position"], "#e2b566")
                drawn.add(edge)
        if entity.get("entity_type") == "inserter":
            line(entity["pickup_position"], entity["drop_position"], "#67e8f9", 2)
            x, y = xy(entity["drop_position"])
            node("circle", cx=x, cy=y, r=2.5, fill="#67e8f9")
    for i, patch in enumerate(shown_patches, 1):
        x, y = xy(patch["nearest_position"])
        label(
            x - 6 if x + 25 > map_right else x + 5,
            max(pad + 12, y - 8),
            f"P{i}",
            text_anchor="end" if x + 25 > map_right else "start",
        )
    for i, step in enumerate(shown_steps, 1):
        x, y = xy(step["position"])
        node(
            "circle", cx=x, cy=y, r=6, fill="#0f172a", stroke="#fbbf24", stroke_width=2
        )
        label(x, y + 4, str(i), text_anchor="middle")
    x, y = xy(capture["player"]["position"])
    node("circle", cx=x, cy=y, r=5, fill="#f472b6")
    label(x + 8, y + 4, "you" if capture["player"]["index"] else "survey origin")
    layer = root
    for coordinate in range(math.ceil(x0 / 8) * 8, math.ceil(x1 / 8) * 8, 8):
        x, _ = xy({"x": coordinate, "y": y0})
        label(x, map_bottom + 17, str(coordinate), text_anchor="middle")
    for coordinate in range(math.ceil(y0 / 8) * 8, math.ceil(y1 / 8) * 8, 8):
        _, y = xy({"x": x0, "y": coordinate})
        label(pad - 8, y + 4, str(coordinate), text_anchor="end")
    panel_x, row_y = map_right + 25, 49
    label(panel_x, row_y, "RESOURCE PATCHES", font_weight="bold")
    for i, patch in enumerate(shown_patches, 1):
        row_y += 32
        label(panel_x, row_y, f"P{i}  {patch['resource'][:26]}")
        description = (
            "infinite yield; excluded"
            if patch["infinite"]
            else f"{patch['units_observed']:,} observed · {patch['hand_mineable_units']:,} eligible"
        )
        label(panel_x + 20, row_y + 14, description)
    if len(patch_list) > len(shown_patches):
        row_y += 32
        label(
            panel_x,
            row_y,
            f"{len(patch_list) - len(shown_patches)} more patches in the JSON report",
        )
    if shown_steps:
        row_y += 48
        label(panel_x, row_y, "ADDITIONAL HAND-MINING", font_weight="bold")
        for i, step in enumerate(shown_steps, 1):
            row_y += 38
            label(panel_x, row_y, f"{i}.  {step['quantity']:g} {step['item']}")
            point = step["position"]
            label(panel_x + 20, row_y + 14, f"at ({point['x']:g}, {point['y']:g})")
        if len(steps) > len(shown_steps):
            row_y += 34
            label(
                panel_x,
                row_y,
                f"{len(steps) - len(shown_steps)} more targets in the JSON plan",
            )
    label(
        pad,
        height - 49,
        "Blue: water · gray: obstacles · copper: wire links · cyan dot: inserter drop",
    )
    label(
        pad,
        height - 31,
        (
            "Gold line: engine approach · white dot: mining stance · gold circles: mining targets"
            if (plan or {}).get("route")
            else "Gold circles: mining targets · positions/distances do not establish a walking route"
        ),
    )
    label(
        pad,
        height - 13,
        f"Bounds: ({x0:g}, {y0:g}) to ({x1:g}, {y1:g}); resource amounts cover this area only",
    )
    ET.ElementTree(root).write(
        Path(destination), encoding="utf-8", xml_declaration=True
    )
