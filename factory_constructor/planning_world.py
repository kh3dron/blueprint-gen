"""Place cumulative machine sites on the survey before transport is routed."""
from collections import Counter
from copy import deepcopy
import math

from .legacy import ROOT  # Initialize the existing method import boundary.
from advisor_core.survey import survey_data
from power_plan import PowerIsland
from .science_layout import _cells


class PlanningWorld:
    def __init__(self, observation):
        self.survey = deepcopy(survey_data(observation["capture"]))
        if self.survey.get("ungenerated_chunks"):
            raise ValueError("planning requires a fully generated survey")
        self.entities = []
        self.water = {(t["x"], t["y"]) for t in self.survey["water_tiles"]}
        self.occupied = set(self.water)
        for entity in self.survey["obstacles"]:
            if entity["entity_type"] != "character":
                self.occupied.update(self.cells(entity))

    @staticmethod
    def cells(entity):
        box = entity.get("bounding_box")
        if box:
            return {(x, y) for x in range(math.floor(box["left_top"]["x"]), math.ceil(box["right_bottom"]["x"]))
                    for y in range(math.floor(box["left_top"]["y"]), math.ceil(box["right_bottom"]["y"]))}
        return _cells(entity)

    def clear(self, entity):
        (xmin, ymin), (xmax, ymax) = self.survey["area"]
        cells = self.cells(entity)
        return not (cells & self.occupied) and all(
            xmin <= x and ymin <= y and x + 1 <= xmax and y + 1 <= ymax for x, y in cells)

    def add(self, spec):
        if any(e["address"] == spec["address"] for e in self.entities):
            raise ValueError("duplicate planning address: " + spec["address"])
        if not self.clear(spec):
            raise ValueError("site blocked, wet, or outside survey: " + spec["address"])
        self.entities.append(deepcopy(spec))
        self.occupied.update(self.cells(spec))

    def resource(self, item):
        tiles = [r for r in self.survey["resources"] if r["prototype"] == item]
        if not tiles or any(not r["minable"] or r["infinite"] or r["amount"] <= 0 for r in tiles):
            raise ValueError("need surveyed finite minable resource: " + item)
        if any(r["mining_time"] != 1 or len(r["products"]) != 1 or
               r["products"][0].get("amount") != 1 or r["products"][0]["name"] != item for r in tiles):
            raise ValueError("unsupported mining mechanics: " + item)
        return tiles

    def count(self, service, name):
        return sum(e.get("service") == service and e["name"] == name for e in self.entities)

    def site(self, service, name, index, anchor, recipe=None):
        # Leave two clear tiles around each process site for future ports.
        (xmin, ymin), (xmax, ymax) = self.survey["area"]
        half = 0 if name == "stone-furnace" else .5
        points = [(x + half, y + half)
                  for x in range(math.ceil(xmin) + 3, math.floor(xmax) - 3)
                  for y in range(math.ceil(ymin) + 3, math.floor(ymax) - 3)]
        points.sort(key=lambda p: (math.dist(p, anchor), p))
        for x, y in points:
            spec = {"address": f"{service}.{name}.{index}", "service": service,
                    "name": name, "position": {"x": x, "y": y}, "direction": 0}
            if recipe:
                spec["recipe"] = recipe
            cells = self.cells(spec)
            margin = {(cx + dx, cy + dy) for cx, cy in cells
                      for dx in range(-2, 3) for dy in range(-2, 3)}
            ore = {(math.floor(r["position"]["x"]), math.floor(r["position"]["y"]))
                   for r in self.survey["resources"]}
            if self.clear(spec) and not margin & self.occupied and not cells & ore:
                self.add(spec)
                return
        raise ValueError("no surveyed site for " + service)

    def miners(self, item, count):
        tiles = {(math.floor(r["position"]["x"]), math.floor(r["position"]["y"]))
                 for r in self.resource(item)}
        left, top = min(x for x, y in tiles), min(y for x, y in tiles)
        candidates = sorted({(x + 1, y + 1) for x, y in tiles if (x-left)%2 == 0 and (y-top)%5 == 0}, key=lambda p: (p[1], p[0]))
        while self.count(item, "burner-mining-drill") < count:
            index = self.count(item, "burner-mining-drill")
            for x, y in candidates:
                spec = {"address": f"{item}.drill.{index}", "name": "burner-mining-drill",
                        "service": item, "position": {"x": x, "y": y}, "direction": 0}
                cells = self.cells(spec)
                # A free row above each north-facing drill reserves its output.
                output = {(x - 1, y - 2), (x, y - 2), (x - 1, y + 1), (x - 1, y + 2)}
                if cells <= tiles and self.clear(spec) and not output & self.occupied:
                    self.add(spec)
                    # Reserve the output corridor, but never export it as a built entity.
                    self.occupied.update(output)
                    break
            else:
                raise ValueError("insufficient dry mining sites for " + item)

    def processes(self, graph, items=None):
        order = ["iron-plate", "copper-plate", "iron-gear-wheel", "automation-science-pack",
                 "copper-cable", "electronic-circuit", "transport-belt", "inserter", "logistic-science-pack"]
        for rank, item in enumerate(order):
            node = graph["nodes"].get(item)
            if not node or node.get("method") != "recipe" or (items is not None and item not in items):
                continue
            name = node["machine"]
            while self.count(item, name) < node["count"]:
                index = self.count(item, name)
                anchor = (-9 + (rank % 5) * 14, -5 + (rank // 5) * 16 + index * 6)
                self.site(item, name, index, anchor, recipe=node["recipe"])

    def power(self, engines=1):
        if not any(e["name"] == "steam-engine" for e in self.entities):
            for spec in PowerIsland.from_survey({"survey": self.survey}).document()["placements"]:
                self.add(dict(spec, service="power" if spec["name"] != "lab" else "research"))
        existing = [e for e in self.entities if e["name"] == "steam-engine"]
        if engines > 2:
            raise ValueError("planning power site supports at most two engines and one boiler")
        if len(existing) < engines:
            first = existing[0]
            self.add(dict(first, address="power.engine.1", position={
                "x": first["position"]["x"], "y": first["position"]["y"] - 5}))

    def bill_since(self, before):
        return dict(Counter(e["name"] for e in self.entities[before:]))
