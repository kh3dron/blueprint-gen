#!/usr/bin/env python3
"""Stitch modules over a bus into one composite module.

    python compose.py <name> <spec>... [--belt NAME] [--export ITEM]... [-o DIR] [--no-render]
    python compose.py <item> <rate>  [--from-plates] [--no-smelting] [--raw ITEM]... [--belt NAME] [-o DIR] [--no-render]
    ... [--roboports [SPACING]]   reserve a roboport grid (bottom-left first, every SPACING tiles, default 48)

<spec> is either a path to a .module.json or item=rate (generated on the fly with templates.py).
The second form is factory mode: the recipe tree of <item> is expanded with the 01 calculator,
one module is generated per intermediate at its total rate, and mined/pumped resources, --raw
items, and recipes the templates cannot build (fluids, >4 ingredients, unsupported category)
become external inputs. --from-plates = --raw iron-plate --raw copper-plate (smelting handled
elsewhere); --no-smelting treats every smelting-category product (plates, steel, bricks) as raw.
Output name is <item>-factory.
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


def load_spec(spec, rt, by_product, belt):
    """Returns ("module", Module) for a file or ("plan", plan) for item=rate."""
    if os.path.exists(spec):
        return ("module", Module.load(spec))
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
    return ("plan", templates.plan(item, rt.parse_rate(rate), recipe, rt, machine=machine, belt=belt))


def is_rate(s):
    try:
        float(s[:-2] if s.endswith(("/s", "/m")) else s)
        return True
    except ValueError:
        return False


def factory(item, rate, rt, by_product, raw, belt, no_smelting=False):
    """Plans for every craftable intermediate of `item`, each at its summed rate. Returns (plans, externals)."""
    totals = {}
    order = []          # first-visit order, leaves last
    blocked = {}        # item -> reason it is treated as raw

    def buildable(it):
        if it in raw or it in rt.RAW or it not in by_product:
            return False
        r = by_product[it][0]
        if no_smelting and "smelting" in (r.get("categories") or []):
            blocked[it] = "smelting"
            return False
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
    plans, externals = [], []
    for it in order:
        if buildable(it):
            recipe = by_product[it][0]
            cats = recipe.get("categories") or ["crafting"]
            machine = next(make.CATEGORY_MACHINE[c] for c in cats if c in make.CATEGORY_MACHINE)
            plans.append(templates.plan(it, totals[it], recipe, rt, machine=machine, belt=belt))
        else:
            externals.append((it, totals[it], blocked.get(it, "raw")))
    return plans, externals


def topo_sort(modules):
    """Producers before consumers. Stable for independent modules."""
    produced_by = {}
    for i, m in enumerate(modules):
        for p in m.outputs:
            produced_by.setdefault(p.item, []).append(i)   # every column of the producer
    order, seen, visiting = [], set(), set()

    def visit(i):
        if i in seen:
            return
        if i in visiting:
            sys.exit(f"cycle through {modules[i].name}")
        visiting.add(i)
        for p in modules[i].inputs:
            for j in produced_by.get(p.item, []):
                if j != i:
                    visit(j)
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
    ap.add_argument("--cells", type=int, help="machines per column (default: unlimited; columns split only for belt capacity)")
    ap.add_argument("--tune", action="store_true", help="lay out --cells neighbours (+-3) and keep the smallest real area")
    ap.add_argument("--one-sided", action="store_true", help="modules on the north side of the bus only")
    ap.add_argument("--roboports", nargs="?", const=48, type=int, metavar="SPACING",
                    help="reserve a roboport grid: first at the bottom-left, then every SPACING tiles (default 48; 50 is the connection limit)")
    ap.add_argument("--from-plates", action="store_true", help="factory mode: iron-plate and copper-plate are external inputs")
    ap.add_argument("--no-smelting", action="store_true", help="factory mode: every smelting recipe's product is an external input")
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
            raw = set(args.raw) | ({"iron-plate", "copper-plate"} if args.from_plates else set())
            plans, externals = factory(args.name, rt.parse_rate(args.specs[0]), rt, by_product, raw, args.belt,
                                       no_smelting=args.no_smelting)
            fixed = []
        except ValueError as ex:
            sys.exit(str(ex))
        name = args.name + "-factory"
        print(f"factory {args.name}: {len(plans)} intermediates, {len(externals)} external inputs")
        for it, r, why in externals:
            print(f"  external {it:<24} {r:.3g}/s  ({why})")
        if not plans:
            sys.exit(f"{args.name}: nothing to build ({externals[0][2]})")
    else:
        loaded = [load_spec(s, rt, by_product, args.belt) for s in args.specs]
        plans = [x for kind, x in loaded if kind == "plan"]
        fixed = [x for kind, x in loaded if kind == "module"]
        externals = []
    cells = args.cells or max([pl["n"] for pl in plans] + [1])      # default: no height balancing, minimum columns

    def layout(T):
        mods = fixed + [m for pl in plans for m in templates.build_from_plan(pl, columns=-(-pl["n"] // T))]
        return bus.compose(name, topo_sort(mods), belt=args.belt, exports=args.export, roboport=args.roboports,
                           two_sided=not args.one_sided)

    max_n = max([pl["n"] for pl in plans] + [1])
    candidates = [cells] if (args.cells or not args.tune or not plans) else sorted({max(1, min(max_n, cells + d)) for d in range(-3, 4)})
    mod, best = None, None
    for T in candidates:
        try:
            m = layout(T)
        except ValueError as ex:
            if len(candidates) == 1:
                sys.exit(str(ex))
            print(f"cells {T}: {ex}", file=sys.stderr)
            continue
        area = m.width * m.height
        print(f"cells {T}: {m.width}x{m.height} = {area}", file=sys.stderr)
        if best is None or area < best:
            mod, best, cells = m, area, T
    if mod is None:
        sys.exit("no layout succeeded")
    if plans:
        print(f"columns sized for {cells} machine(s) per column")
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
