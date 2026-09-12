"""Bounded coal-chest to boiler connection, derived from observed endpoints."""
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "11_coal_supply"))
from coal_plan import Placement


@dataclass(frozen=True)
class BoilerFeed:
    placements: tuple[Placement, ...]
    source: str
    consumer: str

    @classmethod
    def from_state(cls, state):
        chest = next(e for e in state["coal"]["entities"] if e["address"] == "coal.chest")
        boiler = next(e for e in state["power_entities"] if e["address"] == "power.boiler")
        cx, cy = chest["position"]["x"], chest["position"]["y"]
        bx, by = boiler["position"]["x"], boiler["position"]["y"]
        end_y = by + 2.5
        route_y = max(cy + 2, end_y + 1)
        if (chest["name"] != "wooden-chest" or boiler["name"] != "boiler"
                or boiler["direction"] != 0 or bx >= cx - 3
                or any(v % 1 != .5 for v in (cx, cy, bx, end_y))
                or cx-bx > 60 or route_y-end_y > 40 or route_y-cy > 40):
            raise ValueError("need a north-facing boiler west of the coal chest within the bounded route")
        points = [(cx, cy+2+i) for i in range(round(route_y-cy-2))]
        points += [(cx-i, route_y) for i in range(round(cx-bx))]
        points += [(bx, route_y-i) for i in range(round(route_y-end_y)+1)]
        placements = [Placement("feed.extract", "burner-inserter", cx, cy+1)]
        for i, (x,y) in enumerate(points):
            nx,ny = points[i+1] if i+1 < len(points) else (x,y-1)
            direction = 12 if nx < x else 8 if ny > y else 0
            placements.append(Placement(f"feed.belt.{i}", "transport-belt", x,y,direction))
        placements.append(Placement("feed.insert", "burner-inserter", bx,end_y-1,8))
        return cls(tuple(placements), chest["id"], boiler["id"])

    def document(self):
        return {"method": "south-side belt from coal chest to boiler",
                "source": {"address": "coal.chest", "id": self.source, "item": "coal"},
                "consumer": {"address": "power.boiler", "id": self.consumer, "item": "coal"},
                "placements": [p.spec() for p in self.placements],
                "bill": dict(Counter(p.name for p in self.placements)),
                "measurement": {"technology": "logistics", "window_ticks": 3600, "windows": 5}}
