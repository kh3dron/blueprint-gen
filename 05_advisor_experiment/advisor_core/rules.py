"""Explicit ruleset selection; no imports or caches from the existing tools."""
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path


DEFAULT_RULES = Path(__file__).resolve().parents[1] / "rules" / "nauvis.json"


@dataclass(frozen=True)
class Rules:
    document: dict
    digest: str

    @classmethod
    def load(cls, path=DEFAULT_RULES):
        document = json.loads(Path(path).read_text())
        if not isinstance(document, dict):
            raise ValueError("ruleset must be a JSON object")
        if document.get("schema_version") != 1:
            raise ValueError("unsupported ruleset schema_version")
        digest = sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return cls(document, digest)

    @property
    def id(self):
        return self.document["id"]

    @property
    def recipes(self):
        return self.document["recipes"]

    @property
    def machines(self):
        return self.document["machines"]

    @property
    def technologies(self):
        return self.document["technologies"]

    @property
    def items(self):
        return set(self.document["items"])

    def unlocked(self, recipe, researched):
        if recipe not in self.recipes:
            return False
        r = self.recipes[recipe]
        return r["enabled"] or any(t in researched for t in r["unlocked_by"])

    def recipe_for(self, item, selected=None):
        name = (selected or {}).get(item, self.document["default_recipes"].get(item))
        if name is None:
            return None
        if name not in self.recipes or self.recipes[name]["outputs"].get(item, 0) <= 0:
            raise ValueError(f"recipe {name!r} does not produce {item!r} in this ruleset")
        return name

    def research_path(self, name, researched):
        """Ordered prerequisites, refusing unknown technology rather than treating it as unlocked."""
        result, visiting = [], set()

        def visit(tech):
            if tech in researched or tech in result:
                return
            if tech not in self.technologies:
                raise ValueError(f"unknown technology {tech!r}")
            if tech in visiting:
                raise ValueError(f"cyclic technology prerequisites at {tech!r}")
            visiting.add(tech)
            for parent in self.technologies[tech]["prerequisites"]:
                visit(parent)
            visiting.remove(tech)
            result.append(tech)

        visit(name)
        return result

    def unlock_path(self, recipe, researched):
        if self.unlocked(recipe, researched):
            return []
        if recipe not in self.recipes:
            raise ValueError(f"unknown recipe {recipe!r}")
        paths = [self.research_path(t, researched) for t in self.recipes[recipe]["unlocked_by"]]
        if not paths:
            raise ValueError(f"recipe {recipe!r} is disabled and has no supported unlock")
        return min(paths, key=lambda p: (len(p), p))

    def machine_for(self, recipe):
        category = self.recipes[recipe]["category"]
        name = self.document["default_machines"].get(category)
        if name is None:
            raise ValueError(f"no supported machine for {category!r}")
        return name

    def craft_inputs(self, recipe, machine):
        """Process ingredients plus burner fuel; quantities per craft, not per second."""
        r, m = self.recipes[recipe], self.machines[machine]
        result = dict(r["inputs"])
        if m.get("fuel"):
            coal = m["fuel_kw"] * r["seconds"] / m["speed"] / self.document["fuel_kj"][m["fuel"]]
            result[m["fuel"]] = result.get(m["fuel"], 0) + coal
        return result
