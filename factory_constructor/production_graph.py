"""Backward production dependencies with shared demand and explicit reused services."""
from collections import defaultdict
import math


def production_graph(goal, rules, researched, *, available=None, selected=None, machine_metadata=None):
    available=dict(available or {})
    demands=defaultdict(float)
    nodes={}

    def require(item, rate, path=()):
        if item in path:
            raise ValueError("production cycle needs a dedicated construction method: "+item)
        demands[item]+=rate
        supplied=min(available.get(item,0),rate)
        available[item]=available.get(item,0)-supplied
        node=nodes.setdefault(item,{"item":item,"required_per_minute":0,"reused_per_minute":0,
                                    "crafts_per_minute":0,"dependencies":{}})
        node["required_per_minute"]+=rate
        node["reused_per_minute"]+=supplied
        rate-=supplied
        if rate<=1e-9:return
        recipe=rules.recipe_for(item,selected)
        if recipe is None:
            node["method"]="extraction"
            return
        if not rules.unlocked(recipe,researched):
            raise ValueError("production requires research: "+", ".join(rules.unlock_path(recipe,researched)))
        data=rules.recipes[recipe]
        if len(data["outputs"])!=1:
            raise ValueError("coproduct construction needs a dedicated production method")
        machine=rules.machine_for(recipe)
        activity=rate/data["outputs"][item]
        node.update(method="recipe",recipe=recipe,machine=machine)
        node["crafts_per_minute"]+=activity
        for ingredient,amount in rules.craft_inputs(recipe,machine).items():
            demand=activity*amount
            node["dependencies"][ingredient]=node["dependencies"].get(ingredient,0)+demand
            require(ingredient,demand,path+(item,))

    require(goal.item,goal.per_minute)
    active_kw=idle_kw=0
    for node in nodes.values():
        if node.get("method")=="recipe":
            machine={**rules.machines[node["machine"]], **(machine_metadata or {}).get(node["machine"], {})}
            utilization=node["crafts_per_minute"]*rules.recipes[node["recipe"]]["seconds"]/(60*machine["speed"])
            node["count"]=math.ceil(utilization-1e-9)
            node["active_electric_kw"]=utilization*machine["electric_kw"]
            node["idle_electric_kw"]=node["count"]*machine.get("idle_kw",0)
            active_kw+=node["active_electric_kw"];idle_kw+=node["idle_electric_kw"]
        elif node["reused_per_minute"]>=node["required_per_minute"]-1e-9:
            node.update(method="reuse",count=0)
    return {"nodes":nodes,"active_electric_kw":active_kw,"idle_electric_kw":idle_kw,
            "electricity_note":"recipe load only; transport, extraction and installed capacity are checked by layout"}
