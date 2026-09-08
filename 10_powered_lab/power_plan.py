"""Bounded declarative power island anchored to an observed rectangular shoreline."""
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class Placement:
    address: str
    name: str
    x: float
    y: float
    direction: int = 0

    def spec(self):
        return {"address": self.address, "name": self.name, "position": {"x": self.x, "y": self.y}, "direction": self.direction}


@dataclass(frozen=True)
class PowerIsland:
    placements: tuple[Placement, ...]
    staging: tuple[float, float]

    @classmethod
    def from_survey(cls, capture):
        water = {(t["x"], t["y"]) for t in capture["survey"]["water_tiles"]}
        if not water:
            raise ValueError("the observed area has no water")
        xmin, xmax = min(x for x, _ in water), max(x for x, _ in water)
        ymin, ymax = min(y for _, y in water), max(y for _, y in water)
        area = capture["survey"].get("area")
        if area and (xmin <= area[0][0] or ymin <= area[0][1] or xmax+1 >= area[1][0] or ymax+1 >= area[1][1]):
            raise ValueError("pond touches the survey boundary; observe its full shoreline")
        if xmax-xmin < 3 or ymax-ymin < 5 or water != {(x,y) for x in range(xmin,xmax+1) for y in range(ymin,ymax+1)}:
            raise ValueError("power island requires one fully observed rectangular pond at least 4 by 6 tiles")
        x, y = xmax+1.5, ymin+4.5
        placements = (
            Placement("power.pump", "offshore-pump", x, y, 12),
            Placement("power.water-pipe", "pipe", x+1, y),
            Placement("power.boiler", "boiler", x+3, y-.5),
            Placement("power.engine", "steam-engine", x+3, y-4),
            Placement("power.pole", "small-electric-pole", x+6, y-2),
            Placement("power.lab", "lab", x+8, y-4),
        )
        return cls(placements, (x+5.5, y+2.5))

    def document(self):
        return {"method": "east-shore finite steam-powered lab", "placements": [p.spec() for p in self.placements],
                "staging": {"x": self.staging[0], "y": self.staging[1]},
                "bill": dict(Counter(p.name for p in self.placements)),
                "connections": [
                    {"from": "power.pump", "to": "power.water-pipe", "kind": "fluid", "fluid": "water"},
                    {"from": "power.water-pipe", "to": "power.boiler", "kind": "fluid", "fluid": "water"},
                    {"from": "power.boiler", "to": "power.engine", "kind": "fluid", "fluid": "steam"},
                    {"from": "power.engine", "to": "power.lab", "via": "power.pole", "kind": "electric"}],
                "completion": "observe automation researched by this lab from ten paid science packs",
                "note": "Design connections require engine validation; no advertised continuous power or science rate."}
