"""Seal a verified, idle deployment for a fresh process to compile its next goal."""
import json
from pathlib import Path
import shutil

from .legacy import ROOT
from checkpoint import digest_file, write_checkpoint
from iron_checkpoint import prerequisites
from .deployment import refresh
from .program import save


CONTRACT = {"method": "constructor-idle-v1"}


def write(driver, destination, *, config, prepared=None):
    deployment=json.loads((driver.root/"deployment.json").read_text())
    refresh(deployment,driver.observations[-1])
    # The shared writer uses a fixed save name. Remove its previous staging
    # archive so its ZIP-completion check cannot mistake an older save for this one.
    staging = driver.session.root / "user-data/saves/dev-feed-ready.zip"
    staging.unlink(missing_ok=True)
    destination=write_checkpoint(driver,destination,config=config,contract=CONTRACT)
    manifest=json.loads((destination/"checkpoint.json").read_text())
    manifest.update(stage="constructor-prepared" if prepared else "constructor-idle",dependencies=prerequisites())
    if prepared:
        manifest["preparation"] = prepared
    for directory in (ROOT/"13_iron_supply",ROOT/"factory_constructor"):
        for path in directory.rglob("*"):
            if path.suffix in {".py",".lua"} and not {"out","tests","__pycache__"}.intersection(path.parts):
                target=destination/"sources"/path.relative_to(ROOT)
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(path,target)
    manifest["files"]={str(p.relative_to(destination)):digest_file(p) for p in destination.rglob("*")
                       if p.is_file() and p!=destination/"checkpoint.json"}
    save(destination/"checkpoint.json",manifest)
    return destination


def validate(bundle, *, config):
    bundle=Path(bundle).resolve()
    manifest=json.loads((bundle/"checkpoint.json").read_text())
    if manifest.get("schema_version")!=1 or manifest.get("stage") not in {"constructor-idle", "constructor-prepared"}:
        raise ValueError("need a sealed constructor checkpoint")
    if manifest["config"]!=config or manifest["contract"]!=CONTRACT or manifest["dependencies"]!=prerequisites():
        raise ValueError("constructor checkpoint prerequisites or configuration changed")
    required={"game.zip","driver.json","evidence/actions.json","evidence/player-crafts.jsonl",
              "evidence/deployment.json","evidence/program.json","evidence/execution.json",
              "evidence/constructor-verification.json","evidence/feed-design.json","evidence/coal-design.json"}
    if not required<=manifest["files"].keys():
        raise ValueError("constructor checkpoint evidence missing")
    for relative,expected in manifest["files"].items():
        path=(bundle/relative).resolve()
        if not path.is_relative_to(bundle) or not path.is_file() or digest_file(path)!=expected:
            raise ValueError("constructor checkpoint artifact missing or changed: "+relative)
    deployment=json.loads((bundle/"evidence/deployment.json").read_text())
    driver=json.loads((bundle/"driver.json").read_text())
    refresh(deployment,driver["latest_observation"])
    if manifest["stage"] == "constructor-prepared":
        preparation = manifest["preparation"]
        state = driver["latest_observation"]["state"]
        if state.get("science") or any(state["inventory"].get(k, 0) < v for k, v in preparation["items"].items()):
            raise ValueError("prepared checkpoint is already constructed or lacks its construction items")
        if preparation["deployment_sha256"] != deployment["sha256"]:
            raise ValueError("prepared checkpoint deployment changed")
        return manifest
    execution=json.loads((bundle/"evidence/execution.json").read_text())
    if execution["status"]!="observed-complete" or execution["program_sha256"]!=deployment["program_sha256"]:
        raise ValueError("constructor checkpoint did not complete its deployment")
    return manifest
