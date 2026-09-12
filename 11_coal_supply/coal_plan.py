"""Small authored mining module, translated from a fully surveyed coal rectangle."""
from collections import Counter
from dataclasses import dataclass
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "10_powered_lab"))
from power_plan import Placement


@dataclass(frozen=True)
class CoalLoop:
    placements: tuple[Placement, ...]
    anchor: tuple[int, int]

    @classmethod
    def from_survey(cls, capture):
        survey = capture["survey"]
        coal = [r for r in survey["resources"] if r["prototype"] == "coal"]
        if not coal or any(r["infinite"] or not r["minable"] or r["amount"] <= 0 for r in coal):
            raise ValueError("need finite minable coal in the survey")
        tiles = {(r["position"]["x"], r["position"]["y"]) for r in coal}
        left, right = min(x for x, _ in tiles), max(x for x, _ in tiles)
        top, bottom = min(y for _, y in tiles), max(y for _, y in tiles)
        if any(x % 1 != .5 or y % 1 != .5 for x, y in tiles):
            raise ValueError("coal tiles must use native half-tile centers")
        area = survey["area"]
        if left <= area[0][0]+.5 or top <= area[0][1]+.5 or right >= area[1][0]-.5 or bottom >= area[1][1]-.5:
            raise ValueError("coal patch touches survey boundary")
        if right-left < 3 or bottom-top < 5 or tiles != {
            (left+x, top+y) for x in range(round(right-left)+1) for y in range(round(bottom-top)+1)
        }:
            raise ValueError("need one complete coal rectangle at least 4 by 6 tiles")
        # Keep the loop on the west side of the resource row, away from the furnace.
        x, y = math.floor(left)+1, math.floor(top)+2
        entities = [Placement("coal.drill", "burner-mining-drill", x, y)]
        belts = [(-.5, -1.5, 4), (.5, -1.5, 4), (1.5, -1.5, 4), (2.5, -1.5, 8),
                 (2.5, -.5, 8), (2.5, .5, 8), (2.5, 1.5, 8)]
        entities.extend(Placement(f"coal.belt.{i}", "transport-belt", x+dx, y+dy, direction)
                        for i, (dx, dy, direction) in enumerate(belts))
        entities.extend((Placement("coal.refuel", "burner-inserter", x+1.5, y-.5, 4),
                         Placement("coal.export", "burner-inserter", x+2.5, y+2.5),
                         Placement("coal.chest", "wooden-chest", x+2.5, y+3.5)))
        return cls(tuple(entities), (x, y))

    def document(self):
        x, y = self.anchor
        return {"method": "coal drill with burner fuel return and surplus chest",
                "placements": [e.spec() for e in self.placements],
                "bill": dict(Counter(e.name for e in self.placements)),
                "staging": {"x": x-3, "y": y+2},
                "mining_area": [[x-1, y-1], [x+1, y+1]],
                "links": [["coal.drill", "coal.belt.0"], ["coal.belt.4", "coal.refuel"],
                          ["coal.refuel", "coal.drill"], ["coal.belt.6", "coal.export"],
                          ["coal.export", "coal.chest"]],
                "seed": {"coal.drill": 1, "coal.refuel": 1, "coal.export": 1},
                "output": {"address": "coal.chest", "item": "coal", "minimum_per_min": 10},
                "measurement": {"warmup_ticks": 3600, "window_ticks": 3600, "windows": 5}}
