#!/usr/bin/env python3
"""What to build next, from the notebook.

    plan.py status                  what the ledger adds up to: rates, research, tiers, milestone
    plan.py next [--accept]         the next move; --accept writes it to the notebook
    plan.py accept                  write the move `next` last printed to the notebook
    plan.py log <move> <what> [rate] [note]     append a move yourself
    plan.py ladder                  the milestone ladder and how far along it you are

The ledger (notebook.md, see ledger.py) is the only state. Every `build` line is a factory producing
one item at one rate, so production and consumption are exact: a build consumes its recipe's
ingredients at the rate implied by its output. `have` lines cover everything outside the ledger (ore,
hand-built smelting).

The next move is whatever the milestone ladder is waiting for:

  1. the ladder's first unmet goal sets the target: N science packs per minute
  2. if that pack's recipe is not unlocked yet, or a needed intermediate's is not, the move is the
     next researchable technology on the way to it
  3. otherwise the whole recipe tree of the goal is expanded and compared with what the ledger
     already produces; the move is the shortest-of-supply item whose own ingredients are covered, so
     you always build producers before consumers
  4. an item already in the ledger is a `scale`, a new one is a `build`; when a better machine or belt
     tier has been researched than the one the existing build used, the move says so

A build or scale move comes with a blueprint: 03_blueprint_objects/make.py at the researched machine
and belt tier, written to out/plan/.
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "03_blueprint_objects"))
import ledger                                    # noqa: E402
from tech import Tech, PACKS, TIERS              # noqa: E402
import make as mk                                # noqa: E402
import fluidcells                                # noqa: E402

FAMILY = {"crafting": "assembler", "advanced-crafting": "assembler", "basic-crafting": "assembler",
          "crafting-with-fluid": "assembler", "smelting": "furnace"}

OUT = os.path.join(HERE, "out", "plan")
PENDING = os.path.join(HERE, ".next.json")
EPS = 1e-6
SHORT = 0.005           # items/s below which a shortfall is rounding in the notebook, not a move

# (item, science packs per minute). The ladder the planner works down unless a `target` line overrides
# it: the first four packs at 10/min, then everything at 100/min.
LADDER = [(p, 10) for p in PACKS[:4]] + [(p, 100) for p in PACKS]


def rt_and_recipes():
    rt = mk.load_recipe_tool()
    recipes = rt.load_recipes()
    return rt, recipes, rt.build_index(recipes)


def requirements(item, rate, rt, by_product, buildable):
    """item -> items/s needed to sustain `rate` of `item`. Stops at raws and at anything with no
    buildable recipe, which become the leaves you have to supply some other way."""
    need = {}

    def walk(it, r, seen):
        need[it] = need.get(it, 0.0) + r
        recipe = (by_product.get(it) or [None])[0]
        if recipe is None or recipe["name"] not in buildable or it in rt.RAW or it in seen:
            return
        crafts = r / rt.net_output(recipe, it)
        for ing in recipe["ingredients"]:
            if ing["name"] != it:
                walk(ing["name"], crafts * ing["amount"], seen | {it})

    walk(item, rate, frozenset())
    return need


def demand(st, rt, by_product, buildable, upto):
    """items/s of everything needed to keep every ladder rung up to `upto` running at once, not just
    the one being worked on: an earlier rung still consumes while you build the next."""
    want = {}
    for item, spm in LADDER[:upto + 1]:
        want[item] = max(want.get(item, 0.0), st["targets"].get(item, spm / 60))
    total = {}
    for item, rate in want.items():
        for k, v in requirements(item, rate, rt, by_product, buildable).items():
            total[k] = total.get(k, 0.0) + v
    return total


def goal(st):
    """(item, items/s, why) for the first unmet rung of the ladder, or None when it is all done.
    A rung is met when the ledger builds that pack at the target rate."""
    for i, (item, spm) in enumerate(LADDER):
        want = st["targets"].get(item, spm / 60)
        if st["made"].get(item, 0.0) < want - SHORT:
            return item, want, f"{item} at {spm}/min", i
    for item, want in st["targets"].items():                # bare targets outside the ladder
        if st["made"].get(item, 0.0) < want - SHORT:
            return item, want, f"target {item} {ledger.fmt_rate(want)}", len(LADDER) - 1
    return None


def next_move(st, tech, rt, by_product):
    """The move to make now: dict(kind, what, rate, why, needs, detail)."""
    g = goal(st)
    if g is None:
        return {"kind": "done", "what": "", "rate": 0.0, "why": "every ladder goal is met", "needs": []}
    item, want, why, rung = g
    buildable = tech.recipes(st["researched"])

    chain = tech.unlocking((by_product.get(item) or [{"name": item}])[0]["name"], st["researched"])
    need = demand(st, rt, by_product, buildable, rung)
    for it in sorted(need, key=lambda i: -need[i]):         # a recipe on the way that is still locked
        r = (by_product.get(it) or [None])[0]
        if r is not None and it not in rt.RAW and r["name"] not in buildable and st["net"].get(it, 0) < need[it]:
            chain = chain or tech.unlocking(r["name"], st["researched"])
    if chain:
        return research_move(chain[0], st, tech, why, item)

    # an item is satisfied when it is produced at least as fast as the goal needs it and as fast as
    # the builds already in the ledger consume it; `net` is headroom, which is a different question
    def gap(it):
        return max(need.get(it, 0.0), st["used"].get(it, 0.0)) - st["made"].get(it, 0.0)

    short = {it: gap(it) for it in need if gap(it) > SHORT}
    if not short:
        return {"kind": "done", "what": item, "rate": want, "needs": [],
                "why": f"{why}: every input is already produced, the ladder rung is only waiting on labs"}

    def ready(it):
        """No ingredient of `it` is itself short, so building it now is not blocked."""
        recipe = (by_product.get(it) or [None])[0]
        if recipe is None or it in rt.RAW:
            return False
        return not any(i["name"] in short for i in recipe["ingredients"] if i["name"] != it)

    pick = max((it for it in short if ready(it)), key=lambda it: short[it], default=None)
    if pick is None:                                         # only raws are short: mine or import them
        raw = max((it for it in short if it in rt.RAW or not by_product.get(it)), key=lambda it: short[it])
        return {"kind": "supply", "what": raw, "rate": short[raw], "needs": [],
                "why": f"{why}: {raw} short {ledger.fmt_rate(short[raw])} - mine it or feed it in, "
                       f"then it goes in the notebook as `have`"}

    recipe = by_product[pick][0]
    machine = machine_for(recipe, tech.tiers(st["researched"]))
    hold = tech.unlocking(machine, st["researched"])        # nothing to build it with yet
    if hold:
        return research_move(hold[0], st, tech, f"{why}: {pick} needs {machine} to build it in", item)
    crafts = short[pick] / rt.net_output(recipe, pick)
    needs = [(i["name"], crafts * i["amount"]) for i in recipe["ingredients"] if i["name"] != pick]
    return {"kind": "scale" if st["builds"].get(pick) else "build", "what": pick, "rate": short[pick],
            "why": f"{why}: {pick} short {ledger.fmt_rate(short[pick])}"
                   + (f" of {ledger.fmt_rate(need[pick])} needed" if need[pick] > short[pick] else ""),
            "needs": needs, "tiers": tech.tiers(st["researched"])}


def machine_for(recipe, tiers):
    """The machine a print of this recipe would run on: the best tier already researched for its
    family, else what the generators default to."""
    cats = recipe.get("categories") or ["crafting"]
    fam = next((FAMILY[c] for c in cats if c in FAMILY), None)
    if fam:
        return tiers.get(fam) or TIERS[fam][0]              # nothing researched yet: the first tier
    if any(i["type"] == "fluid" for i in recipe["ingredients"] + recipe["results"]):
        return fluidcells.CATEGORY_MACHINE.get(next((c for c in cats if c in fluidcells.CATEGORY_MACHINE), ""), "")
    return mk.CATEGORY_MACHINE.get(next((c for c in cats if c in mk.CATEGORY_MACHINE), ""), "")


def research_move(name, st, tech, why, goal_item=None):
    units, packs, secs = tech.cost(name)
    unlocks = [e["recipe"] for e in (tech.all[name].get("effects") or []) if e.get("type") == "unlock-recipe"]
    trig = tech.trigger(name)
    if trig:                                                 # 2.0 trigger technology: no science at all
        return {"kind": "research", "what": name, "rate": 0.0, "needs": [], "unlocks": unlocks,
                "why": f"{why}: needs {name}, which is unlocked by doing it once - {trig}"}
    missing = [p for p in packs if st["made"].get(p, 0.0) <= SHORT]
    if missing and goal_item in missing:
        # bootstrap: the pack this research would let you build is the pack it costs. That is the
        # hand-crafting phase of a new game, so say so instead of deadlocking.
        return {"kind": "research", "what": name, "rate": 0.0, "needs": [], "unlocks": unlocks,
                "why": f"{why}: needs {name} ({units} x {'+'.join(packs)}) and nothing makes "
                       f"{', '.join(missing)} yet - hand-craft them into a lab this once"}
    if missing:                                              # a pack from an earlier rung is missing
        return {"kind": "blocked", "what": name, "rate": 0.0, "needs": [(p, 0.0) for p in missing],
                "why": f"{why}: needs {name}, which costs {units} x {'+'.join(packs)} "
                       f"and you make no {', '.join(missing)} yet"}
    rate = min(st["made"][p] for p in packs)
    return {"kind": "research", "what": name, "rate": 0.0, "needs": [],
            "why": f"{why}: needs {name} ({units} x {'+'.join(packs)}, {secs}s each"
                   + (f", about {units / rate / 60:.0f} min at {ledger.fmt_rate(rate)})" if rate > 0 else ")"),
            "unlocks": unlocks}


def blueprint(move, tiers, n):
    """Run make.py for a build/scale move and keep the result under the move's number, so a later
    scale of the same item does not overwrite the print you already placed. (path, size) or (None, why)."""
    os.makedirs(OUT, exist_ok=True)
    args = [sys.executable, os.path.join(ROOT, "03_blueprint_objects", "make.py"),
            move["what"], f"{move['rate']:.4g}", "-o", OUT, "--no-render"]
    if tiers.get("belt"):
        args += ["--belt", tiers["belt"]]
    if tiers.get("assembler"):
        args += ["--machine", tiers["assembler"]]
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode != 0:
        return None, (p.stdout + p.stderr).strip().splitlines()[-1][:100]
    head = next((ln for ln in p.stdout.splitlines() if " tiles," in ln), "")
    used = re.search(r"\d+x ([a-z0-9-]+)", p.stdout)
    move["machine"] = used[1] if used else (tiers.get("assembler") or "?")
    kept = None
    for ext in (".txt", ".module.json"):
        src = os.path.join(OUT, move["what"] + ext)
        if os.path.exists(src):
            dst = os.path.join(OUT, f"{n:02d}-{move['what']}{ext}")
            os.replace(src, dst)
            kept = kept or dst
    return kept, head.strip()


def show(move, tiers, upgrades):
    n = len(ledger.read(ledger.NOTEBOOK)) + 1
    print(f"NEXT MOVE  #{n}")
    kind = move["kind"].upper()
    what = f"{move['what']} {ledger.fmt_rate(move['rate'])}" if move["rate"] else move["what"]
    print(f"{kind:<9}{what}")
    print(f"  why    {move['why']}")
    if move.get("needs"):
        print("  needs  " + ", ".join(f"{i} +{ledger.fmt_rate(r)}" if r else i for i, r in move["needs"]))
    if move.get("unlocks"):
        print("  gives  " + ", ".join(move["unlocks"][:8]))
    if move["kind"] in ("build", "scale"):
        path, txt = blueprint(move, tiers, n)
        move["locked"] = bool(move.get("machine")) and move["machine"] not in move.get("have_recipes", [])
        move["print"] = os.path.relpath(path, HERE) if path else ""
        print(f"  print  {os.path.relpath(path, ROOT)}   {txt}" if path else f"  print  no blueprint: {txt}")
        print(f"  tiers  {move.get('machine')}, {tiers.get('belt')}")
        if move.get("locked"):
            print(f"  note   {move['machine']} is not researched yet - the print assumes it; "
                  f"build it by hand at the tier you have until then")
    for u in upgrades:
        print(f"  UPGRADE {u}")
    if move["kind"] not in ("done", "blocked"):
        print("\n[a]ccept -> appends to notebook.md   [s]kip   [w]hy")


SPEED = {"assembling-machine-1": 0.5, "assembling-machine-2": 0.75, "assembling-machine-3": 1.25,
         "stone-furnace": 1.0, "steel-furnace": 2.0, "electric-furnace": 2.0,
         "transport-belt": 15.0, "fast-transport-belt": 30.0, "express-transport-belt": 45.0,
         "turbo-transport-belt": 60.0}


def upgrades_available(st, tech):
    """Tiers research has unlocked that the ledger's own builds do not use yet. Each build records the
    tier it was made at in its note, so this is what you would gain by rebuilding them."""
    best, out = tech.tiers(st["researched"]), []
    old = {}                                            # tier used -> how many builds use it
    for ln in ledger.read(ledger.NOTEBOOK):
        if ln.move in ("build", "scale") and "[" in ln.note:
            for word in ln.note.split("[", 1)[1].strip("]").split():
                old[word] = old.get(word, 0) + 1
    for kind, top in best.items():
        if not top:
            continue
        behind = {t: n for t, n in old.items()                       # only actual upgrades, never
                  if t in TIERS[kind] and TIERS[kind].index(t) < TIERS[kind].index(top)}
        if not behind:
            continue
        worst = min(behind, key=lambda t: TIERS[kind].index(t))
        gain = SPEED.get(top, 0) / SPEED.get(worst, 1) if SPEED.get(worst) else 0
        out.append(f"{kind}: {sum(behind.values())} build(s) on {worst}, {top} is researched"
                   + (f" ({gain:.2g}x each, no extra ground)" if gain > 1 else ""))
    return out


def cmd_status(args):
    rt, recipes, by_product = rt_and_recipes()
    lines = ledger.read(ledger.NOTEBOOK)
    st = ledger.state(lines, rt, by_product)
    tech = Tech(recipes)
    g = goal(st)
    print(f"NOTEBOOK   {len(lines)} moves, {len(st['researched'])} technologies researched")
    print(f"MILESTONE  {g[2] if g else 'ladder complete'}"
          + (f" (making {st['made'].get(g[0], 0.0) * 60:.3g}/min of {g[1] * 60:.3g}/min)" if g else ""))
    t = tech.tiers(st["researched"])
    print(f"TIERS      {t['assembler']}, {t['belt']}, {t['furnace']}, {t['inserter']}")
    avail = tech.available(st["researched"])
    print(f"RESEARCH   {len(avail)} available now: " + ", ".join(avail[:6]) + (" ..." if len(avail) > 6 else ""))
    rows = sorted(set(st["made"]) | set(st["used"]), key=lambda i: -abs(st["net"].get(i, 0)))
    if rows:
        print(f"\n{'ITEM':<28}{'MADE':>10}{'USED':>10}{'NET':>10}")
        for it in rows:
            print(f"{it:<28}{ledger.fmt_rate(st['made'].get(it, 0)):>10}"
                  f"{ledger.fmt_rate(st['used'].get(it, 0)):>10}{ledger.fmt_rate(st['net'].get(it, 0)):>10}")
    return 0


def cmd_next(args):
    rt, recipes, by_product = rt_and_recipes()
    st = ledger.state(ledger.read(ledger.NOTEBOOK), rt, by_product)
    tech = Tech(recipes)
    move = next_move(st, tech, rt, by_product)
    tiers = tech.tiers(st["researched"])
    move["have_recipes"] = sorted(tech.recipes(st["researched"]))
    show(move, tiers, upgrades_available(st, tech) if move["kind"] != "done" else [])
    with open(PENDING, "w") as f:
        json.dump(move, f)
    writable = move["kind"] in ("build", "scale", "research", "supply")
    if args.accept and writable:
        return cmd_accept(args)
    while writable and sys.stdin.isatty():
        try:
            key = input("> ").strip().lower()[:1]
        except EOFError:
            return 0
        if key == "a":
            return cmd_accept(args)
        if key == "w":
            why(move, st, tech, rt, by_product)
            continue
        return 0
    return 0


def why(move, st, tech, rt, by_product):
    """What the goal still needs and what the ledger makes of it, biggest gap first."""
    g = goal(st)
    if not g:
        return
    item, want, _, rung = g
    need = demand(st, rt, by_product, tech.recipes(st["researched"]), rung)
    print(f"{'ITEM':<28}{'NEEDED':>10}{'MADE':>10}{'SHORT':>10}")
    rows = sorted(need, key=lambda i: -(max(need[i], st["used"].get(i, 0)) - st["made"].get(i, 0.0)))
    for it in rows[:14]:
        short = max(need[it], st["used"].get(it, 0.0)) - st["made"].get(it, 0.0)
        print(f"{it:<28}{ledger.fmt_rate(need[it]):>10}{ledger.fmt_rate(st['made'].get(it, 0.0)):>10}"
              f"{(ledger.fmt_rate(short) if short > SHORT else '-'):>10}")


def cmd_accept(args):
    if not os.path.exists(PENDING):
        sys.exit("no pending move: run plan.py next first")
    with open(PENDING) as f:
        move = json.load(f)
    kind = {"supply": "have", "research": "research"}.get(move["kind"], move["kind"])
    if kind not in ledger.MOVES:
        sys.exit(f"move {move['kind']} is not something to write down")
    rate = ledger.fmt_rate(move["rate"]) if move["rate"] else ""
    note = ""
    if kind in ("build", "scale"):
        t = move.get("tiers") or {}
        note = (move.get("print", "") + f" [{move.get('machine') or '?'} {t.get('belt') or '?'}]").strip()
    ln = ledger.append(kind, move["what"], rate, note, ledger.NOTEBOOK)
    print(f"wrote to {os.path.relpath(ledger.NOTEBOOK, os.getcwd()) if ledger.NOTEBOOK.startswith(ROOT) else ledger.NOTEBOOK}:")
    print(ln.row())
    os.remove(PENDING)
    return 0


def cmd_log(args):
    if args.move not in ledger.MOVES:
        sys.exit(f"move must be one of {', '.join(ledger.MOVES)}")
    ln = ledger.append(args.move, args.what, args.rate or "", args.note or "", ledger.NOTEBOOK)
    print(ln.row())
    return 0


def cmd_ladder(args):
    rt, recipes, by_product = rt_and_recipes()
    st = ledger.state(ledger.read(ledger.NOTEBOOK), rt, by_product)
    print(f"{'GOAL':<28}{'TARGET':>10}{'NOW':>10}  ")
    for item, spm in LADDER:
        want = st["targets"].get(item, spm / 60)
        now = st["net"].get(item, 0.0)
        mark = "ok" if now >= want - EPS else "<- next" if goal(st) and goal(st)[0] == item else ""
        print(f"{item:<28}{spm:>7}/min{now * 60:>9.3g}/min  {mark}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--notebook", metavar="FILE", help="use another notebook (one per save game)")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status")
    n = sub.add_parser("next")
    n.add_argument("--accept", action="store_true", help="write the move to the notebook straight away")
    sub.add_parser("accept")
    lg = sub.add_parser("log")
    lg.add_argument("move")
    lg.add_argument("what")
    lg.add_argument("rate", nargs="?")
    lg.add_argument("note", nargs="?")
    sub.add_parser("ladder")
    args = ap.parse_args()
    if args.notebook:
        ledger.NOTEBOOK = os.path.abspath(args.notebook)
    return {"status": cmd_status, "next": cmd_next, "accept": cmd_accept, "log": cmd_log,
            "ladder": cmd_ladder}.get(args.cmd, cmd_status)(args)


if __name__ == "__main__":
    sys.exit(main())
