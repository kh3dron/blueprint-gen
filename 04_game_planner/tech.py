"""Technology tree: what is researched, what can be researched now, what that unlocks.

Technologies come from data/*/prototypes/technology.lua through 01_recipe_generatpr/extract.lua with
WANT=technology, cached in data/technologies.json exactly like recipes.json. A technology carries its
prerequisites, its unit (how many of which science packs, and the seconds each takes) and its effects;
the only effect this reads is unlock-recipe.

A recipe is available when it is enabled from the start or some researched technology unlocks it, so
machine and belt tiers fall out of the same set: the best assembling machine is the last one in TIERS
whose recipe is available.
"""
import json
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
CACHE = os.path.join(DATA, "technologies.json")
SOURCES = ["base/prototypes/technology.lua"]        # space-age and quality need their own item data
EXTRACT = os.path.join(ROOT, "01_recipe_generatpr", "extract.lua")

# name -> tiers, worst first. The planner suggests an upgrade when a later one becomes available.
TIERS = {
    "belt": ["transport-belt", "fast-transport-belt", "express-transport-belt", "turbo-transport-belt"],
    "assembler": ["assembling-machine-1", "assembling-machine-2", "assembling-machine-3"],
    "furnace": ["stone-furnace", "steel-furnace", "electric-furnace"],
    "inserter": ["inserter", "fast-inserter", "bulk-inserter"],
}
PACKS = ["automation-science-pack", "logistic-science-pack", "military-science-pack",
         "chemical-science-pack", "production-science-pack", "utility-science-pack"]


def load():
    """[technology], regenerating the cache when the prototypes are newer."""
    srcs = [os.path.join(DATA, s) for s in SOURCES]
    if not os.path.exists(CACHE) or any(os.path.getmtime(s) > os.path.getmtime(CACHE) for s in srcs):
        with open(CACHE, "w") as f:
            subprocess.run(["luajit", EXTRACT] + srcs, stdout=f, check=True,
                           env=dict(os.environ, WANT="technology"))
    with open(CACHE) as f:
        return json.load(f)


class Tech:
    def __init__(self, recipes):
        self.all = {t["name"]: t for t in load()}
        self.enabled = {r["name"] for r in recipes if r.get("enabled", True)}
        self.unlocks = {}                                  # recipe -> technology that unlocks it
        for t in self.all.values():
            for e in t.get("effects") or []:
                if e.get("type") == "unlock-recipe":
                    self.unlocks.setdefault(e["recipe"], t["name"])

    # ---- state ---------------------------------------------------------------------------
    def available(self, researched):
        """Technologies whose prerequisites are all researched, and which are not researched yet."""
        return sorted(n for n, t in self.all.items()
                      if n not in researched and set(t.get("prerequisites") or []) <= set(researched))

    def recipes(self, researched):
        """Recipe names buildable with this research: enabled from the start, plus every unlock."""
        out = set(self.enabled)
        for n in researched:
            for e in (self.all.get(n) or {}).get("effects") or []:
                if e.get("type") == "unlock-recipe":
                    out.add(e["recipe"])
        return out

    def tiers(self, researched):
        """kind -> the best tier available, e.g. {"belt": "fast-transport-belt", ...}."""
        have = self.recipes(researched)
        return {kind: ([t for t in names if t in have] or [None])[-1] for kind, names in TIERS.items()}

    def cost(self, name):
        """(units, [pack], seconds each) for one technology. Both are 0 for a 2.0 trigger technology,
        which is unlocked by doing something in the world instead of by science."""
        u = (self.all.get(name) or {}).get("unit") or {}
        return u.get("count", 0), [p[0] for p in u.get("ingredients") or []], u.get("time", 0)

    def trigger(self, name):
        """"craft 10 copper-plate" for a trigger technology, else None."""
        t = (self.all.get(name) or {}).get("research_trigger")
        if not t:
            return None
        kind = t.get("type", "").replace("-", " ")
        what = t.get("item") or t.get("entity") or t.get("fluid") or ""
        return f"{kind} {t.get('count', 1)} {what}".replace("  ", " ").strip()

    # ---- planning ------------------------------------------------------------------------
    def path_to(self, name, researched):
        """Unresearched technologies needed before `name`, prerequisites first, `name` last."""
        out, seen = [], set()

        def walk(n):
            if n in researched or n in seen or n not in self.all:
                return
            seen.add(n)
            for p in self.all[n].get("prerequisites") or []:
                walk(p)
            out.append(n)

        walk(name)
        return out

    def unlocking(self, recipe, researched):
        """The technology chain that would make `recipe` buildable, or [] if it already is."""
        if recipe in self.recipes(researched):
            return []
        t = self.unlocks.get(recipe)
        return self.path_to(t, researched) if t else []
