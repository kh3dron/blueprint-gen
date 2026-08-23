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
import fluidcells  # noqa: E402

OIL = {"petroleum-gas", "heavy-oil", "light-oil"}


def has_fluid(recipe):
    return any(i["type"] == "fluid" for i in recipe["ingredients"]) or any(r["type"] == "fluid" for r in recipe["results"])


def build_plan(pl, columns=None):
    if pl.get("kind") == "fluid":
        return fluidcells.build_from_plan(pl, columns)
    return templates.build_from_plan(pl, columns)


def oil_plans(demand, rt, by_name, belt):
    """Advanced oil processing sized for petroleum-gas / heavy-oil / light-oil demand, with all surplus
    heavy and light oil cracked. Returns plans for the refinery and the two cracking steps."""
    P, Hd, Ld = demand.get("petroleum-gas", 0.0), demand.get("heavy-oil", 0.0), demand.get("light-oil", 0.0)
    c = (P + 0.5 * Hd + (2 / 3) * Ld) / 97.5           # refinery crafts/s: 55 + 30 + 12.5 petgas per craft when all cracked
    c = max(c, Hd / 25, Ld / 45)
    hc = max(0.0, (25 * c - Hd) / 40)                   # heavy cracking crafts/s
    lc = max(0.0, (45 * c + 30 * hc - Ld) / 30)         # light cracking crafts/s
    plans = []
    for name, crafts in (("advanced-oil-processing", c), ("heavy-oil-cracking", hc), ("light-oil-cracking", lc)):
        if crafts > 1e-9:
            plans.append(fluidcells.plan(by_name[name], crafts, rt, belt=belt))
    return plans


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
    if has_fluid(recipe):
        crafts = rt.parse_rate(rate) / rt.net_output(recipe, item)
        return ("plan", fluidcells.plan(recipe, crafts, rt, belt=belt))
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


def factory(item, rate, rt, by_product, by_name, raw, belt, no_smelting=False):
    """Plans for every craftable intermediate of `item`, each at its summed rate. Returns (plans, externals)."""
    totals = {}
    order = []          # first-visit order, leaves last
    blocked = {}        # item -> reason it is treated as raw

    oil_demand = {}

    def buildable(it):
        if it in raw or it in rt.RAW or it not in by_product:
            return False
        if it in OIL:
            return True                              # handled by oil_plans()
        r = by_product[it][0]
        if no_smelting and "smelting" in (r.get("categories") or []):
            blocked[it] = "smelting"
            return False
        ings = r["ingredients"]
        if has_fluid(r):
            try:
                fluidcells.plan(r, 1.0, rt, belt=belt)
                return True
            except ValueError as ex:
                blocked[it] = str(ex)
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
        if it in OIL:
            oil_demand[it] = oil_demand.get(it, 0.0) + r
            return
        recipe = by_product[it][0]
        crafts = r / rt.net_output(recipe, it)
        for ing in recipe["ingredients"]:
            if ing["name"] != it:
                walk(ing["name"], crafts * ing["amount"])

    walk(item, rate)
    plans, externals = [], []
    for it in order:
        if not buildable(it):
            externals.append((it, totals[it], blocked.get(it, "raw")))
        elif it in OIL:
            continue
        else:
            recipe = by_product[it][0]
            if has_fluid(recipe):
                plans.append(fluidcells.plan(recipe, totals[it] / rt.net_output(recipe, it), rt, belt=belt))
                for ing in recipe["ingredients"]:               # fluid raws feed in from outside
                    if ing["type"] == "fluid" and ing["name"] in rt.RAW and ing["name"] not in [e[0] for e in externals]:
                        externals.append((ing["name"], totals.get(ing["name"], 0.0), "raw"))
                continue
            cats = recipe.get("categories") or ["crafting"]
            machine = next(make.CATEGORY_MACHINE[c] for c in cats if c in make.CATEGORY_MACHINE)
            plans.append(templates.plan(it, totals[it], recipe, rt, machine=machine, belt=belt))
    if oil_demand:
        oil = oil_plans(oil_demand, rt, by_name, belt)
        plans.extend(oil)
        water = sum(pl["crafts"] * next(i["amount"] for i in pl["recipe"]["ingredients"] if i["name"] == "water") for pl in oil)
        crude = sum(pl["crafts"] * 100 for pl in oil if pl["recipe"]["name"] == "advanced-oil-processing")
        externals.append(("crude-oil", crude, "raw"))
        externals.append(("water", water, "raw"))
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
    recipes = rt.load_recipes()
    by_product = rt.build_index(recipes)
    by_name = {r["name"]: r for r in recipes}
    name = args.name
    if len(args.specs) == 1 and is_rate(args.specs[0]) and not os.path.exists(args.name):
        if args.name not in by_product:
            sys.exit(f"no recipe produces {args.name!r}")
        try:
            raw = set(args.raw) | ({"iron-plate", "copper-plate"} if args.from_plates else set())
            plans, externals = factory(args.name, rt.parse_rate(args.specs[0]), rt, by_product, by_name, raw, args.belt,
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
        mods = fixed + [m for pl in plans for m in build_plan(pl, columns=-(-pl["n"] // T))]
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
