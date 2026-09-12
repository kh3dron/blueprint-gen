#!/usr/bin/env python3
"""Build and measure automatic iron supply from the verified coal-fed boiler stage."""
import argparse
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import inspect
import json
import math
from pathlib import Path
import shutil
import tempfile
import time

from iron_plan import IronSupply
from iron_checkpoint import write_iron_checkpoint,validate_iron_checkpoint
from run_feed import feed_overlay,execute_feed,preparation_contract as feed_contract
from run_feed import CoalSession,CoalDriver,GraphicalClient,configure_recording,restore_driver,validate_bundle,SOURCE,bill,save
from run_report import report as base_report

HERE=Path(__file__).resolve().parent


def prepare_iron(driver):
    driver.milestone="automatic-iron-supply"
    snapshot,rules,capture=driver.observe()
    save(driver.root/"iron-opening-observation.json",driver.observations[-1])
    design=IronSupply.from_observation(capture,driver.current).document()
    driver.action("preflight_power",{"specs":design["placements"]},"Check the iron module and coal/power corridors")
    materials=bill(snapshot,rules,design["bill"])
    save(driver.root/"iron-design.json",design);save(driver.root/"iron-materials.json",materials)
    print("Procure the iron module from finite minerals and harvested wood.",flush=True)
    driver.execute_bill({"construction":materials})
    driver.observe()
    save(driver.root/"iron-ready-observation.json",driver.observations[-1])


def contract():
    return {"method":"iron-ready-v1","prepare_sha256":sha256(inspect.getsource(prepare_iron).encode()).hexdigest()}


@contextmanager
def iron_overlay():
    with feed_overlay() as base, tempfile.TemporaryDirectory(prefix="blueprint-iron-overlay-") as temp:
        overlay=Path(temp)
        for path in base.glob("*.lua"):
            name={"extension.lua":"feed.lua","adapter.lua":"feed_adapter.lua","control.lua":"feed_control.lua"}.get(path.name,path.name)
            shutil.copy2(path,overlay/name)
        for path in (HERE/"integration").glob("*.lua"):
            shutil.copy2(path,overlay/path.name)
        yield overlay


def wait_iron(driver,label,speed):
    previous=driver.session.client.call({"op":"status"})["speed"]
    driver.session.client.call({"op":"speed","speed":speed})
    try:
        return driver.action("wait_iron",{"ticks":3600},label)
    finally:
        driver.session.client.call({"op":"speed","speed":previous})


def execute_iron(driver,wait_speed):
    root=driver.root
    prepared=json.loads((root/"iron-design.json").read_text())
    ready=json.loads((root/"iron-ready-observation.json").read_text())
    design=IronSupply.from_observation(ready["capture"],driver.current).document()
    if design["bill"]!=prepared["bill"]:raise ValueError("iron bill changed; prepare another checkpoint")
    save(root/"iron-design.json",design)
    driver.action("preflight_power",{"specs":design["placements"]},"Recheck all iron construction sites")
    baseline=driver.action("begin_iron",{"mining_areas":design["mining_areas"]},"Record iron deposits and empty new-module buffers")
    save(root/"iron-baseline.json",baseline["outcome"]["value"])
    for spec in design["placements"]:
        p=spec["position"]
        current=driver.session.client.call({"op":"status"})
        position=current["position"]
        reach=min(current["build_distance"],current["reach_distance"])-1.25
        half=1 if spec["name"] in {"stone-furnace","burner-mining-drill"} else .5
        inside=abs(position["x"]-p["x"])<half+.4 and abs(position["y"]-p["y"])<half+.4
        if inside or math.hypot(position["x"]-p["x"],position["y"]-p["y"])>reach:
            command='/silent-command rcon.print(helpers.table_to_json(remote.call("iron-supply-dev","approach",'+str(p["x"])+','+str(p["y"])+')))'
            approach=json.loads(driver.session.client.execute(command))
            driver.action("walk_to",{"position":approach},"Walk within reach of "+spec["address"])
        driver.action("place_iron",{"spec":spec},"Build "+spec["address"]+" with the player cursor")
    before=driver.session.client.call({"op":"status"})
    for spec in design["placements"]:
        result=driver.action("place_iron",{"spec":spec},"Reconcile "+spec["address"])
        if result["outcome"]["value"]["added"]:raise ValueError("iron repeat placement duplicated an entity")
    after=driver.session.client.call({"op":"status"})
    keys=("inventory","cursor_placements","player_build_events")
    if any(before[k]!=after[k] for k in keys):raise ValueError("iron reconciliation changed paid construction")
    changed=deepcopy(next(s for s in design["placements"] if s["name"]=="burner-mining-drill"))
    changed["direction"]=4
    try:
        driver.action("place_iron",{"spec":changed},"Refuse direction drift in the existing iron drill")
    except RuntimeError as error:
        if "declarative entity drift" not in str(error):raise
    else:raise ValueError("iron direction drift was accepted")
    refused=driver.session.client.call({"op":"status"})
    save(root/"iron-reconciliation.json",{"before":before,"after":after,"refusal_id":driver.actions[-1]["request"]["id"],
        "drift_before":{k:after[k] for k in keys},"drift_after":{k:refused[k] for k in keys}})
    print("Warm up automatic ore, fuel and plate delivery for two minutes.",flush=True)
    warmup=[]
    for i in range(design["measurement"]["warmup_ticks"]//3600):
        result=wait_iron(driver,f"Warm up the coal-fed iron module: idle minute {i+1}/2",wait_speed)
        warmup.append(result["outcome"]["value"])
        save(root/"iron-warmup.json",warmup)
    windows=[]
    for i in range(5):
        result=wait_iron(driver,f"Measure automatic iron plates: idle minute {i+1}/5",wait_speed)
        windows.append(result["outcome"]["value"]);save(root/"iron-windows.json",windows)
    driver.observe();save(root/"iron-final-observation.json",driver.observations[-1])
    from verify_iron import verify_directory
    verification=verify_directory(root);save(root/"iron-verification.json",verification)
    driver.session.client.call({"op":"save","name":"automatic-iron"})
    print(json.dumps({"iron_verified":True,"plates_per_min":verification["plates_per_minute"],
        "coal_buffer_gain":verification["coal_buffer_gain"]}),flush=True)


def summarize(root,status,started,start_tick,start_action,error=None):
    result=base_report(root,status=status,wall_seconds=time.perf_counter()-started,start_tick=start_tick,start_action=start_action,error=error)
    result.pop("checks",None)
    latest=Path(root)/"latest-observation.json"
    if latest.exists():
        state=json.loads(latest.read_text())["state"]
        result["tick"]=state["tick"];result["simulated_seconds"]=(state["tick"]-start_tick)/60 if start_tick is not None else None
        if error:result["last_observed"]={k:state.get(k) for k in ("tick","revision","position","inventory","researched")}
    checked=Path(root)/"iron-verification.json"
    if status=="passed" and checked.exists():result["checks"]=json.loads(checked.read_text())
    save(Path(root)/"run-summary.json",result)
    print(json.dumps(result),flush=True)


def run(binary,out,*,from_feed=None,resume=None,prepare_only=False,wait_speed=40):
    started=time.perf_counter();start_tick=None;start_action=0
    config=json.loads((SOURCE/"config.json").read_text())
    bundle=resume or from_feed
    if resume:validate_iron_checkpoint(bundle,config=config,contract=contract())
    else:validate_bundle(bundle,config=config,contract=feed_contract())
    session=graphics=None
    try:
        with iron_overlay() as overlay:
            session=CoalSession(binary,out,config,scenario_overlay=overlay,checkpoint=bundle)
        session.start();configure_recording(session,False)
        graphics=GraphicalClient(session);graphics.record=False;graphics.start()
        driver=restore_driver(CoalDriver(session,graphics),bundle)
        start_tick,start_action=driver.current["tick"],len(driver.actions)
        session.client.call({"op":"speed","speed":10})
        save(driver.root/"iron-resume-provenance.json",{"checkpoint":str(Path(bundle).resolve()),"counter":driver.counter,
            "tick":start_tick,"continuation_sources":{str(p.relative_to(HERE)):sha256(p.read_bytes()).hexdigest()
                for p in HERE.rglob("*") if p.suffix in {".py",".lua"} and not {"out","tests","__pycache__"}.intersection(p.parts)}})
        if not resume:
            execute_feed(driver,wait_speed=40)
            prepare_iron(driver)
            checkpoint=write_iron_checkpoint(driver,driver.root/"checkpoints/iron-ready",config=config,contract=contract())
            print(json.dumps({"iron_checkpoint_ready":str(checkpoint),"tick":driver.current["tick"]}),flush=True)
        if not prepare_only:execute_iron(driver,wait_speed)
    except Exception as error:
        if Path(out).is_dir():summarize(out,"failed",started,start_tick,start_action,error)
        raise
    finally:
        if graphics:graphics.close()
        if session:session.close()
    summarize(out,"checkpoint_ready" if prepare_only else "passed",started,start_tick,start_action)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--factorio",required=True);parser.add_argument("--out",required=True,type=Path)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-feed",type=Path);source.add_argument("--resume",type=Path)
    parser.add_argument("--prepare-only",action="store_true")
    parser.add_argument("--wait-speed",type=int,choices=(10,40),default=40)
    args=parser.parse_args()
    try:run(args.factorio,args.out,from_feed=args.from_feed,resume=args.resume,prepare_only=args.prepare_only,wait_speed=args.wait_speed)
    except (OSError,ValueError,RuntimeError) as error:parser.exit(2,f"iron-supply: {error}\n")
