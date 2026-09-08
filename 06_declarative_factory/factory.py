"""Typed, anchored blueprint declarations and conservative additive revision plans.

Manifests describe designs, never observed construction or measured throughput.
Only the separate engine harness mutates a disposable test world.
"""

from __future__ import annotations

import base64
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
import re
import zlib

VERSION = "2.1.16"
MODS = {"base": VERSION, "blueprint-gen-observer": "0.3.0"}
DIRECTIONS = {0: (0, -1), 4: (1, 0), 8: (0, 1), 12: (-1, 0)}
# Deliberately small geometry vocabulary. The engine still judges actual placement.
SIZES = {
    "transport-belt": (1, 1),
    "inserter": (1, 1),
    "long-handed-inserter": (1, 1),
    "small-electric-pole": (1, 1),
    "medium-electric-pole": (1, 1),
    "wooden-chest": (1, 1),
    "stone-wall": (1, 1),
    "stone-furnace": (2, 2),
    "burner-mining-drill": (2, 2),
    "assembling-machine-1": (3, 3),
    "assembling-machine-2": (3, 3),
    "lab": (3, 3),
}


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", value):
        raise ValueError(
            "stable names must contain letters, digits, underscores or hyphens"
        )
    return value


@dataclass(frozen=True)
class Tile:
    x: int
    y: int

    def __post_init__(self):
        if any(type(v) is not int or abs(v) > 100000 for v in (self.x, self.y)):
            raise ValueError("tile coordinates must be bounded integers")

    def plus(self, other):
        return Tile(self.x + other.x, self.y + other.y)


@dataclass(frozen=True)
class Port:
    name: str
    io: str
    item: str
    at: Tile
    direction: int
    rate: float  # items per second, advertised design contract, not measured flow
    lane: str = "both"
    kind: str = "belt"

    def __post_init__(self):
        name(self.name)
        name(self.item)
        if self.io not in ("in", "out") or self.kind != "belt":
            raise ValueError("this first adapter supports belt input/output ports only")
        if (
            self.lane not in ("left", "right", "both")
            or self.direction not in DIRECTIONS
        ):
            raise ValueError("invalid lane or cardinal direction")
        if (
            isinstance(self.rate, bool)
            or not isinstance(self.rate, (int, float))
            or not math.isfinite(self.rate)
            or not 0 < self.rate <= (15 if self.lane == "both" else 7.5)
        ):
            raise ValueError("port rate exceeds yellow-belt lane capacity")


@dataclass(frozen=True)
class Asset:
    """Immutable legacy blueprint payload with explicit typed boundary ports."""

    payload: str
    ports: tuple[Port, ...]

    @classmethod
    def from_module_json(cls, document, *, port_names=None):
        d = deepcopy(document)
        for field in ("width", "height"):
            if type(d.get(field)) is not int or not 1 <= d[field] <= 256:
                raise ValueError("module dimensions must be integers from 1 to 256")
        if d.get("tiles"):
            raise ValueError("tile/landfill changes require a separate method")
        entries = d.get("inputs", []) + d.get("outputs", [])
        labels = port_names or tuple(f"{p['io']}-{i}" for i, p in enumerate(entries))
        if len(labels) != len(entries) or len(set(labels)) != len(labels):
            raise ValueError("ports require unique stable names")
        ports = tuple(
            Port(
                label,
                p["io"],
                p["item"],
                Tile(p["x"], p["y"]),
                p["direction"],
                p["rate"],
                p["lane"],
                p["kind"],
            )
            for label, p in zip(labels, entries)
        )
        occupied, centers = set(), {}
        entities = d.get("entities")
        if not isinstance(entities, list) or not 1 <= len(entities) <= 4096:
            raise ValueError("module requires 1 to 4096 entities")
        for entity in entities:
            entity.pop(
                "entity_number", None
            )  # array ordering is not persistent identity
            if set(entity) - {"name", "position", "direction", "recipe"}:
                raise ValueError(
                    "unsupported entity settings; do not silently discard them"
                )
            if entity.get("name") not in SIZES:
                raise ValueError(f"unsupported entity geometry: {entity.get('name')}")
            entity.setdefault("direction", 0)
            if entity["direction"] not in DIRECTIONS:
                raise ValueError("only cardinal entity directions are supported")
            if "recipe" in entity:
                name(entity["recipe"])
            x, y = entity["position"]["x"], entity["position"]["y"]
            w, h = SIZES[entity["name"]]
            if (
                any(
                    isinstance(v, bool)
                    or not isinstance(v, (int, float))
                    or not math.isfinite(v)
                    for v in (x, y)
                )
                or (x - w / 2) % 1
                or (y - h / 2) % 1
            ):
                raise ValueError("entity is not aligned to the tile grid")
            cells = {
                (i, j)
                for i in range(int(x - w / 2), int(x + w / 2))
                for j in range(int(y - h / 2), int(y + h / 2))
            }
            if occupied & cells or any(
                not (0 <= i < d["width"] and 0 <= j < d["height"]) for i, j in cells
            ):
                raise ValueError("entities overlap or leave the module reservation")
            occupied |= cells
            centers[(x, y)] = entity
        for p in ports:
            entity = centers.get((p.at.x + 0.5, p.at.y + 0.5), {})
            if (
                entity.get("name") != "transport-belt"
                or entity.get("direction") != p.direction
            ):
                raise ValueError(
                    "port must sit on a belt pointing in its declared direction"
                )
            if not (p.at.x in (0, d["width"] - 1) or p.at.y in (0, d["height"] - 1)):
                raise ValueError("ports must lie on a module boundary")
        for wire in d.get("wires", []):
            if (
                not isinstance(wire, list)
                or len(wire) != 4
                or any(type(v) is not int for v in wire)
                or not 1 <= wire[0] <= len(entities)
                or not 1 <= wire[2] <= len(entities)
            ):
                raise ValueError("wire references an invalid module entity")
        return cls(json.dumps(d, sort_keys=True, allow_nan=False), ports)

    def document(self):
        return json.loads(self.payload)


@dataclass(frozen=True)
class Module:
    name: str
    asset: Asset
    at: Tile


@dataclass(frozen=True)
class Group:
    name: str
    at: Tile
    children: tuple[Module | Group, ...]  # stable hierarchical addresses


@dataclass(frozen=True)
class Endpoint:
    module: str  # e.g. main/gear-a
    port: str


@dataclass(frozen=True)
class Link:
    name: str
    source: Endpoint
    target: Endpoint
    path: tuple[Tile, ...]  # every belt tile, including both existing endpoints


@dataclass(frozen=True)
class Factory:
    name: str
    children: tuple[Module | Group, ...]
    links: tuple[Link, ...] = ()

    def compile(self):
        name(self.name)
        modules, ports, entities, wires, reservations = {}, {}, {}, [], []

        def flatten(children, origin, prefix):
            seen = set()
            for child in children:
                name(child.name)
                if child.name in seen:
                    raise ValueError("duplicate sibling address")
                seen.add(child.name)
                path = f"{prefix}/{child.name}" if prefix else child.name
                at = origin.plus(child.at)
                if isinstance(child, Group):
                    flatten(child.children, at, path)
                    continue
                if not isinstance(child, Module):
                    raise ValueError("children must be Module or Group instances")
                d = child.asset.document()
                rect = (at.x, at.y, at.x + d["width"], at.y + d["height"])
                for other, r in reservations:
                    if (
                        rect[0] < r[2]
                        and r[0] < rect[2]
                        and rect[1] < r[3]
                        and r[1] < rect[3]
                    ):
                        raise ValueError(
                            f"module reservations overlap: {path} and {other}"
                        )
                reservations.append((path, rect))
                local_ids = []
                for raw in d["entities"]:
                    entity = deepcopy(raw)
                    p = raw["position"]
                    key = f"{path}/entity/{p['x']:g},{p['y']:g}"
                    entity["position"] = {"x": at.x + p["x"], "y": at.y + p["y"]}
                    entities[key] = entity
                    local_ids.append(key)
                for a, ca, b, cb in d.get("wires", []):
                    wires.append([local_ids[a - 1], ca, local_ids[b - 1], cb])
                modules[path] = {
                    "at": [at.x, at.y],
                    "size": [d["width"], d["height"]],
                    "asset_sha256": digest(d),
                }
                for p in child.asset.ports:
                    ports[f"{path}:{p.name}"] = {
                        "io": p.io,
                        "item": p.item,
                        "kind": p.kind,
                        "lane": p.lane,
                        "rate": p.rate,
                        "direction": p.direction,
                        "at": [at.x + p.at.x, at.y + p.at.y],
                        "module": path,
                    }

        flatten(self.children, Tile(0, 0), "")
        used, links, route_cells = set(), {}, set()
        for link in self.links:
            name(link.name)
            if link.name in links:
                raise ValueError("duplicate link address")
            source = f"{link.source.module}:{link.source.port}"
            target = f"{link.target.module}:{link.target.port}"
            if source not in ports or target not in ports:
                raise ValueError("link refers to an unknown port")
            a, b = ports[source], ports[target]
            if source in used or target in used:
                raise ValueError(
                    "fan-out/merging needs explicit splitter modules and separate ports"
                )
            if (
                a["io"] != "out"
                or b["io"] != "in"
                or a["item"] != b["item"]
                or a["kind"] != b["kind"]
                or a["lane"] != "both"
                or b["lane"] != "both"
            ):
                raise ValueError(
                    "link requires matching items and full-belt output/input ports"
                )
            if a["rate"] + 1e-9 < b["rate"]:
                raise ValueError("source cannot cover the target's declared input rate")
            path = link.path
            if not 2 <= len(path) <= 256 or len(set(path)) != len(path):
                raise ValueError("connection must have 2 to 256 unique adjacent tiles")
            if [path[0].x, path[0].y] != a["at"] or [path[-1].x, path[-1].y] != b["at"]:
                raise ValueError("connection endpoints do not match their ports")
            moves = [(q.x - p.x, q.y - p.y) for p, q in zip(path, path[1:])]
            if any(move not in DIRECTIONS.values() for move in moves):
                raise ValueError("connection path must use adjacent cardinal tiles")
            if (
                moves[0] != DIRECTIONS[a["direction"]]
                or moves[-1] != DIRECTIONS[b["direction"]]
            ):
                raise ValueError(
                    "connection must leave/enter in the port flow direction"
                )
            for i, p in enumerate(path[1:-1], 1):
                if (p.x, p.y) in route_cells or any(
                    r[0] <= p.x < r[2] and r[1] <= p.y < r[3] for _, r in reservations
                ):
                    raise ValueError(
                        "connection crosses another route or a module reservation"
                    )
                route_cells.add((p.x, p.y))
                direction = next(
                    d for d, move in DIRECTIONS.items() if move == moves[i]
                )
                entities[f"link/{link.name}/{p.x},{p.y}"] = {
                    "name": "transport-belt",
                    "position": {"x": p.x + 0.5, "y": p.y + 0.5},
                    "direction": direction,
                }
            used.update((source, target))
            links[link.name] = {
                "source": source,
                "target": target,
                "rate": b["rate"],
                "item": b["item"],
                "path": [[p.x, p.y] for p in path],
            }
        external = {k: p for k, p in ports.items() if p["io"] == "in" and k not in used}
        outputs = {k: p for k, p in ports.items() if p["io"] == "out" and k not in used}
        d = {
            "schema_version": 1,
            "name": self.name,
            "factorio_version": VERSION,
            "active_mods": dict(MODS),
            "modules": modules,
            "ports": ports,
            "links": links,
            "entities": entities,
            "wires": sorted(wires),
            "external_inputs": external,
            "unconnected_outputs": outputs,
            "evidence": "compiled design; placement, research, inventory, supply and power need game observation",
        }
        return {**d, "sha256": digest(d)}


def validate_manifest(document):
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("unsupported design manifest")
    if (
        document.get("factorio_version") != VERSION
        or document.get("active_mods") != MODS
    ):
        raise ValueError("manifest profile mismatch")
    if document.get("sha256") != digest(
        {k: v for k, v in document.items() if k != "sha256"}
    ):
        raise ValueError("manifest digest mismatch")
    return document


def plan(desired, previous=None, *, observation=None):
    """Compare design manifests. Replacements/removals are reported and block patch output."""
    validate_manifest(desired)
    if previous is not None:
        validate_manifest(previous)
        if previous["name"] != desired["name"]:
            raise ValueError("cannot reuse state from another factory")
    old = previous["entities"] if previous else {}
    new = desired["entities"]
    add = {key: value for key, value in new.items() if key not in old}
    remove = sorted(set(old) - set(new))
    replace = sorted(key for key in old.keys() & new.keys() if old[key] != new[key])
    old_wires = previous["wires"] if previous else []
    wire_remove = [wire for wire in old_wires if wire not in desired["wires"]]
    wire_add = [wire for wire in desired["wires"] if wire not in old_wires]
    conflicts = []
    if remove or replace or wire_remove:
        conflicts.append(
            "removal, relocation, setting changes or replacement require an explicit migration method"
        )
    # Treat changing an established module's envelope as a migration even if its entities stay put.
    if previous:
        for key in previous["modules"].keys() & desired["modules"].keys():
            a, b = previous["modules"][key], desired["modules"][key]
            if a["at"] != b["at"] or a["size"] != b["size"]:
                conflicts.append(f"module reservation changed: {key}")
    if observation is not None:
        if (
            previous is None
            or observation.get("manifest_sha256") != previous["sha256"]
            or observation.get("active_mods") != MODS
            or observation.get("factorio_version") != VERSION
            or observation.get("source") != "factorio-proving-ground"
        ):
            raise ValueError(
                "observation does not match the baseline design and engine profile"
            )
        for key, expected in old.items():
            actual = observation.get("entities", {}).get(key)
            if not actual or actual.get("configuration") != expected:
                conflicts.append(f"observed drift at {key}; inspect before extending")
    return {
        "schema_version": 1,
        "base_sha256": previous["sha256"] if previous else None,
        "desired_sha256": desired["sha256"],
        "kind": "blocked" if conflicts else "additive",
        "add": add,
        "remove": remove,
        "replace": replace,
        "wire_add": wire_add,
        "retained": sorted(
            key for key in old.keys() & new.keys() if old[key] == new[key]
        ),
        "bill": dict(sorted(Counter(e["name"] for e in add.values()).items())),
        "observation_sha256": digest(observation) if observation is not None else None,
        "conflicts": conflicts,
        "changes_game": False,
        "preconditions": [
            "Refresh the actual game and compare every retained entity before applying.",
            "Check research, available construction inventory, world collisions and reach.",
            "Establish external inputs, power and output handling; then measure actual production.",
        ],
    }


def blueprint(document, change=None):
    validate_manifest(document)
    entities = document["entities"]
    wires = document["wires"]
    if change is not None:
        if (
            change["desired_sha256"] != document["sha256"]
            or change["kind"] != "additive"
        ):
            raise ValueError("cannot export a blocked or mismatched patch")
        entities = dict(change["add"])
        wires = change["wire_add"]
        for a, _, b, _ in wires:
            entities.setdefault(a, document["entities"][a])
            entities.setdefault(b, document["entities"][b])
    ids = {key: i + 1 for i, key in enumerate(sorted(entities))}
    bp = {
        "item": "blueprint",
        "label": document["name"],
        "version": (2 << 48) | (1 << 32) | (16 << 16),
        "description": "Anchored design. Align using absolute positions in the manifest; vanilla cursor placement translates blueprints.",
        "entities": [
            dict(entities[key], entity_number=ids[key]) for key in sorted(entities)
        ],
        "wires": [[ids[a], ca, ids[b], cb] for a, ca, b, cb in wires],
    }
    return (
        "0"
        + base64.b64encode(
            zlib.compress(json.dumps({"blueprint": bp}).encode())
        ).decode()
    )
