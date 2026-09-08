#!/usr/bin/env python3
"""Read-only advisor experiment. Run `python3 advisor.py --help` for examples."""
import argparse
import json
import sys

from advisor_core.construction import bill
from advisor_core.model import Snapshot
from advisor_core.planner import next_step
from advisor_core.production import analyze, completion
from advisor_core.rules import DEFAULT_RULES, Rules


def show_bill(result):
    print("Construction checklist (quantities are items; this does not change the snapshot):")
    if result["requires_research"]:
        print("  Research needed: " + ", ".join(result["requires_research"]))
    if result["inventory_used"]:
        print("  Reserve inventory: " + ", ".join(f"{n:g} {i}" for i, n in result["inventory_used"].items()))
    for i, step in enumerate(result["steps"], 1):
        kind = step["kind"]
        if kind in ("gather", "supply", "place"):
            text = f"{kind.capitalize()} {step['quantity']:g} {step['item']}"
            if kind == "gather":
                text = (f"Chop trees to collect {step['quantity']:g} wood" if step["item"] == "wood"
                        else f"Hand-mine {step['quantity']:g} {step['item']}")
            if step.get("check"):
                text += ". " + step["check"]
        else:
            outputs = ", ".join(f"{q:g} {item}" for item, q in step["outputs"].items())
            text = f"{kind.capitalize()} {outputs} ({step['crafts']} crafts of {step['recipe']})"
            if kind == "smelt":
                text += f" in {step['machine']}; load {step['coal']} coal; {step['processing_seconds']:g} machine-seconds"
            if step.get("requires_research"):
                text += "; first research " + ", ".join(step["requires_research"])
        print(f"  {i}. {text}")
    if result["unsupported"]:
        print("  Unsupported: " + "; ".join(result["unsupported"]))
    print(f"  Handcraft time: {result['handcraft_seconds']:g}s; stone-furnace work: {result['smelting_machine_seconds']:g}s")
    print("  " + result["note"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules", default=str(DEFAULT_RULES), help="explicit ruleset JSON")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("next", "analyze", "bill"):
        sub = commands.add_parser(name)
        sub.add_argument("snapshot", help="observed-state JSON; never written by these commands")
        sub.add_argument("--json", action="store_true", help="machine-readable result")
        if name == "bill":
            sub.add_argument("items", nargs="+", help="ITEM=COUNT, e.g. stone-furnace=2")
    commands.add_parser("profile", help="show the pinned profile and content hash")
    args = parser.parse_args(argv)
    try:
        rules = Rules.load(args.rules)
        if args.command == "profile":
            print(json.dumps({"ruleset_id": rules.id, "ruleset_sha256": rules.digest,
                              "factorio_version": rules.document["factorio_version"],
                              "mods": rules.document["mods"], "provenance": rules.document["provenance"]}, indent=2))
            return 0
        snapshot = Snapshot.load(args.snapshot, rules)
        if args.command == "next":
            result = next_step(snapshot, rules)
        elif args.command == "bill":
            requested = {}
            for spec in args.items:
                item, raw = spec.rsplit("=", 1)
                requested[item] = requested.get(item, 0) + int(raw)
            result = bill(snapshot, rules, requested)
        else:
            result = analyze(snapshot, rules)
            result["completion"] = completion(snapshot, rules, result)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        elif args.command == "bill":
            show_bill(result)
        elif args.command == "next":
            print(f"{result['kind'].upper()}: {result['title']}")
            print("Why: " + result["why"])
            for gap in result.get("observation_gaps", []):
                print("Observe: " + gap)
            if "construction" in result:
                show_bill(result["construction"])
            for flag, text in (("placement_pending", "World placement and connection quantities still require a layout plan."),
                               ("extraction_plan_pending", "Mining placement and extraction equipment are not yet planned.")):
                if result.get(flag):
                    print("Pending: " + text)
            print("Check: " + result["completion_check"])
            print(f"Based on revision {result['snapshot_revision']}, tick {result['snapshot_tick']}. Import a new snapshot after acting.")
        else:
            print(f"FLOW BOUND: {result['goal_fraction']:.1%} of every requested target")
            for item, value in result["goal_delivery_per_min"].items():
                print(f"  {item}: {value:.4g}/min (optimistic bound)")
            print(f"  Modeled electric load: {result['electric_kw']:.4g} kW")
            for disabled in result["disabled"]:
                print(f"  {disabled['machine_id']}: {disabled['reason']}")
            print("OBSERVED COMPLETE: " + str(result["completion"]["complete"]))
            for reason in result["completion"]["reasons"]:
                print("  " + reason)
            for assumption in result["assumptions"]:
                print("Assumption: " + assumption)
        return 0
    except (ValueError, KeyError, TypeError, OSError, ArithmeticError) as error:
        print(f"advisor: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
