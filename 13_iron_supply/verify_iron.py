"""Check connected, paid iron production and complete coal/ore item balances."""
from collections import Counter
import json
from pathlib import Path

from iron_plan import IronSupply
from verify_feed import indexed,loose_coal,check_connections as check_feed


def stock(sample,item):
    total=0
    for e in sample["entities"]:
        for key in ("input","output","contents","fuel"):
            total+=(e.get(key) or {}).get(item,0)
        total+=sum((lane or {}).get(item,0) for lane in e.get("lanes",[]))
        held=e.get("held")
        if held and held["name"]==item:total+=held["count"]
    return total


def coal_stock(sample):
    return loose_coal(sample["feed"])+stock(sample,"coal")


def all_burners(sample):
    rows=(sample["entities"]+sample["feed"]["entities"]+sample["feed"]["coal"]["entities"]
          +sample["feed"]["power_entities"])
    return {e["address"]:e for e in rows if "fuel" in e}


def check_sample(sample,design,feed_design,coal_design,ids=None):
    check_feed(sample["feed"],feed_design,coal_design)
    actual=indexed(sample["entities"]);specs=indexed(design["placements"])
    if actual.keys()!=specs.keys():raise ValueError("missing iron entity")
    found_ids={k:e["id"] for k,e in actual.items()}
    if ids is not None and found_ids!=ids:raise ValueError("iron entity replaced")
    for address,e in actual.items():
        if any(e[k]!=specs[address][k] for k in ("name","position","direction")):
            raise ValueError("iron entity drift")
        if e["name"] in {"burner-mining-drill","stone-furnace","inserter","burner-inserter"} and not e["active"]:
            raise ValueError("inactive iron entity")
        if e["name"] in {"inserter","small-electric-pole"} and e.get("network_id")!=design["power"]["network_id"]:
            raise ValueError("iron output power disconnected")
        if e["name"]=="stone-furnace" and e.get("recipe")!="iron-plate":
            # Native furnaces can clear their recipe between deliveries. Accept
            # only an empty, idle crafter; the window's native products, ore use
            # and plate stocks still have to balance independently below.
            if not (e.get("recipe") is None and e["progress"]==0 and not e["input"] and not e["output"]):
                raise ValueError("wrong smelting recipe")
        if e["name"]=="burner-mining-drill" and e.get("mining_target") not in (None,"iron-ore"):
            raise ValueError("wrong mining resource")
    power=indexed(sample["feed"]["power_entities"])["power.pole"]
    if (power["id"],power["network_id"])!=(design["power"]["id"],design["power"]["network_id"]):
        raise ValueError("upstream power endpoint changed")
    belts={tuple(e["position"][k] for k in ("x","y")):e for e in actual.values() if e["name"]=="transport-belt"}
    for prefix in ("iron.trunk.","iron.branch.","iron.extension.belt."):
        path=[actual[p["address"]] for p in design["placements"] if p["address"].startswith(prefix)]
        for a,b in zip(path,path[1:]):
            if b["id"] not in a["outputs"]:raise ValueError("iron coal belt disconnected")
    def connection(address,pickup,drop):
        e=actual[address]
        if (e.get("pickup_target"),e.get("drop_target"))!=(pickup,drop):
            raise ValueError("iron inserter endpoints disconnected: "+address)
    chest=indexed(sample["feed"]["coal"]["entities"])["coal.chest"]
    if chest["id"]!=design["source"]["id"]:raise ValueError("iron coal source changed")
    connection("iron.extract",chest["id"],actual["iron.trunk.0"]["id"])
    if "iron.branch-tap" in actual:
        tap=actual["iron.branch-tap"]["position"]
        connection("iron.branch-tap",belts[(tap["x"],tap["y"]-1)]["id"],actual["iron.branch.0"]["id"])
    for tap,pickup,drop in design.get("fuel_taps",[]):
        connection(tap,actual[pickup]["id"],actual[drop]["id"])
    for i in range(len(design["mining_areas"])):
        stem=f"iron.line.{i}"
        furnace=actual[stem+".furnace"];drill=actual[stem+".drill"]
        if drill.get("drop_target")!=furnace["id"]:raise ValueError("drill does not feed its furnace")
        connection(stem+".output",furnace["id"],actual[stem+".chest"]["id"])
        for consumer in ("furnace","drill"):
            p=actual[stem+"."+consumer+"-fuel"]["position"]
            connection(stem+"."+consumer+"-fuel",belts[(p["x"]+1,p["y"])]["id"],actual[stem+"."+consumer]["id"])
    if set(sample["meters"])!=set(all_burners(sample)):raise ValueError("fuel meter coverage incomplete")
    if sample["deposit_remaining"]!=sum(d["amount"] for d in sample["deposits"]):
        raise ValueError("iron deposit total inconsistent")
    return found_ids


def verify_payment(final,opening,actions,reconciliation,events,ids,*,require_refusal=True):
    state=final["state"]
    for key in ("cursor_placements","player_build_events"):
        old=opening["state"][key]
        if state[key][:len(old)]!=old:raise ValueError("previous native construction history changed")
    placements=[p for p in state["cursor_placements"] if p["address"].startswith("iron.")]
    if len(placements)!=len(ids):raise ValueError("missing paid iron placements")
    for p in placements:
        expected=Counter(p["before"]);expected.subtract({p["name"]:1})
        matching=[e for e in state["player_build_events"] if e["id"]==p["id"]]
        if (+expected!=Counter(p["after"]) or p["id"]!=ids[p["address"]] or len(matching)!=1
                or any(matching[0][k]!=p[k] for k in ("tick","name","position","player_index"))):
            raise ValueError("iron placement lacks paid inventory or native build event")
    for key in ("inventory","cursor_placements","player_build_events"):
        if reconciliation["before"][key]!=reconciliation["after"][key]:raise ValueError("iron repeat deployment changed inventory")
    if reconciliation["drift_before"]!=reconciliation["drift_after"]:raise ValueError("iron refusal changed inventory")
    inventory=Counter(opening["state"]["inventory"]);gathered=Counter()
    recipes=final["capture"]["resolved_rules"]["recipes"]
    refusal_seen=False
    for action in actions:
        req,out=action["request"],action["outcome"]
        # Paused commands can share a tick across milestones. Revisions place
        # the ledger boundary after the already verified Logistics command.
        if req["revision"]<opening["state"]["revision"]:continue
        if out["status"]!="done":
            if req["id"]==reconciliation["refusal_id"] and "declarative entity drift" in out.get("error",""):
                refusal_seen=True;continue
            raise ValueError("unexpected failed iron action")
        op,args,value=req["op"],req["args"],out["value"]
        if op in ("mine","harvest_tree"):
            if value["gained"]<=0 or (op=="mine" and value["gained"]!=value["depleted"]):raise ValueError("unpaid mineral gathering")
            inventory[value["item"]]+=value["gained"];gathered[value["item"]]+=value["gained"]
        elif op in ("smelt","handcraft"):
            recipe=recipes[args["recipe"]]
            for p in recipe["inputs"]:inventory[p["name"]]-=p["amount"]*args["crafts"]
            for p in recipe["outputs"]:inventory[p["name"]]+=p["amount"]*args["crafts"]
            if op=="smelt":
                inventory["coal"]-=args["coal"]
                if value["station_id"]!=opening["state"]["built"][0]["id"]:raise ValueError("procurement furnace changed")
            else:
                matching=[e for e in events if out["started_tick"]<e["tick"]<=out["finished_tick"]]
                outputs=Counter()
                for e in matching:
                    if e["recipe"]!=args["recipe"] or e["player_index"]!=placements[0]["player_index"]:
                        raise ValueError("native crafting attribution changed")
                    outputs[e["item"]]+=e["count"]
                if len(matching)!=args["crafts"] or outputs!=Counter({p["name"]:p["amount"]*args["crafts"] for p in recipe["outputs"]}):
                    raise ValueError("missing native crafting outputs")
        elif op=="place_iron" and value["added"]:
            p=next(p for p in placements if p["address"]==args["spec"]["address"])
            if +inventory!=Counter(p["before"]):raise ValueError("iron procurement inventory changed")
            inventory[p["name"]]-=1
        elif op not in {"place_iron","route","approach","walk_to","preflight_power","begin_iron","begin_iron_update","wait_iron"}:
            raise ValueError("unsupported action in iron ledger: "+op)
        if any(v<0 for v in inventory.values()):raise ValueError("iron construction spent unavailable items")
    if require_refusal and not refusal_seen:raise ValueError("missing iron direction refusal")
    if +inventory!=Counter(state["inventory"]):raise ValueError("final iron inventory does not conserve construction")
    if any(t["count"]!=t["removed"] or t["count"]!=t["inserted"] for t in final["transfers"]):
        raise ValueError("transfer did not conserve items")
    initial_ids={p["id"] for p in opening["state"]["cursor_placements"] if p["address"].startswith("iron.")}
    return dict(gathered),sum(p["id"] not in initial_ids for p in placements)


def verify(final,opening,design,feed_design,coal_design,actions,windows,baseline,reconciliation,events,*,require_refusal=True,previous_design=None):
    if previous_design:
        expected=IronSupply.extend(opening["capture"],opening["state"],previous_design,
            lines=len(design["mining_areas"]),minimum_per_min=design["output"]["minimum_per_min"]).document()
    else:
        expected=IronSupply.from_observation(opening["capture"],opening["state"],lines=len(design["mining_areas"]),
            minimum_per_min=design["output"]["minimum_per_min"]).document()
    if expected!=design:
        raise ValueError("iron design differs from observed endpoints and ore")
    starts=[a for a in actions if a["request"]["op"] in {"begin_iron","begin_iron_update"}]
    if len(starts)!=1 or starts[0]["outcome"]["value"]!=baseline:
        raise ValueError("iron baseline differs from its command receipt")
    if not previous_design and (baseline["entities"] or starts[0]["request"]["op"]!="begin_iron"):
        raise ValueError("iron baseline does not establish an empty new module")
    retained={}
    if previous_design:
        if starts[0]["request"]["op"]!="begin_iron_update":raise ValueError("missing deployment update baseline")
        retained=check_sample(opening["state"]["iron"],previous_design,feed_design,coal_design)
        # The baseline adds deposit coverage, but the previous machines and their
        # identities must remain. Product/fuel counters may advance during procurement.
        baseline_entities=indexed(baseline["entities"])
        if {k:e["id"] for k,e in baseline_entities.items()}!=retained:raise ValueError("retained baseline entities changed")
        for p in previous_design["placements"]:
            if any(baseline_entities[p["address"]][k]!=p[k] for k in ("name","position","direction")):
                raise ValueError("retained baseline configuration changed")
    waits=[a for a in actions if a["request"]["op"]=="wait_iron"]
    warmup_count=design["measurement"]["warmup_ticks"]//3600
    if len(waits)!=warmup_count+5 or len(windows)!=5 or [a["outcome"]["value"] for a in waits[warmup_count:]]!=windows:
        raise ValueError("iron windows differ from action receipts")
    previous_warmup=None
    for action in waits[:warmup_count]:
        window=action["outcome"]["value"];before,after=window["before"],window["after"]
        if (after["tick"]-before["tick"]!=3600 or window["idle_ticks"]!=3600 or not window["player_idle"]
                or window["inventory_before"]!=window["inventory_after"] or window["position_before"]!=window["position_after"]
                or (action["outcome"]["started_tick"],action["outcome"]["finished_tick"])!=(before["tick"],after["tick"])
                or (previous_warmup is not None and before!=previous_warmup)):
            raise ValueError("iron startup window is incomplete or interrupted")
        previous_warmup=after
    if previous_warmup!=windows[0]["before"]:raise ValueError("iron measurement does not follow startup")
    state=final["state"];ids=None;previous=None;rates=[];mined=produced=collected=coal_burned=0
    for window,action in zip(windows,waits[warmup_count:]):
        before,after=window["before"],window["after"]
        ids=check_sample(before,design,feed_design,coal_design,ids)
        ids=check_sample(after,design,feed_design,coal_design,ids)
        if any(ids.get(k)!=v for k,v in retained.items()):raise ValueError("retained entity replaced during extension")
        if previous is not None and before!=previous:raise ValueError("iron windows are not contiguous")
        previous=after
        start,finish=before["tick"],after["tick"]
        if (finish-start!=3600 or window["idle_ticks"]!=3600 or
                (action["outcome"]["started_tick"],action["outcome"]["finished_tick"])!=(start,finish)):
            raise ValueError("iron window skipped game time")
        if (not window["player_idle"] or window["inventory_before"]!=window["inventory_after"] or
                window["position_before"]!=window["position_after"] or before["player_inventory"]!=after["player_inventory"]):
            raise ValueError("player intervened during iron measurement")
        if any(start<e["tick"]<=finish for e in final["transfers"]+state["player_build_events"]+state["tree_events"]+events):
            raise ValueError("native player action during iron measurement")
        ore=after["ore_produced"]-before["ore_produced"]
        consumed=after["ore_consumed"]-before["ore_consumed"]
        plates=after["plates_produced"]-before["plates_produced"]
        if ore<=0 or ore!=before["deposit_remaining"]-after["deposit_remaining"]:
            raise ValueError("iron mining does not match deposit depletion")
        if ore!=stock(after,"iron-ore")-stock(before,"iron-ore")+consumed:
            raise ValueError("mined ore does not balance furnace inputs and consumption")
        a,b=indexed(before["entities"]),indexed(after["entities"])
        furnaces=[p["address"] for p in design["placements"] if p["name"]=="stone-furnace"]
        if plates!=sum(b[k]["products"]-a[k]["products"] for k in furnaces) or plates!=stock(after,"iron-plate")-stock(before,"iron-plate"):
            raise ValueError("plate output does not balance native furnace production")
        progress_delta=sum(int(b[k]["progress"]>0)-int(a[k]["progress"]>0) for k in furnaces)
        if consumed!=plates+progress_delta:raise ValueError("smelting input does not balance output and work in progress")
        delivered=sum((b[k]["contents"] or {}).get("iron-plate",0)-(a[k]["contents"] or {}).get("iron-plate",0) for k in design["output"]["addresses"])
        if delivered<design["output"]["minimum_per_min"]:raise ValueError("iron collection rate below contract")
        if after["inserter_consumed_j"]<=before["inserter_consumed_j"]:raise ValueError("powered plate collection had no electric consumption")
        rates.append(delivered);mined+=ore;produced+=plates;collected+=delivered
        old,new=all_burners(before),all_burners(after);burned=0
        for address,meter in after["meters"].items():
            earlier=before["meters"][address]
            arriving=meter["delivered"]-earlier["delivered"];starts=meter["started"]-earlier["started"]
            delta=(new[address]["fuel"] or {}).get("coal",0)-(old[address]["fuel"] or {}).get("coal",0)
            if arriving<0 or starts<0 or arriving!=delta+starts:raise ValueError("burner fuel delivery does not conserve coal")
            burned+=starts
        coal=after["feed"]["coal"]["produced"]-before["feed"]["coal"]["produced"]
        if coal!=before["feed"]["coal"]["deposit_remaining"]-after["feed"]["coal"]["deposit_remaining"]:
            raise ValueError("coal depletion does not match extraction")
        if coal_stock(after)-coal_stock(before)!=coal-burned:raise ValueError("connected coal stocks do not balance extraction and all burners")
        coal_burned+=burned
    first,last=windows[0]["before"],windows[-1]["after"]
    gain=coal_stock(last)-coal_stock(first)
    if gain<0:raise ValueError("connected fuel buffers drained")
    for i in range(len(design["mining_areas"])):
        for machine in ("drill","furnace"):
            address=f"iron.line.{i}.{machine}"
            if last["meters"][address]["delivered"]<=first["meters"][address]["delivered"]:
                raise ValueError("no new coal reached an iron consumer")
    if any(t["tick"]>=baseline["tick"] for t in final["transfers"]):raise ValueError("manual transfer after iron baseline")
    check_sample(state["iron"],design,feed_design,coal_design,ids)
    gathered,builds=verify_payment(final,opening,actions,reconciliation,events,ids,require_refusal=require_refusal)
    return {"automatic_iron_supply_observed":True,"factorio_version":state["active_mods"]["base"],
        "idle_seconds":300,"plates_per_minute":rates,"iron_ore_mined":mined,"plates_produced":produced,
        "plates_collected":collected,"coal_burned":coal_burned,"coal_buffer_gain":gain,
        "native_cursor_builds_added":builds,"additional_gathered":gathered,
        "output_service":{"item":"iron-plate","minimum_per_minute":min(rates),
            "entities":[ids[k] for k in design["output"]["addresses"]],"measurement_ticks":[first["tick"],last["tick"]]},
        "goal_complete":False}


def verify_directory(root):
    root=Path(root)
    def read(name):return json.loads((root/name).read_text())
    events=root/"player-crafts.jsonl"
    if not events.exists():events=root/"user-data/script-output/player-crafts.jsonl"
    return verify(read("iron-final-observation.json"),read("iron-opening-observation.json"),read("iron-design.json"),
        read("feed-design.json"),read("coal-design.json"),read("actions.json"),read("iron-windows.json"),
        read("iron-baseline.json"),read("iron-reconciliation.json"),
        [json.loads(s) for s in events.read_text().splitlines()])
