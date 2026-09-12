"""One or two directly fed furnaces at the north edge of an observed iron rectangle."""
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "12_boiler_feed"))
from feed_plan import Placement


@dataclass(frozen=True)
class IronSupply:
    data: dict

    @classmethod
    def from_observation(cls, capture, state, *, lines=2, minimum_per_min=20):
        if type(lines) is not int or lines not in (1, 2):
            raise ValueError("this north-edge method supports one or two lines")
        if isinstance(minimum_per_min, bool) or not math.isfinite(minimum_per_min) or minimum_per_min <= 0:
            raise ValueError("need a positive finite output target")
        survey=capture["survey"]
        ores=[r for r in survey["resources"] if r["prototype"]=="iron-ore"]
        if not ores or any(r["infinite"] or not r["minable"] or r["amount"]<=0 for r in ores):
            raise ValueError("need finite minable iron ore")
        tiles={(r["position"]["x"],r["position"]["y"]) for r in ores}
        left,right=min(x for x,y in tiles),max(x for x,y in tiles)
        top,bottom=min(y for x,y in tiles),max(y for x,y in tiles)
        area=survey["area"]
        if (any(x%1!=.5 or y%1!=.5 for x,y in tiles) or left<=area[0][0]+.5
                or top<=area[0][1]+.5 or right>=area[1][0]-.5 or bottom>=area[1][1]-.5
                or not 7<=right-left<=13 or bottom-top<2
                or tiles!={(left+x,top+y) for x in range(round(right-left)+1) for y in range(round(bottom-top)+1)}):
            raise ValueError("need a fully observed iron rectangle 8–14 tiles wide")
        chest=next(e for e in state["coal"]["entities"] if e["address"]=="coal.chest")
        pole=next(e for e in state["power_entities"] if e["address"]=="power.pole")
        cx,cy=chest["position"]["x"],chest["position"]["y"]
        xs=[math.floor(left)+1,math.floor(right)][:lines]
        dy=math.floor(top)+1;fy=dy-2;trunk_y=fy-3.5
        if chest["name"]!="wooden-chest" or not cx+2<xs[0]-3 or not trunk_y<cy<trunk_y+30 or xs[-1]-cx>60:
            raise ValueError("need the coal chest west of the iron patch within the bounded route")
        placements=[];links=[];areas=[]
        # Native pole autoconnection along a clear northern corridor.
        px,py=pole["position"]["x"],pole["position"]["y"]
        corridor=trunk_y-2
        targets=[(px,corridor),(xs[0]-2.5,corridor)]+[(x-2.5,fy-2.5) for x in xs]
        for tx,ty in targets:
            while (px,py)!=(tx,ty):
                px+=max(-7,min(7,tx-px));py+=max(-7,min(7,ty-py))
                placements.append(Placement(f"iron.pole.{sum(p.name=='small-electric-pole' for p in placements)}",
                                            "small-electric-pole",px,py))
        outputs=[]
        for i,x in enumerate(xs):
            stem=f"iron.line.{i}"
            placements.extend((Placement(stem+".chest","wooden-chest",x-2.5,fy-.5),
                Placement(stem+".furnace","stone-furnace",x,fy),
                Placement(stem+".drill","burner-mining-drill",x,dy),
                Placement(stem+".output","inserter",x-1.5,fy-.5,4),
                Placement(stem+".furnace-fuel","burner-inserter",x+1.5,fy-.5,4),
                Placement(stem+".drill-fuel","burner-inserter",x+1.5,dy-.5,4)))
            areas.append([[x-1,dy-1],[x+1,dy+1]])
            outputs.append(stem+".chest")
            links.extend(((stem+".drill",stem+".furnace"),(stem+".furnace",stem+".output"),
                          (stem+".output",stem+".chest")))
        points=[(cx+2,cy-j) for j in range(round(cy-trunk_y))]
        points += [(cx+2+j,trunk_y) for j in range(round(xs[-1]+2.5-cx-2))]
        points += [(xs[-1]+2.5,trunk_y+j) for j in range(round(dy-.5-trunk_y)+1)]
        for i,(x,y) in enumerate(points):
            nx,ny=points[i+1] if i+1<len(points) else (x,y+1)
            direction=4 if nx>x else 8 if ny>y else 0
            placements.append(Placement(f"iron.trunk.{i}","transport-belt",x,y,direction))
        bx=xs[0]+2.5
        branch=[(bx,trunk_y+2+j) for j in range(round(dy-.5-trunk_y-2)+1)] if lines>1 else []
        placements.extend(Placement(f"iron.branch.{i}","transport-belt",x,y,8) for i,(x,y) in enumerate(branch))
        if branch:placements.append(Placement("iron.branch-tap","burner-inserter",bx,trunk_y+1))
        placements.append(Placement("iron.extract","burner-inserter",cx+1,cy,12))
        specs=[p.spec() for p in placements]
        # Catch overlap among future builds before paying for the plan.
        occupied=set()
        for p in placements:
            size=2 if p.name in {"stone-furnace","burner-mining-drill"} else 1
            cells={(math.floor(p.x-size/2)+x,math.floor(p.y-size/2)+y) for x in range(size) for y in range(size)}
            if occupied & cells: raise ValueError("planned iron entities overlap")
            occupied|=cells
        return cls({"method":("two" if lines==2 else "one")+" coal-fed burner drills directly feeding furnaces",
            "placements":specs,"bill":dict(Counter(p.name for p in placements)),"mining_areas":areas,
            "source":{"address":"coal.chest","id":chest["id"],"item":"coal"},
            "power":{"address":"power.pole","id":pole["id"],"network_id":pole["network_id"]},
            "links":[list(x) for x in links],"output":{"addresses":outputs,"item":"iron-plate","minimum_per_min":minimum_per_min},
            "measurement":{"warmup_ticks":7200,"window_ticks":3600,"windows":5}})

    def document(self):
        return self.data

    @classmethod
    def extend(cls, capture, state, previous, *, lines, minimum_per_min):
        """Keep installed geometry, appending a side-fed second line when needed."""
        count=len(previous["mining_areas"])
        if lines<count or not count<=lines<=2:
            raise ValueError("extension cannot remove lines or exceed this method's capacity")
        result=deepcopy(previous)
        result["output"]["minimum_per_min"]=minimum_per_min
        if lines==count:
            return cls(result)
        # Use the survey to locate the next production cell and pole continuation.
        expanded=cls.from_observation(capture,state,lines=2,minimum_per_min=minimum_per_min).document()
        standard=cls.from_observation(capture,state,lines=1,
            minimum_per_min=previous["output"]["minimum_per_min"]).document()
        if previous!=standard:
            raise ValueError("extension needs a recognized one-line baseline")
        old={p["address"]:p for p in previous["placements"]}
        additions=[p for p in expanded["placements"] if p["address"].startswith("iron.line.1.")
                   or (p["name"]=="small-electric-pole" and p["address"] not in old)]
        first=old["iron.line.0.furnace"]["position"]
        second=next(p for p in additions if p["address"]=="iron.line.1.drill")["position"]
        bx,by=first["x"]+2.5,first["y"]-1.5
        endx,endy=second["x"]+2.5,second["y"]-.5
        points=[(bx+2+i,by) for i in range(round(endx-bx-2)+1)]
        points += [(endx,by+i) for i in range(1,round(endy-by)+1)]
        for i,(x,y) in enumerate(points):
            direction=4 if i+1<len(points) and points[i+1][0]>x else 8
            additions.append(Placement(f"iron.extension.belt.{i}","transport-belt",x,y,direction).spec())
        additions.append(Placement("iron.extension.tap","burner-inserter",bx+1,by,12).spec())
        pickup=next(p["address"] for p in previous["placements"]
                    if p["name"]=="transport-belt" and p["position"]=={"x":bx,"y":by})
        result.update(method="additive side-fed second iron line",
            placements=result["placements"]+additions,
            mining_areas=expanded["mining_areas"],links=expanded["links"],
            fuel_taps=[["iron.extension.tap",pickup,"iron.extension.belt.0"]])
        result["output"]=expanded["output"]
        result["bill"]=dict(Counter(p["name"] for p in result["placements"]))
        return cls(result)
