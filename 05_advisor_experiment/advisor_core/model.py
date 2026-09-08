"""Validated snapshots. Rates use /s in storage; inventory is a finite item count."""
from copy import deepcopy
from dataclasses import dataclass
import json
import math
from pathlib import Path


def number(value, name, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be {'positive' if positive else 'nonnegative'}")
    return value


def integer(value, name, *, positive=False):
    number(value, name, positive=positive)
    if int(value) != value:
        raise ValueError(f"{name} must be an integer")
    return value


@dataclass(frozen=True)
class Snapshot:
    document: dict

    @classmethod
    def load(cls, path, rules):
        return cls.from_dict(json.loads(Path(path).read_text()), rules)

    @classmethod
    def from_dict(cls, document, rules):
        if not isinstance(document, dict):
            raise ValueError("snapshot must be a JSON object")
        d = deepcopy(document)
        if d.get("schema_version") != 1:
            raise ValueError("unsupported snapshot schema_version")
        if d.get("ruleset_id") != rules.id or d.get("ruleset_sha256") != rules.digest:
            raise ValueError("snapshot ruleset id/hash does not match the loaded ruleset")
        if d.get("factorio_version") != rules.document["factorio_version"]:
            raise ValueError("snapshot Factorio version does not match the ruleset")
        if d.get("mods") != rules.document["mods"] or d.get("surface") != "nauvis":
            raise ValueError("this experiment requires its pinned base-only Nauvis profile")
        integer(d.get("tick"), "tick")
        if not isinstance(d.get("revision"), str) or not d["revision"]:
            raise ValueError("snapshot requires a nonempty revision identifier")
        gaps = d.setdefault("observation_gaps", [])
        if not isinstance(gaps, list) or any(not isinstance(gap, str) or not gap for gap in gaps):
            raise ValueError("observation_gaps must be a list of explanations")
        for field in ("inventory", "crafted", "supplies_per_s", "goals_per_min"):
            values = d.setdefault(field, {})
            if not isinstance(values, dict):
                raise ValueError(f"{field} must be an object")
            for item, value in values.items():
                if item not in rules.items:
                    raise ValueError(f"unknown item {item!r} in {field}")
                number(value, f"{field}.{item}", positive=field == "goals_per_min")
                if field in ("inventory", "crafted"):
                    integer(value, f"{field}.{item}")
        if not d["goals_per_min"]:
            raise ValueError("snapshot must specify at least one goals_per_min target")
        researched = d.setdefault("researched", [])
        if not isinstance(researched, list) or any(t not in rules.technologies for t in researched):
            raise ValueError("researched contains an unknown technology")
        if len(set(researched)) != len(researched):
            raise ValueError("researched contains duplicates")
        for t in researched:
            if not set(rules.technologies[t]["prerequisites"]) <= set(researched):
                raise ValueError(f"researched technology {t!r} is missing prerequisites")
        if not isinstance(d.setdefault("research_units_completed", {}), dict):
            raise ValueError("research_units_completed must be an object")
        for tech, value in d["research_units_completed"].items():
            if tech not in rules.technologies:
                raise ValueError(f"unknown research progress technology {tech!r}")
            integer(value, f"research_units_completed.{tech}")
            if value > rules.technologies[tech]["count"]:
                raise ValueError(f"research progress exceeds the unit count for {tech}")
        if not isinstance(d.setdefault("selected_recipes", {}), dict):
            raise ValueError("selected_recipes must be an object")
        for item, recipe in d["selected_recipes"].items():
            rules.recipe_for(item, {item: recipe})
        power = d.setdefault("power", {"available_kw": 0, "required": True})
        if not isinstance(power, dict):
            raise ValueError("power must be an object")
        number(power.get("available_kw"), "power.available_kw")
        if type(power.get("required", True)) is not bool:
            raise ValueError("power.required must be boolean")
        d.setdefault("require_lab", True)
        if type(d["require_lab"]) is not bool:
            raise ValueError("require_lab must be boolean")
        seen = set()
        if not isinstance(d.setdefault("machines", []), list):
            raise ValueError("machines must be a list")
        for machine in d["machines"]:
            if not isinstance(machine, dict):
                raise ValueError("each machine must be an object")
            mid = machine.get("id")
            if not isinstance(mid, str) or not mid or mid in seen:
                raise ValueError("machine ids must be unique nonempty strings")
            seen.add(mid)
            name = machine.get("prototype")
            if name not in rules.machines:
                raise ValueError(f"unsupported machine {name!r}")
            integer(machine.get("count", 1), f"{mid}.count", positive=True)
            for key in ("built", "connected", "powered", "output_open"):
                if type(machine.get(key)) is not bool:
                    raise ValueError(f"{mid}.{key} must be an explicit boolean observation")
            if type(machine.get("active", True)) is not bool:
                raise ValueError(f"{mid}.active must be boolean")
            position = machine.get("position")
            if position is not None:
                if not isinstance(position, dict) or set(position) != {"x", "y"}:
                    raise ValueError(f"{mid}.position must contain x and y")
                for value in position.values():
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                        raise ValueError(f"{mid}.position must be finite")
            recipe = machine.get("recipe")
            # Furnaces select recipes from their inputs and clear them when empty.
            # Keep the built station without inventing any production activity.
            if recipe is None and name not in ("lab", "stone-furnace"):
                raise ValueError(f"{mid} must specify recipe identity")
            if recipe is not None:
                if recipe not in rules.recipes:
                    raise ValueError(f"unsupported recipe {recipe!r}")
                if rules.recipes[recipe]["category"] not in rules.machines[name]["categories"]:
                    raise ValueError(f"{name} cannot craft {recipe}")
        for key in ("goal_window_seconds", "max_observation_age_seconds"):
            number(d.setdefault(key, 60 if key == "goal_window_seconds" else 10), key, positive=True)
        if not isinstance(d.setdefault("observations", []), list):
            raise ValueError("observations must be a list")
        for sample in d["observations"]:
            if not isinstance(sample, dict) or not isinstance(sample.get("produced"), dict):
                raise ValueError("each observation must be an object with produced counts")
            if not isinstance(sample.get("revision"), str):
                raise ValueError("observation requires a revision")
            if sample.get("source") not in ("automated", "handcrafted", "unknown"):
                raise ValueError("observation source must be automated, handcrafted or unknown")
            integer(sample.get("start_tick"), "observation.start_tick")
            integer(sample.get("end_tick"), "observation.end_tick")
            if sample["end_tick"] <= sample["start_tick"] or sample["end_tick"] > d["tick"]:
                raise ValueError("observation interval must be positive and end no later than snapshot tick")
            for item, value in sample.get("produced", {}).items():
                if item not in rules.items:
                    raise ValueError(f"unknown observed item {item!r}")
                integer(value, f"observation.produced.{item}")
        return cls(d)

    def to_dict(self):
        return deepcopy(self.document)

    def save(self, path):
        Path(path).write_text(json.dumps(self.document, indent=2) + "\n")

    @property
    def researched(self):
        return set(self.document["researched"])

    @property
    def machines(self):
        return self.document["machines"]

    @property
    def goals(self):
        return {k: v / 60 for k, v in self.document["goals_per_min"].items()}
