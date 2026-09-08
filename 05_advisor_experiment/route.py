#!/usr/bin/env python3
"""Read an engine walking-approach receipt and print its remaining instructions."""

import argparse
import json
from pathlib import Path
import sys

from advisor_core.routes import compile_route, map_plan
from advisor_core.survey import write_map


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--current-tick",
        type=int,
        help="reject receipts more than 10 simulated seconds old",
    )
    parser.add_argument(
        "--survey", type=Path, help="matching recent survey for the optional map"
    )
    parser.add_argument("--map", type=Path)
    args = parser.parse_args(argv)
    try:
        if bool(args.map) != bool(args.survey):
            raise ValueError("--map and --survey must be supplied together")
        if args.map and args.map.resolve() in (
            args.receipt.resolve(),
            args.survey.resolve(),
        ):
            raise ValueError("map must not overwrite an input")
        receipt = json.loads(args.receipt.read_text())
        plan = compile_route(receipt, current_tick=args.current_tick)
        if args.map:
            if plan["kind"] != "walk_then_mine":
                raise ValueError("cannot map an unusable or stale route")
            capture = json.loads(args.survey.read_text())
            write_map(capture, args.map, map_plan(receipt, capture))
        if args.json:
            print(json.dumps(plan, indent=2, allow_nan=False))
        else:
            print(
                f"{plan['kind'].upper()} — engine observation at tick {plan['based_on_tick']}"
            )
            for reason in plan.get("reasons", []):
                print(reason)
            for precondition in plan.get("preconditions", []):
                print("Before starting: " + precondition)
            for i, instruction in enumerate(plan["instructions"], 1):
                print(f"{i}. {instruction}")
            if plan.get("completion_check"):
                print("Check: " + plan["completion_check"])
            for limit in plan.get("limits", []):
                print("Scope: " + limit)
            if args.map:
                print(f"Map: {args.map}")
        return 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f"route: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
