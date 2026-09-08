#!/usr/bin/env python3
"""Build a separate, configurable flat Nauvis scenario; never install into a live game."""

import argparse
import json
from pathlib import Path
import shutil
import sys

from advisor_core.game_import import digest
from advisor_core.model import integer

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "integration/proving-ground"
sys.path.insert(0, str(HERE / "tools"))
from build_observer import lua


def validate(config):
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise ValueError("unsupported proving-ground schema")
    integer(config.get("seed"), "seed")
    if config["seed"] >= 2**32:
        raise ValueError("seed must fit uint32")

    def coordinate(value):
        if type(value) is not int or abs(value) > 10000:
            raise ValueError("coordinates must be integers within 10,000 tiles")

    spawn = config.get("spawn")
    if not isinstance(spawn, list) or len(spawn) != 2:
        raise ValueError("spawn must be [x, y]")
    for value in spawn:
        coordinate(value)
    inventory = config.get("inventory")
    if not isinstance(inventory, dict):
        raise ValueError("inventory must be an object")
    for item, count in inventory.items():
        if item not in {"iron-plate", "wood", "stone-furnace", "burner-mining-drill"}:
            raise ValueError("unsupported starter item")
        integer(count, "inventory count", positive=True)
        if count > 100:
            raise ValueError("starter item count exceeds 100")
    occupied = set()
    for field in ("patches", "water", "trees"):
        if not isinstance(config.get(field), list) or len(config[field]) > 64:
            raise ValueError(f"{field} must be a list of at most 64 entries")
        for rect in config[field]:
            if not isinstance(rect, dict):
                raise ValueError("terrain entries must be objects")
            for key in ("x", "y"):
                coordinate(rect.get(key))
            if field != "trees":
                for key in ("width", "height"):
                    integer(rect.get(key), key, positive=True)
                    if rect[key] > 32:
                        raise ValueError("rectangle dimensions cannot exceed 32")
            if field == "patches":
                if rect.get("item") not in {"iron-ore", "copper-ore", "coal", "stone"}:
                    raise ValueError("only finite base opening minerals are supported")
                integer(rect.get("amount"), "amount", positive=True)
                if rect["amount"] > 1000000:
                    raise ValueError("resource amount exceeds one million per tile")
            width, height = rect.get("width", 1), rect.get("height", 1)
            for x in range(rect["x"], rect["x"] + width):
                for y in range(rect["y"], rect["y"] + height):
                    if (x, y) in occupied:
                        raise ValueError("terrain declarations overlap")
                    occupied.add((x, y))
            if (
                field in ("water", "trees")
                and rect["x"] - 1 <= spawn[0] <= rect["x"] + width
                and rect["y"] - 1 <= spawn[1] <= rect["y"] + height
            ):
                raise ValueError("spawn must be clear of water and trees")
    if len(occupied) > 8192:
        raise ValueError("configured terrain exceeds 8,192 tiles")
    return config


def build(config, destination):
    validate(config)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    for name in ("ground.lua", "control.lua", "description.json"):
        shutil.copy2(SOURCE / name, destination / name)
    (destination / "config.lua").write_text("return " + lua(config) + "\n")
    (destination / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    (destination / "provenance.json").write_text(
        json.dumps(
            {
                "config_sha256": digest(config),
                "surface": "nauvis",
                "extent": "standard Factorio maximum extent, generated on demand",
                "resources": "finite; never replenished",
            },
            indent=2,
        )
        + "\n"
    )
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=SOURCE / "config.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(build(json.loads(args.config.read_text()), args.out))
    except (ValueError, OSError) as error:
        parser.exit(2, f"proving-ground: {error}\n")


if __name__ == "__main__":
    main()
