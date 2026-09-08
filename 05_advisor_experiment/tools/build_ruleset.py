#!/usr/bin/env python3
"""Regenerate the reviewed subset from local legacy caches; not needed to run the experiment.

This is a transitional data authoring tool, not a full Factorio data-stage export.
Run from any directory. It writes only this experiment's rules/nauvis.json.
"""
from hashlib import sha256
import json
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
DATA = HERE.parent / "data"
NAMES = """iron-plate copper-plate iron-gear-wheel copper-cable electronic-circuit
stone-furnace burner-mining-drill assembling-machine-1 assembling-machine-2 assembling-machine-3
lab offshore-pump boiler steam-engine small-electric-pole pipe transport-belt inserter wooden-chest
automation-science-pack oil-refinery chemical-plant basic-oil-processing advanced-oil-processing
heavy-oil-cracking light-oil-cracking plastic-bar sulfur""".split()


def main():
    cache = json.loads((DATA / "recipes.json").read_text())
    base = {r["name"]: r for r in cache if r["__src"].endswith("base/prototypes/recipe.lua")}
    technologies = {t["name"]: t for t in json.loads((DATA / "technologies.json").read_text())}
    unlocks = {}
    for name, tech in technologies.items():
        for effect in tech.get("effects", []):
            if effect.get("type") == "unlock-recipe":
                unlocks.setdefault(effect["recipe"], []).append(name)
    recipes, items = {}, {}
    for name in NAMES:
        r = base[name]
        recipes[name] = {"category": (r.get("categories") or ["crafting"])[0],
                         "seconds": r.get("energy_required", 0.5),
                         "enabled": r.get("enabled", True), "unlocked_by": unlocks.get(name, []),
                         "inputs": {i["name"]: i["amount"] for i in r["ingredients"]},
                         "outputs": {i["name"]: i["amount"] for i in r["results"]}}
        for entry in r["ingredients"] + r["results"]:
            items[entry["name"]] = entry["type"]
    included = set()

    def include(name):
        if name in included:
            return
        included.add(name)
        for parent in technologies[name].get("prerequisites", []):
            include(parent)

    for recipe in recipes.values():
        for name in recipe["unlocked_by"]:
            include(name)
    normalized_tech = {}
    for name in sorted(included):
        t = technologies[name]
        unit = t.get("unit") or {}
        normalized_tech[name] = {"prerequisites": t.get("prerequisites", []),
                                 "trigger": t.get("research_trigger"),
                                 "count": unit.get("count", 0), "seconds": unit.get("time", 0),
                                 "packs": dict(unit.get("ingredients", []))}
        for item in normalized_tech[name]["packs"]:
            items[item] = "item"
    machines = {
        "stone-furnace": {"speed": 1, "categories": ["smelting"], "electric_kw": 0,
                          "fuel": "coal", "fuel_kw": 90, "size": [2, 2]},
        "assembling-machine-1": {"speed": 0.5, "categories": ["crafting"], "electric_kw": 75, "size": [3, 3]},
        "assembling-machine-2": {"speed": 0.75, "categories": ["crafting"], "electric_kw": 150, "size": [3, 3]},
        "assembling-machine-3": {"speed": 1.25, "categories": ["crafting"], "electric_kw": 375, "size": [3, 3]},
        "oil-refinery": {"speed": 1, "categories": ["oil-processing"], "electric_kw": 420, "size": [5, 5]},
        "chemical-plant": {"speed": 1, "categories": ["chemistry"], "electric_kw": 210, "size": [3, 3]},
        "lab": {"speed": 1, "categories": [], "electric_kw": 60, "size": [3, 3]},
    }
    defaults = {name: name for name in recipes if name in recipes[name]["outputs"]}
    defaults.update({"petroleum-gas": "basic-oil-processing", "heavy-oil": "advanced-oil-processing",
                     "light-oil": "advanced-oil-processing"})
    sources = ["base/prototypes/recipe.lua", "base/prototypes/technology.lua", "base/prototypes/entity/entities.lua"]
    version = json.loads((DATA / "base/info.json").read_text())["version"]
    document = {
        "schema_version": 1,
        "id": f"nauvis-opening-{version}-v1",
        "factorio_version": version,
        "mods": {"base": version},
        "provenance": {
            "kind": "reviewed-prototype-subset",
            "note": "Recipes/technology from selected base prototypes; machine constants manually checked. Not an engine-exported or in-game-certified dataset.",
            "source_sha256": {p: sha256((DATA / p).read_bytes()).hexdigest() for p in sources},
            "quality": "normal", "modifications": "No expansion data; no modules, beacons or productivity.",
        },
        "items": dict(sorted(items.items())),
        "raw_items": ["iron-ore", "copper-ore", "coal", "stone", "wood", "water", "crude-oil"],
        "hand_collectable": ["iron-ore", "copper-ore", "coal", "stone", "wood"],
        "fuel_kj": {"coal": 4000},
        "recipes": recipes,
        "machines": machines,
        "default_recipes": defaults,
        "default_machines": {"crafting": "assembling-machine-1", "smelting": "stone-furnace",
                             "chemistry": "chemical-plant", "oil-processing": "oil-refinery"},
        "technologies": normalized_tech,
    }
    destination = HERE / "rules" / "nauvis.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(document, indent=2) + "\n")
    print(f"Wrote {destination}: {len(recipes)} recipes, {len(normalized_tech)} technologies")


if __name__ == "__main__":
    main()
