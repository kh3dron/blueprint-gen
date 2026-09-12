"""Sealed, reusable idle checkpoints for local experiment development."""
from hashlib import sha256
import json
from pathlib import Path
import shutil
import time
from zipfile import BadZipFile, ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]


def digest_file(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n")


def dependencies():
    """Hash executable prerequisites, excluding tests, recordings and fixtures."""
    result = {}
    for directory in ("05_advisor_experiment", "06_declarative_factory", "07_bootstrap_executor",
                      "08_live_executor", "09_player_capture", "10_powered_lab", "11_coal_supply"):
        for path in (ROOT / directory).rglob("*"):
            if (path.suffix in {".py", ".lua", ".json"} and path.is_file()
                    and not {"out", "tests", "fixtures", "__pycache__"}.intersection(path.relative_to(ROOT / directory).parts)):
                result[str(path.relative_to(ROOT))] = digest_file(path)
    return result


def validate_bundle(bundle, *, config, contract):
    bundle = Path(bundle).resolve()
    manifest = json.loads((bundle / "checkpoint.json").read_text())
    if manifest.get("schema_version") != 1 or manifest.get("stage") != "feed-ready":
        raise ValueError("unsupported checkpoint stage or schema")
    if manifest["config"] != config or manifest["contract"] != contract:
        raise ValueError("checkpoint configuration or preparation contract changed; prepare a new checkpoint")
    current = dependencies()
    if manifest["dependencies"] != current:
        changed = sorted(k for k in set(current) | set(manifest["dependencies"])
                         if current.get(k) != manifest["dependencies"].get(k))
        raise ValueError("checkpoint prerequisite code changed: " + ", ".join(changed))
    for relative, expected in manifest["files"].items():
        path = (bundle / relative).resolve()
        if not path.is_relative_to(bundle) or not path.is_file() or digest_file(path) != expected:
            raise ValueError("checkpoint artifact missing or changed: " + relative)
    required = {"game.zip", "driver.json", "evidence/actions.json", "evidence/player-crafts.jsonl"}
    if not required <= manifest["files"].keys():
        raise ValueError("checkpoint is missing required evidence")
    return manifest


def rewrite_scenario(source, destination, scenario):
    """Clone the save, replacing only its Lua source with the current controller.

    Binary world data, entities, inventories and serialized storage are copied
    unchanged. Prerequisite hashes are checked by validate_bundle before this.
    """
    with ZipFile(source) as src, ZipFile(destination, "w", ZIP_DEFLATED) as dst:
        roots = {name.split("/")[0] for name in src.namelist()}
        if len(roots) != 1 or not any(n.endswith("/script.dat") for n in src.namelist()):
            raise ValueError("unsupported Factorio save archive")
        prefix = next(iter(roots)) + "/"
        lua_files = {p.name: p.read_bytes() for p in Path(scenario).glob("*.lua")}
        for info in src.infolist():
            name = info.filename.removeprefix(prefix)
            data = lua_files.pop(name) if name in lua_files else src.read(info)
            dst.writestr(info, data)
        for name, data in lua_files.items():
            dst.writestr(prefix + name, data)


def write_checkpoint(driver, destination, *, config, contract):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    observed = driver.session.client.call({"op": "checkpoint_state"})
    if not driver.actions or observed["last_command_id"] != driver.actions[-1]["request"]["id"]:
        raise ValueError("driver and game command ledgers disagree")
    if {k:v for k,v in driver.current.items() if k != "furnace_sites"} != observed["state"]:
        raise ValueError("checkpoint needs a fresh observation at the idle boundary")
    driver.session.client.call({"op": "save", "name": "dev-feed-ready"})
    source = driver.session.root / "user-data/saves/dev-feed-ready.zip"
    deadline = time.monotonic() + 15
    while True:
        try:
            with ZipFile(source) as archive:
                if archive.testzip() is not None:
                    raise BadZipFile("unfinished save")
            break
        except (FileNotFoundError, BadZipFile):
            if time.monotonic() >= deadline:
                raise TimeoutError("checkpoint save was not completed")
            time.sleep(.05)
    shutil.copy2(source, destination / "game.zip")
    evidence = destination / "evidence"
    evidence.mkdir()
    for path in driver.root.glob("*.json"):
        shutil.copy2(path, evidence / path.name)
    shutil.copy2(driver.session.output / "player-crafts.jsonl", evidence / "player-crafts.jsonl")
    save_json(destination / "driver.json", {"counter": driver.counter, "milestone": driver.milestone,
        "latest_observation": driver.observations[-1], "game": observed})
    # Preserve source for later inspection/replay, but compare only prerequisites
    # when resuming. The experiment under test is allowed to change.
    prerequisites = dependencies()
    for relative in prerequisites:
        path = destination / "sources" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, path)
    for path in (ROOT / "12_boiler_feed").rglob("*"):
        if path.suffix in {".py", ".lua"} and not {"out", "tests", "__pycache__"}.intersection(path.parts):
            target = destination / "sources" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    manifest = {"schema_version": 1, "stage": "feed-ready", "config": config, "contract": contract,
        "dependencies": prerequisites, "tick": driver.current["tick"],
        "files": {str(p.relative_to(destination)): digest_file(p) for p in destination.rglob("*") if p.is_file()}}
    save_json(destination / "checkpoint.json", manifest)  # Seal only after all files exist.
    return destination


def restore_driver(driver, bundle):
    bundle = Path(bundle)
    saved = json.loads((bundle / "driver.json").read_text())
    actual = driver.session.client.call({"op": "checkpoint_state"})
    if actual != saved["game"]:
        raise ValueError("loaded world or command ledger differs from checkpoint; no continuation executed")
    for path in (bundle / "evidence").glob("*.json"):
        shutil.copy2(path, driver.root / path.name)
    driver.session.output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bundle / "evidence/player-crafts.jsonl", driver.session.output / "player-crafts.jsonl")
    driver.actions = json.loads((driver.root / "actions.json").read_text())
    driver.counter = saved["counter"]
    if driver.actions[-1]["request"]["id"] != f"action-{driver.counter:03}":
        raise ValueError("checkpoint driver command counter is inconsistent")
    driver.observations = [saved["latest_observation"]]
    driver.current = actual["state"]
    driver.milestone = saved["milestone"]
    return driver
