#!/usr/bin/env python3
"""Inspect a game survey or locate finite, additional hand-mining targets."""

import argparse
import json
from pathlib import Path
import sys

from advisor_core.survey import gather, inspect, write_map


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "gather"):
        sub = commands.add_parser(name)
        sub.add_argument("capture", type=Path)
        if name == "gather":
            sub.add_argument(
                "items", nargs="+", help="additional ITEM=COUNT to hand-mine"
            )
        sub.add_argument("--json", action="store_true")
        sub.add_argument(
            "--map", type=Path, help="write a standalone SVG of the observed area"
        )
    args = parser.parse_args(argv)
    try:
        if args.map and args.map.resolve() == args.capture.resolve():
            raise ValueError("map output must not overwrite the capture")
        capture = json.loads(args.capture.read_text())
        if args.command == "gather":
            requested = {}
            for spec in args.items:
                item, raw = spec.rsplit("=", 1)
                quantity = int(raw)
                if quantity <= 0:
                    raise ValueError("each additional quantity must be positive")
                requested[item] = requested.get(item, 0) + quantity
            result = gather(capture, requested)
        else:
            result = inspect(capture)
        if args.map:
            write_map(capture, args.map, result if args.command == "gather" else None)
        if args.json:
            print(json.dumps(result, indent=2, allow_nan=False))
        elif args.command == "gather":
            print(f"HAND-MINING TARGETS — capture tick {result['tick']}")
            for p in result["preconditions"]:
                print("Before mining: " + p)
            for i, step in enumerate(result["steps"], 1):
                print(f"{i}. {step['instruction']}")
                print("   Request a walking approach in-game: " + step["route_command"])
                print("   " + step["completion_check"])
            for item, quantity in result["unplanned"].items():
                print(
                    f"Still unlocated: {quantity:g} {item}; survey more ground or clear access."
                )
        else:
            print(
                f"SURVEY — tick {result['tick']}; {result['water_tile_count']} water tiles, {result['obstacle_count']} obstacles"
            )
            for p in result["patches"]:
                point = p["nearest_position"]
                print(
                    f"{p['resource']}: {p['units_observed']} units on {p['tiles']} tiles; nearest ({point['x']:g}, {point['y']:g}), {p['straight_line_distance']:.1f} tiles straight-line"
                )
            for d in result["diagnostics"]:
                point = d["position"]
                print(
                    f"Inspect {d['entity_id']} at ({point['x']:g}, {point['y']:g}): {d['status']}. {d['instruction']}"
                )
            print(
                f"Observed electric networks: {len(result['network_members_in_scope'])}; available generation still needs review."
            )
        if not args.json:
            for limit in result["limits"]:
                print("Scope: " + limit)
            if args.map:
                print(f"Map: {args.map}")
        return 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f"survey: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
