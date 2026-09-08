#!/usr/bin/env python3
"""Run a disposable engine scenario without touching the user's Factorio data/mods.

Requires a local Factorio 2.1 executable; all config, mods, saves, logs and exports
are written beneath --out. No server or GUI is started.
"""
import argparse
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import time

from build_observer import build
from advisor_core.game_import import import_capture, review_template
from advisor_core.planner import next_step
from advisor_core.production import analyze, completion

HERE = Path(__file__).resolve().parents[1]


def benchmark_metrics(log, expected_ticks):
    """Separate simulated time and engine update time from process startup/shutdown."""
    matches = re.findall(r"Performed (\d+) updates in ([\d.]+) ms", log)
    if len(matches) != 1:
        raise RuntimeError("Expected one Factorio benchmark timing summary")
    ticks, milliseconds = int(matches[0][0]), float(matches[0][1])
    if ticks != expected_ticks or not math.isfinite(milliseconds) or milliseconds <= 0:
        raise RuntimeError("Benchmark timing does not match the requested tick budget")
    return {"updates": ticks, "simulated_seconds": ticks / 60,
            "update_seconds": milliseconds / 1000,
            "update_speed_vs_realtime": ticks / 60 / (milliseconds / 1000)}


def verify(destination):
    """Require real exports and independent game counters, not just a successful process."""
    output = destination / "user-data/script-output"
    captures = sorted((output / "blueprint-gen-observer").glob("*.json"))
    if len(captures) != 2:
        raise RuntimeError(f"Expected two game exports, found {len(captures)}; inspect benchmark.log")
    first, edited = [json.loads(p.read_text()) for p in captures]
    stats = json.loads((output / "observer-smoke-results.json").read_text())

    def check(condition, message):
        if not condition:
            raise RuntimeError(message)

    observed = first["observation"]
    check(observed["valid"] and not observed["invalid_reasons"], "Stable window was invalidated")
    check(observed["end_tick"] - observed["start_tick"] == 3600, "Incorrect measurement duration")
    check(observed["produced"]["automation-science-pack"] == stats["red1_finished"] + stats["red2_finished"] == 12,
          "Red science counter differs from the 12-pack engine baseline")
    cables = sum(s["count"] for s in stats["cable_contents"] if s["name"] == "copper-cable")
    check(observed["produced"]["copper-cable"] == 2 * stats["cable_finished"] == cables == 120,
          "Cable crafts/items counter semantics differ from the engine baseline")
    check(observed["produced"]["iron-gear-wheel"] == stats["gears_finished"] == 52, "Gear counter mismatch")
    check(not edited["observation"]["valid"] and "machine configuration changed" in edited["observation"]["invalid_reasons"],
          "Recipe change did not invalidate the second window")
    snapshot, rules = import_capture(first)
    check(next_step(snapshot, rules)["kind"] == "observe", "Unknown routing/supply/power did not request observation")
    check(rules.machines["assembling-machine-1"]["electric_kw"] == 75 and rules.machines["stone-furnace"]["fuel_kw"] == 90
          and rules.machines["lab"]["electric_kw"] == 60, "Runtime energy units differ from the base profile")
    check(rules.technologies["automation"]["seconds"] == 10 and rules.recipes["automation-science-pack"]["seconds"] == 5,
          "Runtime crafting/research time units differ from the base profile")
    reviewed = review_template(first)
    # This fixture has preloaded inputs, test electricity and no material routing.
    # Finite stock deliberately never becomes an external delivery rate.
    reviewed.update(inventory={}, supplies_per_s={}, available_power_kw=10000)
    for settings in reviewed["machines"].values():
        settings.update(connected=False, output_open=True)
    finite, rules = import_capture(first, reviewed)
    check(not finite.document["observation_gaps"], "Controlled fixture review left unknowns")
    check(analyze(finite, rules)["goal_fraction"] == 0 and not completion(finite, rules)["complete"],
          "Preloaded materials incorrectly established sustained production")
    blocked = [m for m in finite.machines if m.get("recipe") == "iron-gear-wheel"]
    check(len(blocked) == 1 and not blocked[0]["output_open"], "Game's full_output status did not override review")
    rejected, _ = import_capture(edited)
    check(not rejected.document["observations"], "Invalid window survived import")
    report = {"factorio_version": first["factorio_version"], "active_mods": first["active_mods"],
              "window_ticks": [observed["start_tick"], observed["end_tick"]], "produced": observed["produced"],
              "cable_crafts": stats["cable_finished"], "cable_items": cables,
              "recipe_change_rejected": True, "unreviewed_action": "observe",
              "finite_stock_goal_fraction": 0, "full_output_overrides_review": True,
              "ruleset_sha256": rules.digest}
    (destination / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    snapshot.save(destination / "snapshot.json")
    (destination / "runtime-rules.json").write_text(json.dumps(rules.document, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    return report


def run(binary, destination, *, scenario_name="observer-smoke", scenario_directory=None, ticks=3800, verify_result=verify):
    started = time.perf_counter()
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("Choose a new --out directory so an earlier engine run cannot supply stale results.")
    destination.mkdir(parents=True)
    mod = build(destination / "mods")
    scenario = mod / "scenarios" / scenario_name
    shutil.copytree(scenario_directory or HERE / "integration/scenario", scenario)
    config = destination / "config.ini"
    binary = Path(binary).resolve()
    data = next((p / "data" for p in list(binary.parents)[:4] if (p / "data/core").is_dir()), None)
    if data is None:
        raise ValueError("Cannot locate the installation's data/core next to the Factorio executable.")
    # Factorio also discovers packages installed under its read-data directory.
    # Disable them explicitly in this temporary mod list, leaving live settings alone.
    packages = [json.loads(p.read_text())["name"] for p in data.glob("*/info.json")]
    (destination / "mods/mod-list.json").write_text(json.dumps({"mods": [
        {"name": name, "enabled": name == "base"} for name in packages if name != "core"
    ] + [{"name": "blueprint-gen-observer", "enabled": True}]}))
    config.write_text(f"[path]\nread-data={data}\nwrite-data={destination / 'user-data'}\n")
    prefix = [str(Path(binary).resolve()), "--config", str(config), "--mod-directory", str(destination / "mods")]
    durations = {}
    def execute(args, name):
        process_started = time.perf_counter()
        result = subprocess.run(prefix + args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        durations[name] = time.perf_counter() - process_started
        (destination / f"{name}.log").write_text(result.stdout)
        if result.returncode:
            raise RuntimeError(f"Factorio {name} failed ({result.returncode}):\n{result.stdout[-6000:]}")
        print(f"{name}: completed", flush=True)
    execute(["--scenario2map", "blueprint-gen-observer/" + scenario_name], "create")
    saves = sorted((destination / "user-data/saves").rglob("*.zip"))
    if len(saves) != 1:
        raise RuntimeError(f"Expected one converted scenario save, found {saves}")
    execute(["--benchmark", str(saves[0]), "--benchmark-ticks", str(ticks), "--benchmark-runs", "1"], "benchmark")
    performance = benchmark_metrics((destination / "benchmark.log").read_text(), ticks)
    performance.update(mode="unthrottled --benchmark; no game.speed override",
                       create_process_seconds=durations["create"],
                       benchmark_process_seconds=durations["benchmark"],
                       benchmark_non_update_seconds=max(0, durations["benchmark"] - performance["update_seconds"]))
    # Keep timing even if semantic verification fails. A fast run is not a passing run.
    performance_path = destination / "performance.json"
    performance_path.write_text(json.dumps(performance, indent=2) + "\n")
    verified = verify_result(destination)
    performance["total_runner_seconds"] = time.perf_counter() - started
    performance["total_speed_vs_realtime"] = performance["simulated_seconds"] / performance["total_runner_seconds"]
    performance_path.write_text(json.dumps(performance, indent=2) + "\n")
    return verified


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--factorio", required=True, help="path to the installed executable")
    parser.add_argument("--out", required=True, help="new directory for this run")
    args = parser.parse_args()
    try:
        run(args.factorio, args.out)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        parser.exit(2, f"observer-smoke: {error}\n")


if __name__ == "__main__":
    main()
