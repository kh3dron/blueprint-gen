#!/usr/bin/env python3
"""Factorio recipe rate calculator.

    python recipe.py <item> <rate> [--recipe NAME] [--flat]

<rate> is items per second. Suffix /m for per minute (e.g. 60/m).
"""

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(ROOT), "data")
CACHE = os.path.join(DATA, "recipes.json")
SOURCES = [
    "base/prototypes/recipe.lua",
    "space-age/prototypes/recipe.lua",
    "quality/prototypes/recipe.lua",
    "elevated-rails/prototypes/recipe/elevated-rails.lua",
]

# category -> (machine, crafting_speed). Values from data/*/prototypes/entity/entities.lua.
MACHINES = {
    "crafting": ("assembling-machine-2", 0.75),
    "advanced-crafting": ("assembling-machine-2", 0.75),
    "crafting-with-fluid": ("assembling-machine-2", 0.75),
    "smelting": ("electric-furnace", 2.0),
    "chemistry": ("chemical-plant", 1.0),
    "oil-processing": ("oil-refinery", 1.0),
    "centrifuging": ("centrifuge", 1.0),
    "rocket-building": ("rocket-silo", 1.0),
    "crushing": ("crusher", 1.0),
    "metallurgy": ("foundry", 4.0),
    "organic": ("biochamber", 2.0),
    "electromagnetics": ("electromagnetic-plant", 2.0),
    "cryogenics": ("cryogenic-plant", 2.0),
    "captive-spawner-process": ("captive-biter-spawner", 1.0),
}
SOURCE_RANK = {s: i for i, s in enumerate(SOURCES)}
MACHINES_BY_NAME = {m: s for m, s in MACHINES.values()}
MACHINES_BY_NAME.update({"assembling-machine-1": 0.5, "assembling-machine-3": 1.25})

# Mined / pumped inputs. Never expanded. From data/*/prototypes/entity/resources.lua plus water.
RAW = {
    "iron-ore",
    "copper-ore",
    "coal",
    "stone",
    "uranium-ore",
    "crude-oil",
    "water",
    "tungsten-ore",
    "calcite",
    "scrap",
    "lithium-brine",
    "fluorine",
}
LAST_RESORT = ("-recycling", "-reprocessing", "-crushing")


def load_recipes():
    srcs = [os.path.join(DATA, s) for s in SOURCES]
    if not os.path.exists(CACHE) or any(
        os.path.getmtime(s) > os.path.getmtime(CACHE) for s in srcs
    ):
        with open(CACHE, "w") as f:
            subprocess.run(
                ["luajit", os.path.join(ROOT, "extract.lua")] + srcs,
                stdout=f,
                check=True,
            )
    with open(CACHE) as f:
        recipes = json.load(f)
    return [
        r
        for r in recipes
        if not r.get("parameter") and not r.get("hidden") and r.get("results")
    ]


def expected_amount(res):
    if "amount" in res:
        amt = res["amount"]
    else:
        amt = (res["amount_min"] + res["amount_max"]) / 2
    prob = res.get("probability", 1.0)
    if "shared_probability" in res:
        prob = res["shared_probability"]["max"] - res["shared_probability"]["min"]
    return amt * prob


def net_output(recipe, item):
    out = sum(expected_amount(r) for r in recipe["results"] if r["name"] == item)
    back = sum(i["amount"] for i in recipe["ingredients"] if i["name"] == item)
    return out - back


def build_index(recipes):
    by_product = defaultdict(list)
    for r in recipes:
        for res in r["results"]:
            if net_output(r, res["name"]) > 0:
                by_product[res["name"]].append(r)
    for item, rs in by_product.items():
        rs.sort(
            key=lambda r: (
                r["name"] != item,
                r["name"].endswith(LAST_RESORT),
                len(r["results"]),
                SOURCE_RANK.get(os.path.relpath(r["__src"], DATA), 99),
            )
        )
    return by_product


def parse_rate(s):
    if s.endswith("/m"):
        return float(s[:-2]) / 60
    if s.endswith("/s"):
        return float(s[:-2])
    return float(s)


def machine_for(recipe):
    for c in recipe.get("categories") or ["crafting"]:
        if c in MACHINES:
            return MACHINES[c]
    return ("?", 1.0)


def fmt(x):
    return f"{x:.4g}"


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("item")
    ap.add_argument("rate", help="items/s; use N/m for per minute")
    ap.add_argument(
        "--recipe",
        action="append",
        default=[],
        help="force a recipe by name for its product (repeatable)",
    )
    ap.add_argument("--flat", action="store_true", help="only print totals, no tree")
    args = ap.parse_args()

    recipes = load_recipes()
    by_name = {r["name"]: r for r in recipes}
    by_product = build_index(recipes)
    forced = {}
    for name in args.recipe:
        if name not in by_name:
            sys.exit(f"unknown recipe: {name}")
        for res in by_name[name]["results"]:
            if net_output(by_name[name], res["name"]) > 0:
                forced[res["name"]] = by_name[name]

    if args.item not in by_product and args.item not in forced:
        sys.exit(f"no recipe produces {args.item!r}")

    rate = parse_rate(args.rate)
    totals = defaultdict(float)  # item -> items/s (all demand)
    machines = defaultdict(float)  # recipe name -> machine count
    raw = defaultdict(float)  # leaf items -> items/s
    alternatives = {}
    lines = []

    def expand(item, r, depth, stack):
        totals[item] += r
        recipe = forced.get(item) or (
            by_product[item][0] if by_product.get(item) else None
        )
        pad = "  " * depth
        if item in RAW:
            recipe = None
        if recipe is None or item in stack:
            raw[item] += r
            lines.append(f"{pad}{item}  {fmt(r)}/s  [raw]")
            return
        opts = by_product.get(item, [])
        if len(opts) > 1:
            alternatives[item] = [o["name"] for o in opts]
        per_craft = net_output(recipe, item)
        crafts = r / per_craft
        time = recipe.get("energy_required", 0.5)
        machine, speed = machine_for(recipe)
        n = crafts * time / speed
        machines[recipe["name"]] += n
        tag = "" if recipe["name"] == item else f"  via {recipe['name']}"
        lines.append(f"{pad}{item}  {fmt(r)}/s  {fmt(n)}x {machine}{tag}")
        for ing in recipe["ingredients"]:
            if ing["name"] == item:
                continue  # catalyst; already netted in per_craft
            expand(ing["name"], crafts * ing["amount"], depth + 1, stack | {item})

    expand(args.item, rate, 0, frozenset())

    if not args.flat:
        print("\n".join(lines))
        print()
    print("MACHINES")
    for name, n in sorted(machines.items(), key=lambda kv: -kv[1]):
        m, _ = machine_for(by_name[name])
        print(f"  {n:8.2f}  {m:<22} {name}")
    print("RAW")
    for item, r in sorted(raw.items(), key=lambda kv: -kv[1]):
        print(f"  {r:8.3f}/s  {item}")
    if alternatives:
        print("ALTERNATIVE RECIPES (override with --recipe NAME)")
        for item, names in alternatives.items():
            print(f"  {item}: {', '.join(names)}")


if __name__ == "__main__":
    main()
