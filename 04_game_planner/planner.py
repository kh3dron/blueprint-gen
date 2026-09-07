"""The next move, worked out from a Factory.

The milestone ladder in LADDER sets the goal: the first science pack the factory does not make at its
target rate. Then, in order:

  1. if the goal's recipe is locked, or a recipe on the way to it is, or there is no machine researched
     to build it in, the move is the next researchable technology toward it, prerequisites first
  2. otherwise the recipe tree of every rung up to the goal is expanded - the earlier rungs keep
     consuming while you build the next - and compared with what the factory makes
  3. the move is the largest shortfall whose own ingredients are not themselves short, so producers
     always come before consumers

A move is an object: print it for the report, `f.apply(move)` to take it.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "03_blueprint_objects"))
import fluidcells                                  # noqa: E402
import make as mk                                  # noqa: E402
from factory import Rate, Text, Module, data, FAMILY, supported_tier   # noqa: E402
from tech import PACKS, TIERS                      # noqa: E402

SHORT = 0.005          # items/s: below this a shortfall is rounding, not a move
LADDER = [(p, 10) for p in PACKS[:4]] + [(p, 100) for p in PACKS]


class Move:
    """What to do next. `f.apply(move)` takes it."""

    def __init__(self, kind, what, r=0.0, why="", needs=(), unlocks=(), note=""):
        self.kind, self.what, self.rate = kind, what, Rate(r)
        self.why, self.needs, self.unlocks, self.note = why, list(needs), list(unlocks), note

    def __repr__(self):
        head = f"{self.kind.upper():<9}{self.what}"
        if self.rate:
            head += f"  {self.rate.per_min:.4g}/min"
        out = [head, f"  why    {self.why}"]
        if self.needs:
            out.append("  needs  " + ", ".join(f"{i} +{Rate(r).per_min:.4g}/min" for i, r in self.needs))
        if self.unlocks:
            out.append("  gives  " + ", ".join(self.unlocks[:8]))
        if self.note:
            out.append(f"  note   {self.note}")
        if self.kind in ("build", "scale"):
            out.append("  take it with  f.apply(move)   ->  adds the module to the factory")
        elif self.kind == "research":
            out.append("  take it with  f.apply(move)   ->  marks it researched")
        return "\n".join(out)

    _repr_pretty_ = None


def requirements(item, r, rt, by_product, buildable):
    """item -> items/s needed to sustain `r` of `item`, stopping at raws and locked recipes."""
    need = {}

    def walk(it, v, seen):
        need[it] = need.get(it, 0.0) + v
        recipe = (by_product.get(it) or [None])[0]
        if recipe is None or recipe["name"] not in buildable or it in rt.RAW or it in seen:
            return
        crafts = v / rt.net_output(recipe, it)
        for ing in recipe["ingredients"]:
            if ing["name"] != it:
                walk(ing["name"], crafts * ing["amount"], seen | {it})

    walk(item, float(r), frozenset())
    return need


def demand(st, rt, by_product, buildable, upto):
    """Everything needed to keep every rung up to `upto` running at once."""
    want = {}
    for item, spm in LADDER[:upto + 1]:
        want[item] = max(want.get(item, 0.0), st["targets"].get(item, spm / 60))
    total = {}
    for item, r in want.items():
        for k, v in requirements(item, r, rt, by_product, buildable).items():
            total[k] = total.get(k, 0.0) + v
    return total


def goal(st):
    """(item, items/s, why, rung) for the first unmet rung, or None."""
    for i, (item, spm) in enumerate(LADDER):
        want = st["targets"].get(item, spm / 60)
        if st["made"].get(item, 0.0) < want - SHORT:
            return item, want, f"{item} at {spm}/min", i
    for item, want in st["targets"].items():
        if st["made"].get(item, 0.0) < want - SHORT:
            return item, want, f"target {item} {want * 60:.4g}/min", len(LADDER) - 1
    return None


def machine_for(recipe, tiers):
    """The machine you would actually put this recipe in: the best researched tier of its family. This
    is what the research gate asks for - you can smelt in stone furnaces long before electric ones."""
    cats = recipe.get("categories") or ["crafting"]
    fam = next((FAMILY[c] for c in cats if c in FAMILY), None)
    if fam:
        return tiers.get(fam) or TIERS[fam][0]
    if any(i["type"] == "fluid" for i in recipe["ingredients"] + recipe["results"]):
        return fluidcells.CATEGORY_MACHINE.get(next((c for c in cats if c in fluidcells.CATEGORY_MACHINE), ""), "")
    return mk.CATEGORY_MACHINE.get(next((c for c in cats if c in mk.CATEGORY_MACHINE), ""), "")


def print_machine(recipe, tiers):
    """The machine the blueprint will use, which is the best one the cell generators can place."""
    cats = recipe.get("categories") or ["crafting"]
    fam = next((FAMILY[c] for c in cats if c in FAMILY), None)
    if fam:
        return supported_tier(fam, machine_for(recipe, tiers)) or machine_for(recipe, tiers)
    return machine_for(recipe, tiers)


def research_move(name, st, tech, why, goal_item=None):
    units, packs, secs = tech.cost(name)
    unlocks = [e["recipe"] for e in (tech.all[name].get("effects") or []) if e.get("type") == "unlock-recipe"]
    trig = tech.trigger(name)
    if trig:
        return Move("research", name, why=f"{why}: needs {name}, unlocked by doing it once - {trig}",
                    unlocks=unlocks)
    missing = [p for p in packs if st["made"].get(p, 0.0) <= SHORT]
    if missing and goal_item in missing:
        # the pack this research would let you build is the pack it costs: the opening bootstrap
        return Move("research", name, unlocks=unlocks,
                    why=f"{why}: needs {name} ({units} x {'+'.join(packs)}) and nothing makes "
                        f"{', '.join(missing)} yet - hand-craft them into a lab this once")
    if missing:
        return Move("blocked", name, needs=[(p, 0.0) for p in missing],
                    why=f"{why}: needs {name}, which costs {units} x {'+'.join(packs)} and you make "
                        f"no {', '.join(missing)} yet")
    r = min(st["made"][p] for p in packs)
    return Move("research", name, unlocks=unlocks,
                why=f"{why}: needs {name} ({units} x {'+'.join(packs)}, {secs}s each"
                    + (f", about {units / r / 60:.0f} min at {r * 60:.4g}/min)" if r > 0 else ")"))


def next_move(f):
    """The move to make now, given a Factory."""
    rt, _, by_product, tech = data()
    st = f.state()
    g = goal(st)
    if g is None:
        return Move("done", "", why="every rung of the ladder is met")
    item, want, why, rung = g
    buildable = tech.recipes(st["researched"])
    tiers = f.tiers()

    chain = tech.unlocking((by_product.get(item) or [{"name": item}])[0]["name"], st["researched"])
    need = demand(st, rt, by_product, buildable, rung)
    for it in sorted(need, key=lambda i: -need[i]):
        r = (by_product.get(it) or [None])[0]
        if r is not None and it not in rt.RAW and r["name"] not in buildable and st["made"].get(it, 0) < need[it]:
            chain = chain or tech.unlocking(r["name"], st["researched"])
    if chain:
        return research_move(chain[0], st, tech, why, item)

    def gap(it):
        return max(need.get(it, 0.0), st["used"].get(it, 0.0)) - st["made"].get(it, 0.0)

    short = {it: gap(it) for it in need if gap(it) > SHORT}
    if not short:
        return Move("done", item, want, why=f"{why}: every input is produced, the rung is only waiting "
                                            f"on labs")

    def ready(it):
        recipe = (by_product.get(it) or [None])[0]
        if recipe is None or it in rt.RAW:
            return False
        return not any(i["name"] in short for i in recipe["ingredients"] if i["name"] != it)

    pick = max((it for it in short if ready(it)), key=lambda it: short[it], default=None)
    if pick is None:
        raw = max((it for it in short if it in rt.RAW or not by_product.get(it)), key=lambda it: short[it])
        return Move("supply", raw, short[raw],
                    why=f"{why}: {raw} short {short[raw] * 60:.4g}/min - mine it or feed it in, then "
                        f"f.have({raw!r}, {short[raw] * 60:.4g})")

    recipe = by_product[pick][0]
    machine = machine_for(recipe, tiers)
    hold = tech.unlocking(machine, st["researched"])
    if hold:
        return research_move(hold[0], st, tech, f"{why}: {pick} needs {machine} to build it in", item)
    crafts = short[pick] / rt.net_output(recipe, pick)
    needs = [(i["name"], crafts * i["amount"]) for i in recipe["ingredients"] if i["name"] != pick]
    printed = print_machine(recipe, tiers)
    note = ""
    if printed != machine:
        note = (f"the print uses {printed} (the cells are built around 3x3 machines); you have "
                f"{machine}, so place those by hand - the rates are the same either way")
    return Move("scale" if st["builds"].get(pick) else "build", pick, short[pick], needs=needs, note=note,
                why=f"{why}: {pick} short {short[pick] * 60:.4g}/min"
                    + (f" of {need[pick] * 60:.4g}/min needed" if need[pick] > short[pick] else ""))


def apply(f, move):
    """Take a move: add the module it asks for, mark the research, or log the supply."""
    if move.kind in ("build", "scale"):
        _, _, by_product, _ = data()
        m = Module(move.what, f"{float(move.rate)}/s", belt=f.tiers().get("belt") or "transport-belt",
                   machine=print_machine(by_product[move.what][0], f.tiers()))
        f.add(m)
        return m
    if move.kind == "research":
        f.research(move.what)
        return move.what
    if move.kind == "supply":
        f.have(move.what, f"{float(move.rate)}/s")
        return move.what
    raise ValueError(f"{move.kind} is not a move you can apply")


def upgrades(f):
    """Tiers research has unlocked that the factory's modules do not use yet, and what they would buy."""
    best, out = f.tiers(), []
    for kind, top in best.items():
        if not top:
            continue
        behind = [m for m in f.modules
                  if (m.belt if kind == "belt" else m.machine) in TIERS[kind]
                  and TIERS[kind].index(m.belt if kind == "belt" else m.machine) < TIERS[kind].index(top)]
        if not behind:
            continue
        gain = 0.0
        for m in behind:
            before = m.throughput()
            keep = (m.belt, m.machine)
            m.upgrade(top)
            gain += float(m.throughput() - before)
            m.belt, m.machine = keep
        out.append(f"{kind}: {len(behind)} module(s) below {top}"
                   + (f", +{gain * 60:.4g}/min in total by upgrading in place" if gain > SHORT
                      else " (they are not belt-limited, so it buys nothing yet)"))
    return out


def ladder_table(f):
    st = f.state()
    g = goal(st)
    out = [f"{'GOAL':<28}{'TARGET':>10}{'NOW':>12}"]
    for item, spm in LADDER:
        want = st["targets"].get(item, spm / 60)
        now = st["made"].get(item, 0.0) * 60
        mark = "  ok" if now >= want * 60 - SHORT else ("  <- next" if g and g[0] == item and
                                                        abs(g[1] - want) < SHORT else "")
        out.append(f"{item:<28}{spm:>7}/min{now:>9.4g}/min{mark}")
    return Text("\n".join(out))


def status(f):
    _, _, _, tech = data()
    st = f.state()
    g = goal(st)
    t = f.tiers()
    avail = tech.available(st["researched"])
    out = [f"FACTORY    {len(f.modules)} modules, {len(f.supply)} supplied, "
           f"{len(f.researched)} technologies researched",
           f"MILESTONE  {g[2] if g else 'ladder complete'}"
           + (f" (making {st['made'].get(g[0], 0.0) * 60:.4g}/min of {g[1] * 60:.4g}/min)" if g else ""),
           f"TIERS      {t['assembler']}, {t['belt']}, {t['furnace']}, {t['inserter']}",
           f"RESEARCH   {len(avail)} available now: " + ", ".join(avail[:6]) + (" ..." if len(avail) > 6 else "")]
    for u in upgrades(f):
        out.append(f"UPGRADE    {u}")
    return Text("\n".join(out) + "\n\n" + f.table())
