"""Seal the iron preparation boundary using the existing idle-save machinery."""
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"08_live_executor"))
from checkpoint import dependencies, digest_file, save_json, write_checkpoint, ROOT


def prerequisites():
    result=dependencies()
    for path in (ROOT/"12_boiler_feed").rglob("*"):
        if path.suffix in {".py",".lua"} and not {"out","tests","__pycache__"}.intersection(path.parts):
            result[str(path.relative_to(ROOT))]=digest_file(path)
    return result


def write_iron_checkpoint(driver,destination,*,config,contract):
    destination=write_checkpoint(driver,destination,config=config,contract=contract)
    manifest=json.loads((destination/"checkpoint.json").read_text())
    manifest["stage"]="iron-ready"
    manifest["dependencies"]=prerequisites()
    for path in (ROOT/"13_iron_supply").rglob("*"):
        if path.suffix in {".py",".lua"} and not {"out","tests","__pycache__"}.intersection(path.parts):
            target=destination/"sources"/path.relative_to(ROOT)
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,target)
    manifest["files"]={str(p.relative_to(destination)):digest_file(p) for p in destination.rglob("*")
                       if p.is_file() and p!=destination/"checkpoint.json"}
    save_json(destination/"checkpoint.json",manifest)
    return destination


def validate_iron_checkpoint(bundle,*,config,contract):
    bundle=Path(bundle).resolve()
    manifest=json.loads((bundle/"checkpoint.json").read_text())
    if manifest.get("schema_version")!=1 or manifest.get("stage")!="iron-ready":
        raise ValueError("need a sealed iron-ready checkpoint")
    if manifest["config"]!=config or manifest["contract"]!=contract or manifest["dependencies"]!=prerequisites():
        raise ValueError("iron checkpoint prerequisites or preparation changed; prepare again")
    required={"game.zip","driver.json","evidence/actions.json","evidence/player-crafts.jsonl",
              "evidence/iron-design.json","evidence/iron-opening-observation.json","evidence/feed-verification.json"}
    if not required<=manifest["files"].keys():raise ValueError("iron checkpoint evidence missing")
    for relative,expected in manifest["files"].items():
        path=(bundle/relative).resolve()
        if not path.is_relative_to(bundle) or not path.is_file() or digest_file(path)!=expected:
            raise ValueError("iron checkpoint artifact missing or changed: "+relative)
    return manifest
