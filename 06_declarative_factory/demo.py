#!/usr/bin/env python3
"""Declare two anchored revisions using an adapted existing gear blueprint."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from factory import Asset, Endpoint, Factory, Group, Link, Module, Tile, blueprint, plan

HERE = Path(__file__).resolve().parent


def gear_asset():
    d = json.loads((HERE / "assets/legacy-gear.module.json").read_text())
    # Explicit adapter: the legacy starter-machine template still uses a medium pole.
    # This revision substitutes a small pole in the same tile, leaving the source untouched.
    for entity in d["entities"]:
        if entity["name"] == "medium-electric-pole":
            entity["name"] = "small-electric-pole"
    d["notes"].append("Adapter substitutes small pole; power supply remains external.")
    return Asset.from_module_json(d, port_names=("iron", "gears"))


def feed_asset():
    # Two independent reserved feed columns. A future shared main-bus splitter/tap
    # module can expose the same boundary, after its routing and throughput are checked.
    d = {
        "name": "reserved-iron-feeds",
        "width": 25,
        "height": 5,
        "entities": [
            {
                "name": "transport-belt",
                "position": {"x": x + 0.5, "y": y + 0.5},
                "direction": 0,
            }
            for x in (0, 24)
            for y in range(5)
        ],
        "inputs": [],
        "outputs": [],
        "wires": [],
    }
    for x in (0, 24):
        for io, y in (("in", 4), ("out", 0)):
            d["inputs" if io == "in" else "outputs"].append(
                {
                    "io": io,
                    "kind": "belt",
                    "item": "iron-plate",
                    "lane": "both",
                    "x": x,
                    "y": y,
                    "direction": 0,
                    "rate": 2,
                }
            )
    return Asset.from_module_json(
        d, port_names=("supply-a", "supply-b", "socket-a", "socket-b")
    )


def declarations():
    gears = gear_asset()
    feed = Module("feeds", feed_asset(), Tile(0, 10))
    a = Module("gear-a", gears, Tile(0, 0))
    b = Module("gear-b", gears, Tile(24, 0))
    first = Factory(
        "gear-capacity",
        (Group("main", Tile(0, 0), (feed, a)),),
        (
            Link(
                "feed-a",
                Endpoint("main/feeds", "socket-a"),
                Endpoint("main/gear-a", "iron"),
                tuple(Tile(0, y) for y in range(10, 2, -1)),
            ),
        ),
    )
    second = replace(
        first,
        children=(Group("main", Tile(0, 0), (feed, a, b)),),
        links=first.links
        + (
            Link(
                "feed-b",
                Endpoint("main/feeds", "socket-b"),
                Endpoint("main/gear-b", "iron"),
                tuple(Tile(24, y) for y in range(10, 2, -1)),
            ),
        ),
    )
    return first, second


def write_map(manifest, path, change):
    svg = ET.Element(
        "svg",
        xmlns="http://www.w3.org/2000/svg",
        width="980",
        height="570",
        viewBox="0 0 980 570",
    )
    ET.SubElement(svg, "rect", width="980", height="570", fill="#0f172a")

    def label(x, y, text, size=15, fill="#e2e8f0"):
        ET.SubElement(
            svg,
            "text",
            x=str(x),
            y=str(y),
            fill=fill,
            attrib={"font-family": "sans-serif", "font-size": str(size)},
        ).text = text

    label(30, 30, "Declarative gear modules: preserve the first, attach the second", 20)
    for key, m in manifest["modules"].items():
        x, y = m["at"]
        w, h = m["size"]
        ET.SubElement(
            svg,
            "rect",
            x=str(40 + x * 20),
            y=str(85 + y * 20),
            width=str(w * 20),
            height=str(h * 20),
            fill="#1e293b",
            stroke="#64748b",
        )
        label(40 + x * 20, 75 + y * 20, key, 13)
    for key, e in manifest["entities"].items():
        x, y = e["position"]["x"], e["position"]["y"]
        color = "#fbbf24" if key in change["add"] else "#38bdf8"
        if e["name"].startswith("assembling"):
            ET.SubElement(
                svg,
                "rect",
                x=str(40 + (x - 1.4) * 20),
                y=str(85 + (y - 1.4) * 20),
                width="56",
                height="56",
                fill=color,
                opacity="0.7",
            )
        else:
            ET.SubElement(
                svg,
                "circle",
                cx=str(40 + x * 20),
                cy=str(85 + y * 20),
                r="5",
                fill=color,
            )
    label(40, 465, "Blue: retained entities    Gold: additions")
    label(
        40,
        495,
        f"{len(change['retained'])} retained; {len(change['add'])} added; no relocation",
    )
    label(
        40,
        525,
        "Design contracts: 60 → 120 gears/min. External iron and power still required.",
    )
    path.write_text(ET.tostring(svg, encoding="unicode") + "\n")


def build(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    first, second = (factory.compile() for factory in declarations())
    initial, incremental = plan(first), plan(second, first)
    for label, document in (
        ("first", first),
        ("expanded", second),
        ("initial-plan", initial),
        ("incremental-plan", incremental),
    ):
        (destination / f"{label}.json").write_text(
            json.dumps(document, indent=2) + "\n"
        )
    (destination / "expanded.blueprint.txt").write_text(blueprint(second) + "\n")
    (destination / "additions.blueprint.txt").write_text(
        blueprint(second, incremental) + "\n"
    )
    write_map(second, destination / "expansion.svg", incremental)
    return first, second, initial, incremental


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        _, _, _, change = build(args.out)
        print(
            json.dumps(
                {k: change[k] for k in ("kind", "bill", "conflicts", "preconditions")},
                indent=2,
            )
        )
        print(
            f"Retained {len(change['retained'])}; added {len(change['add'])}. Artifacts: {args.out}"
        )
    except (ValueError, OSError) as error:
        parser.exit(2, f"declarative-demo: {error}\n")
