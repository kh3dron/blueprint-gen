#!/usr/bin/env python3
"""Stitch modules over a bus into one composite module.

    python compose.py <name> <spec>... [--belt NAME] [--export ITEM]... [-o DIR] [--no-render]
    python compose.py <item> <rate>  [--from-plates] [--no-smelting] [--raw ITEM]... [--belt NAME] [-o DIR] [--no-render]
    ... [--roboports [SPACING]]   reserve a roboport grid (bottom-left first, every SPACING tiles, default 48)

<spec> is either a path to a .module.json or item=rate (generated on the fly with templates.py).
The second form is factory mode: the recipe tree of <item> is expanded with the 01 calculator,
one module is generated per intermediate at its total rate, and mined/pumped resources, --raw
items, and recipes no cell can build (>4 item ingredients, >4 item ports on a fluid recipe,
unsupported category) become external inputs. Fluid and mixed item+fluid recipes go through
fluidcells.py (chemical plant, oil refinery, assembling machine).
--from-plates = --raw iron-plate --raw copper-plate (smelting handled elsewhere);
--no-smelting treats every smelting-category product (plates, steel, bricks) as raw.
Output name is <item>-factory.
Modules are ordered producers-before-consumers automatically. Items consumed but not produced
become external inputs (bottom-left risers); items produced but not consumed (or named with
--export) become outputs (bottom-right drops).

Writes <DIR>/<name>.module.json, <DIR>/<name>.txt, <DIR>/<name>.png.
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from module import Module, port_summary, port_table  # noqa: E402
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


def analyse(item, rate, rt, by_product, raw, belt, no_smelting=False):
    """Walk the recipe tree of `item` at `rate`. Returns
    totals     item -> items/s summed over every use
    order      first-visit order (root first, leaves last)
    blocked    item -> why no cell can build it
    consumers  item -> {recipes that consume it}     (drives nesting in factory_tree)
    oil        consumer -> {oil product: items/s}    (oil is planned as one unit, see oil_plans)
    buildable  the predicate itself, so callers can re-ask
    """
    totals, order, blocked, consumers, oil = {}, [], {}, {}, {}

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

    def walk(it, r, parent):
        totals[it] = totals.get(it, 0.0) + r
        if it not in order:
            order.append(it)
        if parent is not None:
            consumers.setdefault(it, set()).add(parent)
        if not buildable(it):
            return
        if it in OIL:
            oil.setdefault(parent, {})
            oil[parent][it] = oil[parent].get(it, 0.0) + r
            return
        recipe = by_product[it][0]
        crafts = r / rt.net_output(recipe, it)
        for ing in recipe["ingredients"]:
            if ing["name"] != it:
                walk(ing["name"], crafts * ing["amount"], it)

    walk(item, rate, None)
    return {"totals": totals, "order": order, "blocked": blocked, "consumers": consumers,
            "oil": oil, "buildable": buildable}


def plan_for(it, total, rt, by_product, belt, single=()):
    """Sizing plan for one intermediate at its summed rate (fluid cell or template). An ingredient in
    `single` (one producer, one consumer in this factory) is put on the cell's leftmost input port,
    where a direct link from the module next door can reach it."""
    recipe = by_product[it][0]
    if has_fluid(recipe):
        return fluidcells.plan(recipe, total / rt.net_output(recipe, it), rt, belt=belt)
    cats = recipe.get("categories") or ["crafting"]
    machine = next(make.CATEGORY_MACHINE[c] for c in cats if c in make.CATEGORY_MACHINE)
    prefer = next((i["name"] for i in recipe["ingredients"] if i["name"] in single), None)
    return templates.plan(it, total, recipe, rt, machine=machine, belt=belt, prefer=prefer)


def single_use(a):
    """Items this factory produces in one place and consumes in one place."""
    return {it for it in a["order"] if a["buildable"](it) and len(a["consumers"].get(it, ())) == 1}


def externals_of(a, rt, raw):
    """[(item, rate, why)] for everything the walk could not build. One line per item."""
    out = []

    def add(name, rate, why):
        for i, (n, r, w) in enumerate(out):
            if n == name:
                out[i] = (n, r + rate, w)
                return
        out.append((name, rate, why))

    for it in a["order"]:
        if not a["buildable"](it):
            add(it, a["totals"][it], a["blocked"].get(it) or ("--raw" if it in raw else
                                                             "mined/pumped" if it in rt.RAW else "no recipe"))
    return out, add


def oil_externals(oil_pls, add):
    water = sum(pl["crafts"] * next(i["amount"] for i in pl["recipe"]["ingredients"] if i["name"] == "water")
                for pl in oil_pls)
    crude = sum(pl["crafts"] * 100 for pl in oil_pls if pl["recipe"]["name"] == "advanced-oil-processing")
    add("crude-oil", crude, "mined/pumped")
    add("water", water, "mined/pumped")


def factory(item, rate, rt, by_product, by_name, raw, belt, no_smelting=False):
    """Plans for every craftable intermediate of `item`, each at its summed rate, all on one bus.
    Returns (plans, externals)."""
    a = analyse(item, rate, rt, by_product, raw, belt, no_smelting)
    externals, add = externals_of(a, rt, raw)
    single = single_use(a)
    plans = [plan_for(it, a["totals"][it], rt, by_product, belt, single)
             for it in a["order"] if a["buildable"](it) and it not in OIL]
    demand = {}
    for per_parent in a["oil"].values():
        for k, v in per_parent.items():
            demand[k] = demand.get(k, 0.0) + v
    if demand:
        oil = oil_plans(demand, rt, by_name, belt)
        plans.extend(oil)
        oil_externals(oil, add)
    return plans, externals


def factory_tree(root, rate, rt, by_product, by_name, raw, belt, build, join, no_smelting=False,
                 nest_min=1):
    """Recursive factory. An intermediate consumed by exactly one recipe is produced inside that
    recipe's own box (its own bus, its own bounding box), so it never reaches the parent bus; one
    consumed by several recipes stays on the parent bus. A group of fewer than `nest_min` modules is
    inlined into the parent's bus instead of getting a bus of its own, which never pays for its
    routing band. `build(plan)` makes a plan's column modules, `join(name, modules)` composes a box.
    Returns (modules for the top bus, externals, tree)."""
    a = analyse(root, rate, rt, by_product, raw, belt, no_smelting)
    totals, order, consumers, buildable = a["totals"], a["order"], a["consumers"], a["buildable"]
    externals, add = externals_of(a, rt, raw)
    single = single_use(a)
    oil_users = [p for p in a["oil"] if p is not None]
    oil_owner = oil_users[0] if len(set(oil_users)) == 1 else None      # else: shared, top level
    exclusive = {it: next(iter(consumers[it])) for it in order
                 if buildable(it) and it not in OIL and it != root and len(consumers.get(it, ())) == 1}

    def oil_box(demand):
        pls = oil_plans(demand, rt, by_name, belt)
        oil_externals(pls, add)
        return [m for pl in pls for m in build(pl)], pls

    def box(it, depth):
        """(modules, node). A box with children is composed into one nested module; one without is
        inlined into whatever bus its parent uses."""
        kids, nodes = [], []
        for ing in by_product[it][0]["ingredients"]:
            if exclusive.get(ing["name"]) == it:
                mods, node = box(ing["name"], depth + 1)
                kids += mods
                nodes.append(node)
        if oil_owner == it:
            mods, pls = oil_box(a["oil"][it])
            kids += mods
            nodes.append({"item": "oil", "rate": sum(a["oil"][it].values()), "depth": depth + 1,
                          "modules": len(mods), "size": None, "kids": [],
                          "detail": "+".join(pl["recipe"]["name"].split("-")[0] for pl in pls)})
        own = build(plan_for(it, totals[it], rt, by_product, belt, single))
        node = {"item": it, "rate": totals[it], "depth": depth, "kids": nodes, "detail": ""}
        if len(kids) + len(own) < max(nest_min, 2) or not kids:
            node["modules"], node["size"] = len(kids) + len(own), None
            return kids + own, node               # too small to pay for a bus of its own: inline it
        mods = topo_sort(kids + own, belt=belt)
        m = join(f"{it} {totals[it]:g}/s", mods)
        node["modules"], node["size"] = len(mods), (m.width, m.height)
        return [m], node

    tops, tree = [], []
    for it in order:                       # shared intermediates: their own box on the top bus
        if it == root or it in OIL or it in exclusive or not buildable(it):
            continue
        mods, node = box(it, 0)
        tops += mods
        tree.append(node)
    if oil_owner is None and a["oil"]:
        demand = {}
        for per_parent in a["oil"].values():
            for k, v in per_parent.items():
                demand[k] = demand.get(k, 0.0) + v
        mods, pls = oil_box(demand)
        tops += mods
        tree.append({"item": "oil", "rate": sum(demand.values()), "depth": 0, "modules": len(mods),
                     "size": None, "kids": [], "detail": "+".join(pl["recipe"]["name"].split("-")[0] for pl in pls)})
    mods, node = box(root, 0)
    tops += mods
    tree.append(node)
    return tops, externals, tree


def topo_sort(modules, chain=True, belt="transport-belt"):
    """Producers before consumers. Where an item has a single producer port and a single consumer port,
    the pair is scheduled as one unit so the two land side by side on the same side of the bus and
    `bus.py` can link them directly instead of giving the item a lane; those pairs chain, so a whole
    production line comes out contiguous. With no such pair the order is exactly the depth-first one."""
    n = len(modules)
    produced_by = {}
    for i, m in enumerate(modules):
        for p in m.outputs:
            produced_by.setdefault(p.item, []).append(i)
    deps = {i: {j for p in modules[i].inputs for j in produced_by.get(p.item, []) if j != i}
            for i in range(n)}

    base, seen, visiting = [], set(), set()      # depth-first order: the baseline this keeps to

    def visit(i):
        if i in seen:
            return
        if i in visiting:
            sys.exit(f"cycle through {modules[i].name}")
        visiting.add(i)
        for p in modules[i].inputs:              # exactly the old traversal: producers in port order
            for j in produced_by.get(p.item, []):
                if j != i:
                    visit(j)
        visiting.discard(i)
        seen.add(i)
        base.append(i)

    for i in range(n):
        visit(i)
    pos = {i: k for k, i in enumerate(base)}

    best = {}                          # consumer -> (producer, port x): a link can only reach the
    for pm, _, cm, pi in (bus.solo_items(modules, belt).values() if chain else ()):   # consumer's westmost port, so prefer the
        x = modules[cm].inputs[pi].x                         # producer that feeds it
        if cm not in best or x < best[cm][1]:
            best[cm] = (pm, x)
    prv = {cm: pm for cm, (pm, _) in best.items()}
    nxt = {pm: cm for cm, pm in prv.items()}
    chains, taken = [], set()
    for i in sorted(range(n), key=lambda i: pos[i]):         # prv/nxt are one-to-one: disjoint paths
        if i in prv or i in taken:
            continue
        ch = [i]
        while ch[-1] in nxt and nxt[ch[-1]] not in taken:
            ch.append(nxt[ch[-1]])
        taken.update(ch)
        chains.append(ch)
    chains += [[i] for i in sorted(range(n), key=lambda i: pos[i]) if i not in taken]
    chains.sort(key=lambda c: pos[c[0]])

    order, done = [], set()
    while any(chains):
        ch = next((c for c in chains if c and all(deps[i] - set(c) <= done for i in c)), None)
        if ch is None:                 # a chain is waiting on something inside another chain: split it
            ch = next((c for c in chains if c and deps[c[0]] <= done), None)
            if ch is None:
                sys.exit(f"cycle through {modules[next(i for c in chains for i in c)].name}")
            order.append(ch.pop(0))
            done.add(order[-1])
            continue
        order += ch
        done.update(ch)
        ch.clear()
    return [modules[i] for i in order]


STEP = [0, 0]           # [done, total] for the "[n/m] LABEL" report


def step(label, text=""):
    STEP[0] += 1
    print(f"[{STEP[0]}/{STEP[1]}] {label:<8}{text}", flush=True)


def cont(text):
    print(f"        {text}", flush=True)


def table(header, rows):
    cont(header)
    for r in rows:
        cont(r)


def tree_rows(nodes, out=None):
    """Pre-order table of the box tree: item, rate, modules inside, and its size when it is a box."""
    out = [] if out is None else out
    for n in nodes:
        size = f"{n['size'][0]}x{n['size'][1]}" if n["size"] else "inline"
        out.append(f"{'  ' * n['depth'] + n['item']:<28}{n['rate']:>10.4g}/s{n['modules']:>8}  {size}"
                   + (f"  ({n['detail']})" if n.get("detail") else ""))
        tree_rows(n["kids"], out)
    return out


def warning_summary(warnings):
    """One line per kind, with the items or places involved. -v prints the warnings themselves."""
    short, rest = {}, {}
    for w in warnings:
        m = re.search(r"([a-z0-9-]+) (?:port|pipe) needs .*\(short ([0-9.]+)/s\)", w)
        if m:
            item, amount = m[1], float(m[2])
            n, tot = short.get(item, (0, 0.0))
            short[item] = (n + 1, tot + amount)
            continue
        kind = ("roboport with no pole path" if "no pole path" in w else
                "roboport spot skipped" if "roboport" in w else
                "pole out of reach" if "pole" in w else "other")
        rest.setdefault(kind, []).append(w)
    out = []
    if short:
        n = sum(v[0] for v in short.values())
        items = ", ".join(f"{it} {v[0]}x short {v[1]:.3g}/s" for it, v in
                          sorted(short.items(), key=lambda kv: -kv[1][1]))
        out.append(f"{n:>3} ports under-supplied (greedy lane packing): {items}")
    for kind, ws in rest.items():
        out.append(f"{len(ws):>3} {kind}: {ws[0][:96]}" + (" ..." if len(ws) > 1 else ""))
    return out


def main():
    T0 = time.time()
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
    ap.add_argument("--nested", action="store_true",
                    help="factory mode: give every single-consumer intermediate its own bus inside its "
                         "consumer's bounding box, instead of one bus for the whole factory")
    ap.add_argument("--no-links", action="store_true",
                    help="do not link a producer straight to the consumer next door; give every item a bus lane")
    ap.add_argument("--nest-min", type=int, default=6, metavar="N",
                    help="--nested: a group smaller than N modules is inlined into its parent's bus "
                         "instead of getting one of its own (default 6)")
    ap.add_argument("--from-plates", action="store_true", help="factory mode: iron-plate and copper-plate are external inputs")
    ap.add_argument("--no-smelting", action="store_true", help="factory mode: every smelting recipe's product is an external input")
    ap.add_argument("-o", "--out-dir", default=os.path.join(HERE, "out"))
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--stats", metavar="FILE", help="write a one-line JSON summary of the result (bench.py reads it)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="per-module and per-lane tables, every port, full retry reasons")
    args = ap.parse_args()
    STEP[1] = 5 if args.no_render else 6
    bus.progress = lambda stage, ex: cont(f"{stage}: {ex if args.verbose else str(ex).split(' (')[0]} -> retry")

    rt = make.load_recipe_tool()
    recipes = rt.load_recipes()
    by_product = rt.build_index(recipes)
    by_name = {r["name"]: r for r in recipes}
    name = args.name
    if len(args.specs) == 1 and is_rate(args.specs[0]) and not os.path.exists(args.name):
        if args.name not in by_product:
            sys.exit(f"no recipe produces {args.name!r}")
        rate = rt.parse_rate(args.specs[0])
        raw = set(args.raw) | ({"iron-plate", "copper-plate"} if args.from_plates else set())
        try:
            plans, externals = factory(args.name, rate, rt, by_product, by_name, raw, args.belt,
                                       no_smelting=args.no_smelting)
            fixed = []
        except ValueError as ex:
            sys.exit(str(ex))
        name = args.name + "-factory"
        step("RECIPE", f"{args.name} {rate:g}/s on {args.belt}")
        cont(f"{len(plans)} intermediates built, {len(externals)} fed from outside")
        table(f"{'EXTERNAL IN':<26}{'RATE':>12}  WHY",
              [f"{it:<26}{r:>10.4g}/s  {why}" for it, r, why in externals])
        if not plans:
            sys.exit(f"{args.name}: nothing to build ({externals[0][2]})")
    else:
        loaded = [load_spec(s, rt, by_product, args.belt) for s in args.specs]
        plans = [x for kind, x in loaded if kind == "plan"]
        fixed = [x for kind, x in loaded if kind == "module"]
        externals = []
        made = {r["name"] for pl in plans for r in pl["recipe"]["results"]}
        used = {}
        for pl in plans:
            for i in pl["recipe"]["ingredients"]:
                used[i["name"]] = used.get(i["name"], 0) + 1
        single = {it for it in made if used.get(it) == 1}
        plans = [pl if pl.get("kind") == "fluid" else
                 templates.plan(pl["item"], pl["rate"], pl["recipe"], rt, machine=pl["machine"],
                                belt=args.belt, prefer=next((i["name"] for i in pl["recipe"]["ingredients"]
                                                             if i["name"] in single), None))
                 for pl in plans]
        step("SPECS", f"{len(plans)} recipe{'s' * (len(plans) != 1)}, {len(fixed)} module "
                      f"file{'s' * (len(fixed) != 1)}, belt {args.belt}")
        for m in fixed:
            cont(f"{m.name:<26}{m.width}x{m.height} from file")
    cells = args.cells or max([pl["n"] for pl in plans] + [1])      # default: no height balancing, minimum columns
    max_n = max([pl["n"] for pl in plans] + [1])
    candidates = [cells] if (args.cells or not args.tune or not plans) else sorted({max(1, min(max_n, cells + d)) for d in range(-3, 4)})

    built, box_warnings, box_name = {}, [], [""]

    def join(nm, mods):
        """Compose one nested box. Its warnings are re-reported at the top level, tagged with the box."""
        box_name[0] = nm
        m = bus.compose(nm, mods, belt=args.belt, two_sided=not args.one_sided, nested=True,
                        direct=not args.no_links)
        box_warnings.extend(f"WARNING [{nm}] {w[len('WARNING '):]}" for w in m.notes if w.startswith("WARNING"))
        return m

    def build(T):
        if args.nested:
            del box_warnings[:]
            try:
                tops, _, tree = factory_tree(args.name, rate, rt, by_product, by_name, raw, args.belt,
                                             lambda pl: build_plan(pl, columns=-(-pl["n"] // T)), join,
                                             no_smelting=args.no_smelting, nest_min=args.nest_min)
            except ValueError as ex:
                cont(f"FAILED box {box_name[0]}: {ex}")
                sys.exit(1)
            built[T] = fixed + tops
            trees[T] = tree
        else:
            built[T] = fixed + [m for pl in plans for m in build_plan(pl, columns=-(-pl["n"] // T))]
        return built[T]

    trees = {}
    if args.nested:
        n_top = len(build(cells))
        nodes = [n for n in trees[cells]]
        boxes = sum(1 for r in tree_rows(nodes) if "x" in r.split()[-1])
        step("TREE", f"{n_top} modules on the top bus, {boxes} nested box{'es' * (boxes != 1)}")
        table(f"{'BOX':<28}{'RATE':>12}{'MODULES':>9}  SIZE", tree_rows(nodes))
    elif len(candidates) == 1:
        n_mod = len(build(cells))
        step("MODULES", f"{len(plans)} plans, {sum(pl['n'] for pl in plans)} machines -> {n_mod} column modules"
                        + (f" (<= {cells} machines each)" if args.cells else " (split by belt capacity)"))
    else:
        step("MODULES", f"{len(plans)} plans, {sum(pl['n'] for pl in plans)} machines, "
                        f"tuning {candidates[0]}-{candidates[-1]} machines per column")
    if args.verbose and plans and not args.nested:
        table(f"{'ITEM':<26}{'RATE':>12}  {'MACHINE':<21}{'N':>4}{'COLS':>5}  CELL",
              [f"{pl.get('item', pl['recipe']['name']):<26}{pl.get('rate', 0.0):>10.4g}/s  {pl['machine']:<21}"
               f"{pl['n']:>4}{max(pl['c_min'], -(-pl['n'] // cells)):>5}  {pl['width'] or '?'}x{pl['base_height']}"
               for pl in plans])

    def one(mods, direct):
        return bus.compose(name, topo_sort(mods, direct, args.belt), belt=args.belt, exports=args.export,
                           roboport=args.roboports, two_sided=not args.one_sided, direct=direct)

    def layout(T):
        """With direct links the module order changes, which can cost more elsewhere than the lane it
        saves. When any link fires, lay the same modules out both ways and keep the smaller."""
        mods = built.get(T) or build(T)
        try:
            m = one(mods, not args.no_links)
        except ValueError as ex:                     # links reserve fewer columns, so they can also
            if args.no_links:                        # fail to pack: fall back to the plain layout
                raise
            cont(f"direct links: {str(ex).split(':')[0]} -> laying out without them")
            return one(mods, False)
        if not getattr(m, "links", 0):
            return m
        alt = one(mods, False)
        area, alt_area = m.width * m.height, alt.width * alt.height
        keep = (area, len(m.entities)) <= (alt_area, len(alt.entities))
        cont(f"{m.links} direct links: {m.width}x{m.height} = {area:,} vs {alt.width}x{alt.height} "
             f"= {alt_area:,} without -> {'links' if keep else 'no links'}")
        return m if keep else alt

    step("BUS", f"{args.belt}, {'one-sided' if args.one_sided else 'both sides'}"
                + (f", roboports every {args.roboports}" if args.roboports else ""))
    mod, best = None, None
    for T in candidates:
        tag = "" if len(candidates) == 1 else f"cells {T:>3}: "
        try:
            m = layout(T)
        except ValueError as ex:
            if len(candidates) == 1:
                cont(f"FAILED {ex}")
                sys.exit(1)
            cont(f"{tag}FAILED {str(ex).split(':')[0]}")
            continue
        area = m.width * m.height
        cont(f"{tag}{len(built[T])} modules -> {m.width}x{m.height} = {area:,} tiles")
        if best is None or area < best:
            mod, best, cells = m, area, T
    if mod is None:
        sys.exit("        no layout succeeded")
    cont(mod.notes[0])
    if args.verbose:
        table("LANES:", [n for n in mod.notes if n.startswith("lane ")])
        table("MODULES:", [mod.notes[1][9:]])

    mod.notes += box_warnings
    problems = mod.check()
    step("CHECK", f"{len(problems)} problems, {len(mod.entities):,} entities, {len(mod.wires):,} wires")
    if problems:
        sys.exit("        " + "\n        ".join(problems[:20]))

    os.makedirs(args.out_dir, exist_ok=True)
    base = os.path.join(args.out_dir, name)
    mod.save(base + ".module.json")
    with open(base + ".txt", "w") as f:
        f.write(mod.to_string() + "\n")
    step("WRITE", f"{base}.module.json, .txt")
    if not args.no_render:
        step("RENDER", f"{base}.png ({(mod.width + 2) * 32:,}x{(mod.height + 2) * 32:,} px)")
        render = os.path.join(ROOT, "02_blueprint_visualizer", "render.py")
        subprocess.run([sys.executable, render, "-", "-o", base + ".png", "--tile", "32"],
                       input=json.dumps(mod.render_json()), text=True, check=True,
                       stdout=subprocess.DEVNULL if not args.verbose else None)

    print(f"\n{mod.name}: {mod.width}x{mod.height} tiles, {len(mod.entities):,} entities, {len(mod.wires):,} wires")
    print(port_table(mod) if args.verbose else port_summary(mod))
    warnings = [n[len("WARNING "):] for n in mod.notes if n.startswith("WARNING")]
    if args.stats:
        with open(args.stats, "w") as f:
            json.dump(dict({"name": name, "width": mod.width, "height": mod.height,
                            "area": mod.width * mod.height, "entities": len(mod.entities),
                            "wires": len(mod.wires), "warnings": len(warnings),
                            "seconds": round(time.time() - T0, 2)}, **getattr(mod, "stats", {})), f)
    if warnings:
        print(f"\nWARNINGS {len(warnings)}" + ("" if args.verbose else " (kept in full in the description; -v to print them)"))
        for line in (warnings if args.verbose else warning_summary(warnings)):
            print("  " + line)


if __name__ == "__main__":
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)   # die quietly when piped into head
    main()
