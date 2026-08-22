#!/usr/bin/env python3
"""Generate a single-recipe module (blueprint with INPUT/OUTPUT ports) for an item at a rate.

    python make.py <item> <rate> [--layout template|row] [--recipe NAME] [--machine NAME] [--belt NAME] [-o DIR] [--no-render]

Writes <DIR>/<item>.module.json, <DIR>/<item>.txt (vanilla blueprint string), <DIR>/<item>.png.

--layout template (default): vertical cells from 03_samples/<N>_to_1.md, N = ingredient count (1-4),
stacked upward to n machines. Inputs enter the bottom edge northbound (left to right), output exits
the bottom-right southbound. See templates.py.

--layout row: horizontal rows (below).

  1 item ingredient                         2 item ingredients
  ┌───────────────────────┐                  ┌───────────────────────┐
  │ machine machine ...   │ rows 0-2         │ machine machine ...   │ rows 0-2
  │ ins pole ins ...      │ row 3            │ long pole ins ...     │ row 3
  │ belt ─────────────►   │ row 4  IN L/OUT R│ belt ──────────────┐  │ row 4  OUT belt
  └───────────────────────┘                  │ belt ───────────►  ▼  │ row 5  IN L+R / OUT at (W-1,5) S
                                             └───────────────────────┘
"""
import argparse
import importlib.util
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from module import Module, Port, port_table  # noqa: E402
import templates  # noqa: E402


def load_recipe_tool():
    spec = importlib.util.spec_from_file_location("recipe", os.path.join(ROOT, "01_recipe_generatpr", "recipe.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# name -> (items/s per lane)
BELTS = [("transport-belt", 7.5), ("fast-transport-belt", 15.0), ("express-transport-belt", 22.5),
         ("turbo-transport-belt", 30.0)]
# crafting machines this generator knows how to place (all 3x3, inserter-fed)
MACHINE_SPEED = {"assembling-machine-1": 0.5, "assembling-machine-2": 0.75, "assembling-machine-3": 1.25,
                 "electric-furnace": 2.0}
CATEGORY_MACHINE = {"crafting": "assembling-machine-2", "advanced-crafting": "assembling-machine-2",
                    "basic-crafting": "assembling-machine-2", "smelting": "electric-furnace"}


def ent(name, x, y, direction=0, **kw):
    e = {"name": name, "position": {"x": x, "y": y}, "direction": direction}
    e.update(kw)
    return e


def pick_belt(max_lane_rate):
    for name, cap in BELTS:
        if max_lane_rate <= cap + 1e-9:
            return name, cap
    sys.exit(f"lane rate {max_lane_rate:.3g}/s exceeds turbo belt lane capacity (30/s)")


def build(item, rate, recipe, machine, rt):
    ings = recipe["ingredients"]
    if any(i["type"] == "fluid" for i in ings) or any(r["type"] == "fluid" for r in recipe["results"]):
        sys.exit(f"{recipe['name']}: fluid ingredients/results not supported")
    if len(ings) > 2:
        sys.exit(f"{recipe['name']}: {len(ings)} ingredients; generator supports at most 2")
    per_craft = rt.net_output(recipe, item)
    crafts = rate / per_craft
    time = recipe.get("energy_required", 0.5)
    n = max(1, math.ceil(crafts * time / MACHINE_SPEED[machine]))
    actual = n * MACHINE_SPEED[machine] / time * per_craft
    ing_rates = [(i["name"], crafts * i["amount"]) for i in ings]

    W = 3 * n
    ents = []
    if len(ings) == 1:
        H = 5
        belt, cap = pick_belt(max(rate, ing_rates[0][1]))
        for x in range(W):
            ents.append(ent(belt, x + 0.5, 4.5, 4))
        for k in range(n):
            c = 3 * k
            ents.append(ent(machine, c + 1.5, 1.5, 0, **({"recipe": recipe["name"]} if machine != "electric-furnace" else {})))
            ents.append(ent("inserter", c + 0.5, 3.5, 8))        # picks from belt (south), drops into machine
            ents.append(ent("small-electric-pole", c + 1.5, 3.5, 0))
            ents.append(ent("inserter", c + 2.5, 3.5, 0))        # picks from machine (north), drops on belt
        inputs = [Port("in", "belt", ing_rates[0][0], "left", 0, 4, 4, ing_rates[0][1])]
        outputs = [Port("out", "belt", item, "right", W - 1, 4, 4, rate)]
        notes = [f"{n}x {machine} {recipe['name']} -> {actual:.3g}/s capacity", f"belt: {belt} ({cap:g}/s per lane)"]
    else:
        H = 6
        belt, cap = pick_belt(max([rate] + [r for _, r in ing_rates]))
        for x in range(W - 1):
            ents.append(ent(belt, x + 0.5, 4.5, 4))          # output belt, east
        ents.append(ent(belt, W - 0.5, 4.5, 8))              # turns south
        ents.append(ent(belt, W - 0.5, 5.5, 8))              # exits bottom-right, south
        for x in range(W - 2):
            ents.append(ent(belt, x + 0.5, 5.5, 4))          # input belt, east, stops short of the output column
        for k in range(n):
            c = 3 * k
            ents.append(ent(machine, c + 1.5, 1.5, 0, **({"recipe": recipe["name"]} if machine != "electric-furnace" else {})))
            ents.append(ent("long-handed-inserter", c + 0.5, 3.5, 8))  # picks from far belt (row 5), drops into machine row 1
            ents.append(ent("small-electric-pole", c + 1.5, 3.5, 0))
            ents.append(ent("inserter", c + 2.5, 3.5, 0))              # machine -> near belt (row 4)
        inputs = [Port("in", "belt", ing_rates[0][0], "left", 0, 5, 4, ing_rates[0][1]),
                  Port("in", "belt", ing_rates[1][0], "right", 0, 5, 4, ing_rates[1][1])]
        outputs = [Port("out", "belt", item, "right", W - 1, 5, 8, rate)]
        notes = [f"{n}x {machine} {recipe['name']} -> {actual:.3g}/s capacity", f"belt: {belt} ({cap:g}/s per lane)",
                 "input belt ends at column W-3; last tile in row 5 is the output belt"]
    return Module(name=f"{item} {rate:g}/s", width=W, height=H, entities=ents, inputs=inputs, outputs=outputs, notes=notes)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("item")
    ap.add_argument("rate", help="items/s; N/m for per minute")
    ap.add_argument("--recipe", help="recipe name (default: recipe named after the item)")
    ap.add_argument("--layout", choices=["template", "row"], default="template")
    ap.add_argument("--machine", choices=sorted(MACHINE_SPEED), help="override crafting machine")
    ap.add_argument("--belt", choices=[b for b, _ in BELTS], default="transport-belt", help="belt tier (template layout)")
    ap.add_argument("-o", "--out-dir", default=os.path.join(HERE, "out"))
    ap.add_argument("--no-render", action="store_true")
    args = ap.parse_args()

    rt = load_recipe_tool()
    recipes = rt.load_recipes()
    by_name = {r["name"]: r for r in recipes}
    by_product = rt.build_index(recipes)
    if args.recipe:
        recipe = by_name.get(args.recipe) or sys.exit(f"unknown recipe {args.recipe}")
    elif args.item in by_product:
        recipe = by_product[args.item][0]
    else:
        sys.exit(f"no recipe produces {args.item!r}")
    cats = recipe.get("categories") or ["crafting"]
    machine = args.machine or next((CATEGORY_MACHINE[c] for c in cats if c in CATEGORY_MACHINE), None)
    if machine is None:
        sys.exit(f"recipe {recipe['name']} categories {cats}: no supported machine")

    rate = rt.parse_rate(args.rate)
    if args.layout == "template":
        try:
            mod = templates.build(args.item, rate, recipe, rt, machine=machine, belt=args.belt)
        except (ValueError, FileNotFoundError) as ex:
            sys.exit(str(ex))
    else:
        mod = build(args.item, rate, recipe, machine, rt)
    problems = mod.check()
    if problems:
        sys.exit("module check failed:\n  " + "\n  ".join(problems))

    os.makedirs(args.out_dir, exist_ok=True)
    base = os.path.join(args.out_dir, args.item)
    mod.save(base + ".module.json")
    with open(base + ".txt", "w") as f:
        f.write(mod.to_string() + "\n")

    print(f"{mod.name}: {mod.width}x{mod.height} tiles, {len(mod.entities)} entities")
    for n in mod.notes:
        print("  " + n)
    print(port_table(mod))
    print(f"wrote {base}.module.json, {base}.txt", flush=True)
    if not args.no_render:
        render = os.path.join(ROOT, "02_blueprint_visualizer", "render.py")
        subprocess.run([sys.executable, render, "-", "-o", base + ".png", "--tile", "48"],
                       input=json.dumps(mod.render_json()), text=True, check=True)


if __name__ == "__main__":
    main()
