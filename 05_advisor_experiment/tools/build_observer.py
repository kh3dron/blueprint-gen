#!/usr/bin/env python3
"""Package the read-only Factorio observer locally; never installs into a live game."""
import argparse
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from advisor_core.rules import Rules


def lua(value):
    if isinstance(value, dict):
        return "{" + ",".join(f"[{json.dumps(k)}]={lua(v)}" for k, v in sorted(value.items())) + "}"
    if isinstance(value, list):
        return "{" + ",".join(lua(v) for v in value) + "}"
    return json.dumps(value)


def build(destination):
    rules = Rules.load()
    info = json.loads((HERE / "observer/info.json").read_text())
    target = Path(destination) / f"{info['name']}_{info['version']}"
    # Never carry stale scripts (especially test scenarios) into a release build.
    target.mkdir(parents=True, exist_ok=False)
    for path in (HERE / "observer").iterdir():
        if path.is_file() and path.suffix in (".lua", ".json"):
            shutil.copy2(path, target / path.name)
    catalog = {"recipes": sorted(rules.recipes), "machines": sorted(rules.machines),
               "technologies": sorted(rules.technologies), "items": rules.document["items"]}
    (target / "catalog.lua").write_text("-- Generated whitelist; values come from runtime prototypes.\nreturn " + lua(catalog) + "\n")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "out" / "mods")
    args = parser.parse_args()
    try:
        print(build(args.out))
    except OSError as error:
        parser.exit(2, f"build-observer: {error}. Choose an output directory without an existing mod build.\n")


if __name__ == "__main__":
    main()
