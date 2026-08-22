#!/usr/bin/env python3
"""Stitch modules over a bus into one composite module.

    python compose.py <name> <spec>... [--belt NAME] [--export ITEM]... [-o DIR] [--no-render]
    python compose.py <item> <rate>  [--raw ITEM]... [--belt NAME] [-o DIR] [--no-render]

<spec> is either a path to a .module.json or item=rate (generated on the fly with templates.py).
The second form is factory mode: the recipe tree of <item> is expanded with the 01 calculator,
one module is generated per intermediate at its total rate, and mined/pumped resources, --raw
items, and recipes the templates cannot build (fluids, >4 ingredients, unsupported category)
become external inputs. Output name is <item>-factory.
Modules are ordered producers-before-consumers automatically. Items consumed but not produced
become external inputs (bottom-left risers); items produced but not consumed (or named with
--export) become outputs (bottom-right drops).

Writes <DIR>/<name>.module.json, <DIR>/<name>.txt, <DIR>/<name>.png.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from module import Module, port_table  # noqa: E402
import bus  # noqa: E402
import make  # noqa: E402
import templates  # noqa: E402


def load_spec(spec, rt, by_product):
    if os.path.exists(spec):
        return Module.load(spec)
    if "=" not in spec:
        sys.exit(f"spec {spec!r}: not a file and not item=rate")
    item, rate = spec.split("=", 1)
    recipe = by_product.get(item)
    if not recipe:
        sys.exit(f"no recipe produces {item!r}")
    recipe = recipe[0]
    cats = recipe.get("categories") or ["crafting"]
    machine = next((make.CATEGORY_MACHINE[c] for c in cats if c in make.CATEGORY_MACHINE), None)
    if machine is None:
        sys.exit(f"recipe {recipe['name']} categories {cats}: no supported machine")
    return templates.build(item, rt.parse_rate(rate), recipe, rt, machine=machine)


def is_rate(s):
    try:
        float(s[:-2] if s.endswith(("/s", "/m")) else s)
        return True
    except ValueError:
        return False


def factory(item, rate, rt, by_product, raw, belt):
    """Modules for every craftable intermediate of `item`, each at its summed rate. Returns (modules, externals)."""
    totals = {}
    order = []          # first-visit order, leaves last
    blocked = {}        # item -> reason it is treated as raw

    def buildable(it):
        if it in raw or it in rt.RAW or it not in by_product:
            return False
        r = by_product[it][0]
        ings = r["ingredients"]
        if any(i["type"] == "fluid" for i in ings) or any(x["type"] == "fluid" for x in r["results"]):
            blocked[it] = "fluid"
            return False
        if not 1 <= len(ings) <= 4:
            blocked[it] = f"{len(ings)} ingredients"
            return False
        cats = r.get("categories") or ["crafting"]
        if not any(c in make.CATEGORY_MACHINE for c in cats):
            blocked[it] = f"category {cats}"
            return False
        return True

    def walk(it, r):
        totals[it] = totals.get(it, 0.0) + r
        if it not in order:
            order.append(it)
        if not buildable(it):
            return
        recipe = by_product[it][0]
        crafts = r / rt.net_output(recipe, it)
        for ing in recipe["ingredients"]:
            if ing["name"] != it:
                walk(ing["name"], crafts * ing["amount"])

    walk(item, rate)
    modules, externals = [], []
    for it in order:
        if buildable(it):
            recipe = by_product[it][0]
            cats = recipe.get("categories") or ["crafting"]
            machine = next(make.CATEGORY_MACHINE[c] for c in cats if c in make.CATEGORY_MACHINE)
            modules.append(templates.build(it, totals[it], recipe, rt, machine=machine, belt=belt))
        else:
            externals.append((it, totals[it], blocked.get(it, "raw")))
    return modules, externals


def topo_sort(modules):
    """Producers before consumers. Stable for independent modules."""
    produced_by = {}
    for i, m in enumerate(modules):
        for p in m.outputs:
            produced_by.setdefault(p.item, i)
    order, seen, visiting = [], set(), set()

    def visit(i):
        if i in seen:
            return
        if i in visiting:
            sys.exit(f"cycle through {modules[i].name}")
        visiting.add(i)
        for p in modules[i].inputs:
            if p.item in produced_by and produced_by[p.item] != i:
                visit(produced_by[p.item])
        visiting.discard(i)
        seen.add(i)
        order.append(modules[i])

    for i in range(len(modules)):
        visit(i)
    return order


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name")
    ap.add_argument("specs", nargs="+")
    ap.add_argument("--belt", default="transport-belt", choices=sorted(bus.LANE_CAPACITY))
    ap.add_argument("--export", action="append", default=[], help="also export this item (repeatable)")
    ap.add_argument("--raw", action="append", default=[], help="factory mode: treat this item as an external input (repeatable)")
    ap.add_argument("-o", "--out-dir", default=os.path.join(HERE, "out"))
    ap.add_argument("--no-render", action="store_true")
    args = ap.parse_args()

    rt = make.load_recipe_tool()
    by_product = rt.build_index(rt.load_recipes())
    name = args.name
    if len(args.specs) == 1 and is_rate(args.specs[0]) and not os.path.exists(args.name):
        if args.name not in by_product:
            sys.exit(f"no recipe produces {args.name!r}")
        try:
            modules, externals = factory(args.name, rt.parse_rate(args.specs[0]), rt, by_product, set(args.raw), args.belt)
        except ValueError as ex:
            sys.exit(str(ex))
        name = args.name + "-factory"
        print(f"factory {args.name}: {len(modules)} modules, {len(externals)} external inputs")
        for it, r, why in externals:
            print(f"  external {it:<24} {r:.3g}/s  ({why})")
        if not modules:
            sys.exit(f"{args.name}: nothing to build ({externals[0][2]})")
    else:
        modules = [load_spec(s, rt, by_product) for s in args.specs]
    modules = topo_sort(modules)
    try:
        mod = bus.compose(name, modules, belt=args.belt, exports=args.export)
    except ValueError as ex:
        sys.exit(str(ex))
    problems = mod.check()
    if problems:
        sys.exit("composite check failed:\n  " + "\n  ".join(problems[:20]))

    os.makedirs(args.out_dir, exist_ok=True)
    base = os.path.join(args.out_dir, name)
    mod.save(base + ".module.json")
    with open(base + ".txt", "w") as f:
        f.write(mod.to_string() + "\n")
    print(f"{mod.name}: {mod.width}x{mod.height} tiles, {len(mod.entities)} entities, {len(mod.wires)} wires")
    for n in mod.notes:
        print("  " + n)
    print(port_table(mod))
    print(f"wrote {base}.module.json, {base}.txt", flush=True)
    if not args.no_render:
        render = os.path.join(ROOT, "02_blueprint_visualizer", "render.py")
        subprocess.run([sys.executable, render, "-", "-o", base + ".png", "--tile", "32"],
                       input=json.dumps(mod.render_json()), text=True, check=True)


if __name__ == "__main__":
    main()
