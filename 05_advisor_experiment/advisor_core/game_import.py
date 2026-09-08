"""Convert bounded observer exports without inventing routing or power facts."""
from copy import deepcopy
from hashlib import sha256
import json

from .model import Snapshot, integer, number
from .rules import Rules

OBSERVER = "blueprint-gen-observer"
OBSERVER_VERSIONS = ("0.1.0", "0.2.0", "0.3.0")


def digest(document):
    return sha256(json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def mapping(value, field):
    # Factorio serializes an empty Lua table as [], including empty dictionaries.
    if value == []:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def sequence(value, field):
    if value == {}:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    return value


def validate_capture(capture):
    if not isinstance(capture, dict) or capture.get("export_schema_version") != 1:
        raise ValueError("unsupported observer export schema")
    exporter = capture.get("exporter")
    if not isinstance(exporter, dict) or exporter.get("name") != OBSERVER or exporter.get("version") not in OBSERVER_VERSIONS:
        raise ValueError("unsupported observer exporter/version")
    version = capture.get("factorio_version")
    if not isinstance(version, str) or not version.startswith("2.1."):
        raise ValueError("this observer importer supports Factorio 2.1 only")
    if capture.get("active_mods") != {"base": version, OBSERVER: exporter["version"]}:
        raise ValueError("import requires exactly base plus blueprint-gen-observer; other mods need a new validated profile")
    integer(capture.get("tick"), "capture.tick")
    integer(capture.get("generation"), "capture.generation")
    if not isinstance(capture.get("scope"), dict) or capture["scope"].get("surface_name") != "nauvis":
        raise ValueError("capture must describe a bounded Nauvis scope")
    sequence(capture.get("machines"), "capture.machines")
    if not isinstance(capture.get("player"), dict):
        raise ValueError("capture must include inventory observation metadata")
    sequence(capture["player"].get("inventory"), "capture.player.inventory")
    if type(capture["player"].get("inventory_observed")) is not bool:
        raise ValueError("capture must identify whether player inventory was observed")
    seen = set()
    for m in capture["machines"]:
        if not isinstance(m, dict) or not isinstance(m.get("id"), str) or not m["id"] or m["id"] in seen:
            raise ValueError("captured machine ids must be unique nonempty strings")
        seen.add(m["id"])
        if m.get("quality") != "normal" or m.get("recipe_quality", "normal") != "normal":
            raise ValueError(f"machine {m['id']} uses unsupported quality")
        if m.get("modules") not in ([], {}) or m.get("speed_bonus", 0) != 0 or m.get("productivity_bonus", 0) != 0:
            raise ValueError(f"machine {m['id']} uses unsupported modules/beacons/bonuses")
        for field in ("built", "active"):
            if type(m.get(field)) is not bool:
                raise ValueError(f"captured machine {m['id']}.{field} must be boolean")
        number(m.get("energy_j"), f"{m['id']}.energy_j")
        if "products_finished" in m:
            integer(m["products_finished"], f"{m['id']}.products_finished")
    return capture


def amounts(entries, field):
    entries = sequence(entries, field)
    result = {}
    for entry in entries:
        if entry.get("probability", 1) != 1 or "amount_min" in entry or "amount_max" in entry:
            raise ValueError(f"{field}: stochastic products are not supported")
        amount = number(entry.get("amount"), f"{field}.amount", positive=True)
        name = entry["name"]
        result[name] = result.get(name, 0) + amount
    return result


def runtime_rules(capture, policy=None):
    """Use exported runtime mechanics; retain only the reviewed recipe-selection policy."""
    validate_capture(capture)
    policy = policy or Rules.load()
    raw = capture["resolved_rules"]
    for key, expected in (("recipes", policy.recipes), ("machines", policy.machines), ("technologies", policy.technologies)):
        if set(raw[key]) != set(expected):
            raise ValueError(f"exported {key} do not match the observer's reviewed catalog")
    recipes, technologies = {}, {}
    for name, t in raw["technologies"].items():
        if t.get("count_formula"):
            raise ValueError(f"formula-based technology {name} is outside the opening profile")
        integer(t["count"], f"{name}.count")
        number(t["seconds"], f"{name}.seconds")
        trigger = deepcopy(t.get("trigger"))
        if trigger and trigger.get("type") == "craft-item":
            # Factorio 2.1 exports an ItemIDFilter, while the planning policy uses
            # an item name. Do not silently erase quality or comparator constraints.
            item = trigger.get("item")
            if isinstance(item, dict):
                if set(item) - {"name", "quality"} or item.get("quality", "normal") != "normal":
                    raise ValueError(f"{name}: unsupported crafting trigger item filter")
                item = item.get("name")
            if not isinstance(item, str) or item not in policy.items:
                raise ValueError(f"{name}: unknown crafting trigger item")
            integer(trigger.get("count", 1), f"{name}.trigger.count", positive=True)
            trigger["item"] = item
        prerequisites = sequence(t["prerequisites"], f"{name}.prerequisites")
        priority = policy.technologies[name]["prerequisites"]
        # Engine prerequisites are an unordered map exported in alphabetic order.
        # Preserve the reviewed scheduling order when the actual dependency set agrees.
        if set(prerequisites) == set(priority):
            prerequisites = list(priority)
        technologies[name] = {"prerequisites": prerequisites, "trigger": trigger,
                              "count": t["count"], "seconds": t["seconds"],
                              "packs": amounts(t["packs"], f"{name}.packs")}
    for name, r in raw["recipes"].items():
        previous_category = policy.recipes[name]["category"]
        if previous_category not in r["categories"]:
            raise ValueError(f"recipe category changed for {name}; review the planning policy")
        number(r["seconds"], f"{name}.seconds", positive=True)
        if type(r["enabled"]) is not bool:
            raise ValueError(f"recipe {name}.enabled must be boolean")
        recipes[name] = {"category": previous_category, "seconds": r["seconds"], "enabled": r["enabled"],
                         "inputs": amounts(r["inputs"], f"{name}.inputs"),
                         "outputs": amounts(r["outputs"], f"{name}.outputs"),
                         "unlocked_by": sorted(t for t, v in raw["technologies"].items() if name in v["unlocks"])}
    machines = {}
    for name, m in raw["machines"].items():
        number(m["speed"], f"{name}.speed", positive=True)
        number(m["electric_kw"], f"{name}.electric_kw")
        number(m["fuel_kw"], f"{name}.fuel_kw")
        machines[name] = {"speed": m["speed"], "categories": sequence(m["categories"], f"{name}.categories"), "electric_kw": m["electric_kw"], "size": m["size"]}
        if m["fuel_kw"]:
            machines[name].update(fuel="coal", fuel_kw=m["fuel_kw"])
    document = deepcopy(policy.document)
    version = capture["factorio_version"]
    document.update(id=f"nauvis-runtime-{version}-observer-v1", factorio_version=version,
                    mods=capture["active_mods"], recipes=recipes, technologies=technologies,
                    machines=machines, items=raw["items"], fuel_kj=raw["fuel_kj"],
                    provenance={"kind": "runtime-prototype-export", "exporter": capture["exporter"],
                                "policy_ruleset_sha256": policy.digest, "quality": "normal",
                                "note": "Mechanics exported after the game data stages; reviewed defaults select recipes/machines. Idle drain is recorded in the raw export but omitted by the flow model."})
    # Ensure every ingredient, product and supported machine category is represented.
    for name, r in recipes.items():
        if not (set(r["inputs"]) | set(r["outputs"])) <= set(document["items"]):
            raise ValueError(f"new items in runtime recipe {name}; extend the reviewed catalog")
    if document["items"] != policy.document["items"]:
        raise ValueError("exported item catalog differs from the reviewed profile")
    for name, t in technologies.items():
        if not set(t["prerequisites"]) <= set(technologies):
            raise ValueError(f"new prerequisites for {name}; extend the reviewed catalog")
        if not set(t["packs"]) <= set(document["items"]):
            raise ValueError(f"new science packs for {name}; extend the reviewed catalog")
    number(document["fuel_kj"]["coal"], "fuel_kj.coal", positive=True)
    return Rules(document, digest(document))


def review_template(capture):
    validate_capture(capture)
    return {"review_schema_version": 1, "capture_sha256": digest(capture),
            "goals_per_min": {"automation-science-pack": 10}, "require_lab": True,
            "supplies_per_s": None, "available_power_kw": None,
            "inventory": None,
            "machines": {m["id"]: {"connected": None, "output_open": None} for m in capture["machines"]},
            "instructions": "Fill only facts checked for this capture. Null means unknown; {} supply means confirmed zero. Inventory override is used only for a headless capture without player inventory. Power is the shared network's available generation after outside loads."}


def import_capture(capture, review=None):
    rules = runtime_rules(capture)
    review = review_template(capture) if review is None else deepcopy(review)
    if review.get("review_schema_version") != 1 or review.get("capture_sha256") != digest(capture):
        raise ValueError("review belongs to another capture; generate a fresh review instead of reusing old facts")
    gaps, notes, machines, inventory = [], [], [], {}
    capture_ids = {m["id"] for m in capture["machines"]}
    if not isinstance(review.get("machines"), dict) or set(review["machines"]) != capture_ids:
        raise ValueError("review machine ids must match this capture exactly")
    for stack in capture["player"]["inventory"]:
        integer(stack["count"], "inventory.count")
        if stack["name"] in rules.items and stack["quality"] == "normal":
            inventory[stack["name"]] = inventory.get(stack["name"], 0) + stack["count"]
        else:
            notes.append(f"Unmodeled inventory omitted: {stack['name']} ({stack['quality']})")
    if not capture["player"]["inventory_observed"]:
        if review.get("inventory") is None:
            gaps.append("Player inventory was not observed; confirm the finite accessible inventory.")
        else:
            inventory = mapping(review["inventory"], "review.inventory")
    elif review.get("inventory") is not None:
        raise ValueError("a review cannot replace player inventory that was actually observed")
    for m in capture["machines"]:
        if m["prototype"] not in rules.machines:
            raise ValueError(f"unsupported captured machine {m['prototype']}; use a smaller modeled scope")
        if not m.get("recipe") and m["prototype"] not in ("lab", "stone-furnace"):
            gaps.append(f"Observe a configured recipe for {m['id']} ({m['prototype']}) and export again; unconfigured hardware is not yet modeled.")
            continue
        if m.get("recipe") and m["recipe"] not in rules.recipes:
            raise ValueError(f"unsupported captured recipe {m['recipe']}")
        settings = review["machines"][m["id"]]
        if not isinstance(settings, dict):
            raise ValueError(f"{m['id']} review must be an object")
        flags = {}
        for field in ("connected", "output_open"):
            value = settings.get(field)
            if value is not None and type(value) is not bool:
                raise ValueError(f"{m['id']}.{field} review must be boolean or null")
            if field == "output_open" and m["status"] in ("full_output", "full_burnt_result_output"):
                # The game provides direct contrary evidence, even if a review says true.
                flags[field] = False
            elif value is None:
                gaps.append(f"Confirm {field.replace('_', ' ')} for {m['id']} ({m['prototype']}).")
                flags[field] = False
            else:
                flags[field] = value
        electric = rules.machines[m["prototype"]]["electric_kw"] > 0
        machines.append({"id": m["id"], "prototype": m["prototype"], "recipe": m.get("recipe"), "count": 1,
                         "built": m["built"], "position": m["position"], "active": m["active"], "status": m["status"],
                         "powered": bool(m.get("electric_network_id") and m["energy_j"] > 0 and m["status"] != "no_power") if electric else False,
                         **flags})
    networks = {m.get("electric_network_id") for m in capture["machines"] if m.get("electric_network_id") is not None}
    if len(networks) > 1:
        raise ValueError("capture spans multiple electric networks; this solver needs a smaller scope with one network")
    supply = review.get("supplies_per_s")
    if supply is None:
        gaps.append("Measure net input delivery rates; inventories and machine production are not external supply.")
        supply = {}
    else:
        supply = mapping(supply, "review.supplies_per_s")
    power = review.get("available_power_kw")
    if power is None:
        gaps.append("Confirm available electric generation after loads outside this scope.")
        power = 0
    number(power, "review.available_power_kw")
    # Includes review values and the exact capture: advice never borrows stale confirmations.
    revision = "import-" + digest({"capture": digest(capture), "review": review})[:24]
    observations = []
    progress = mapping(capture.get("research_units_completed", {}), "research_units_completed")
    for name in progress:
        if name not in rules.technologies:
            notes.append(f"Research progress outside the opening catalog omitted: {name}")
    observed = capture.get("observation")
    if observed:
        integer(observed.get("start_tick"), "observation.start_tick")
        integer(observed.get("end_tick"), "observation.end_tick")
        if observed["end_tick"] <= observed["start_tick"] or observed["end_tick"] != capture["tick"]:
            raise ValueError("monitored window must end at the export tick and have positive duration")
        produced = mapping(observed["produced"], "observation.produced")
        for item, quantity in produced.items():
            if item not in rules.items:
                raise ValueError(f"unmodeled observed product {item}")
            integer(quantity, f"observation.produced.{item}")
        if observed.get("valid") is True and not observed.get("invalid_reasons") and observed.get("source") == "automated" and observed.get("generation") == capture["generation"]:
            observations.append({"start_tick": observed["start_tick"], "end_tick": observed["end_tick"],
                                 "revision": revision, "source": "automated", "produced": produced})
        else:
            notes.append("Production window rejected: " + "; ".join(observed.get("invalid_reasons") or ["invalid source or configuration revision"]))
    document = {
        "schema_version": 1, "ruleset_id": rules.id, "ruleset_sha256": rules.digest,
        "factorio_version": capture["factorio_version"], "mods": capture["active_mods"], "surface": "nauvis",
        "tick": capture["tick"], "revision": revision, "inventory": inventory,
        "crafted": mapping(capture.get("crafted", {}), "crafted"), "researched": sequence(capture["researched"], "researched"),
        "research_units_completed": {t: count for t, count in progress.items() if t in rules.technologies},
        "supplies_per_s": supply, "goals_per_min": review["goals_per_min"], "selected_recipes": {},
        "power": {"available_kw": power, "required": True}, "require_lab": review["require_lab"],
        "machines": machines, "observations": observations, "observation_gaps": gaps,
        "provenance": {"source": "factorio-observer", "capture_sha256": digest(capture),
                       "scope": capture["scope"], "generation": capture["generation"], "notes": notes},
    }
    return Snapshot.from_dict(document, rules), rules
