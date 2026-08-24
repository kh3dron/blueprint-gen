#!/usr/bin/env python3
"""Run every case in CASES through compose.py and print one row each, against a recorded baseline.

    bench.py [--only PAT]... [--save] [--jobs N] [--list] [--full] [--no-cells] [-v]

Each case is a compose.py command line. The result table is size, area, entity count, bus lanes,
direct links, warnings and wall time; with `bench.json` present every number is shown against its
baseline and a case that grew is marked REGRESSED. `--save` rewrites the baseline from this run.

    bench.py                     run everything, compare to bench.json
    bench.py --only science      only the cases whose name contains "science"
    bench.py --save              accept the current numbers as the baseline
    bench.py --full              include the slow cases (marked SLOW below)

Exit code 0 = every case built and nothing regressed by more than TOL, 1 = otherwise. CELLS at the
end is a separate structural check of every fluid recipe's generated cell: overlaps, ports on the
right entity, inserter reach in both orientations, blueprint-string round trip.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
BASELINE = os.path.join(HERE, "bench.json")
TOL = 0.02              # a case may grow this much before it counts as a regression

# name, compose.py arguments, tags
CASES = [
    # spec mode: modules named item=rate, and a composite from a file
    ("circuits",              "circuits copper-cable=6 electronic-circuit=2", ""),
    ("inserters",             "inserters inserter=1 electronic-circuit=1 iron-gear-wheel=1 copper-cable=3", ""),
    ("plastics",              "plastics plastic-bar=2", "fluid"),
    ("chips",                 "chips sulfuric-acid=10 processing-unit=0.2", "fluid"),
    ("nested-file",           "nested-file {out}/circuits.module.json iron-gear-wheel=1 inserter=1", "needs:circuits"),
    # factory mode, small
    ("green-circuit",         "electronic-circuit 2 --raw iron-plate --raw copper-plate", ""),
    ("military-1",            "military-science-pack 1", ""),
    ("military-1-robo",       "military-science-pack 1 --roboports", "robo"),
    ("red-circuit-ore",       "advanced-circuit 1", "fluid"),
    ("red-circuit-plates",    "advanced-circuit 1 --from-plates", "fluid"),
    # fluid cells: chemical plant, refinery, assembler on crafting-with-fluid
    ("sulfuric-acid",         "sulfuric-acid 20 --from-plates", "fluid"),
    ("battery",               "battery 2 --from-plates", "fluid"),
    ("concrete",              "concrete 5 --from-plates", "fluid"),
    ("rocket-fuel",           "rocket-fuel 1 --from-plates", "fluid"),
    ("blue-circuit",          "processing-unit 1 --from-plates --belt fast-transport-belt", "fluid"),
    # 4-ingredient recipes
    ("robot-frame",           "flying-robot-frame 1 --from-plates", "fluid"),
    ("utility-turbo",         "utility-science-pack 1 --raw iron-plate --raw copper-plate --belt turbo-transport-belt", "fluid"),
    ("utility-plates",        "utility-science-pack 1 --from-plates", "fluid"),
    ("production",            "production-science-pack 1 --from-plates", "fluid"),
    # options
    ("military-1-one-sided",  "military-science-pack 1 --one-sided", ""),
    ("military-1-no-links",   "military-science-pack 1 --no-links", ""),
    ("military-1-tune",       "military-science-pack 1 --tune", ""),
    ("red-circuit-nested",    "advanced-circuit 1 --from-plates --nested", "fluid"),
    ("green-circuit-cells",   "electronic-circuit 6 --raw iron-plate --raw copper-plate --cells 2", ""),
    # scaled out
    ("military-10",           "military-science-pack 10", ""),
    ("military-10-robo",      "military-science-pack 10 --raw iron-plate --raw copper-plate --roboports", "robo"),
    ("red-circuit-10",        "advanced-circuit 10 --raw iron-plate --raw copper-plate --roboports --one-sided", "fluid robo"),
    ("blue-circuit-10",       "processing-unit 10 --raw iron-plate --raw copper-plate --belt fast-transport-belt", "fluid SLOW"),
]
def run(case, out_dir, extra):
    name, args, _ = case
    stats = os.path.join(out_dir, name + ".json")
    cmd = [PY, os.path.join(HERE, "compose.py")] + args.format(out=out_dir).split() + \
          ["--no-render", "-o", out_dir, "--stats", stats] + extra
    t = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE)
    took = time.time() - t
    if p.returncode != 0 or not os.path.exists(stats):
        tail = [ln for ln in (p.stdout + p.stderr).splitlines() if ln.strip()]
        return {"name": name, "ok": False, "seconds": round(took, 2),
                "error": (tail[-1].strip() if tail else f"exit {p.returncode}")[:110]}
    with open(stats) as f:
        d = json.load(f)
    d.update(name=name, ok=True, seconds=round(took, 2))
    return d


def regressed(d, base):
    """A case counts as regressed when it grew by more than TOL against the baseline."""
    if not base or not d.get("ok"):
        return False
    return any(base.get(k) and d.get(k, 0) > base[k] * (1 + TOL) for k in ("area", "entities"))


def cells_check():
    """Every fluid recipe through fluidcells: geometry, ports, inserter reach, round trip."""
    sys.path.insert(0, HERE)
    import make, fluidcells                                   # noqa: E402
    from module import Module, mirror                         # noqa: E402
    rt = make.load_recipe_tool()
    ok = bad = rejected = 0
    problems = []
    for r in rt.load_recipes():
        ing, res = r.get("ingredients") or [], r.get("results") or []
        if not (any(i["type"] == "fluid" for i in ing) or any(x["type"] == "fluid" for x in res)):
            continue
        if not any(c in fluidcells.CATEGORY_MACHINE for c in (r.get("categories") or [])):
            continue
        try:
            pl = fluidcells.plan(r, 1.0, rt, belt="transport-belt")
            mods = fluidcells.build_from_plan(pl, columns=2)
        except ValueError:
            rejected += 1
            continue
        bad_here = []
        for m in mods + ([] if pl["layout"]["no_mirror"] else [mirror(x) for x in mods]):
            bad_here += m.check()
            occ, tiles = {}, {}
            for e in m.entities:
                n = e["name"]
                sz = fluidcells.MACHINES[n]["size"] if n in fluidcells.MACHINES else 1
                h = sz // 2
                cx, cy = int(e["position"]["x"] - 0.5), int(e["position"]["y"] - 0.5)
                occ[(cx, cy)] = e
                for dx in range(-h, h + 1):
                    for dy in range(-h, h + 1):
                        t = (cx + dx, cy + dy)
                        if t in tiles:
                            bad_here.append(f"overlap at {t}: {tiles[t]} / {n}")
                        tiles[t] = n
                        if not (0 <= t[0] < m.width and 0 <= t[1] < m.height):
                            bad_here.append(f"{n} tile {t} outside {m.width}x{m.height}")
            belt_col = {p.x: p.io for p in m.inputs + m.outputs if p.kind == "belt"}
            for p in m.inputs + m.outputs:
                e = occ.get((p.x, p.y))
                if e is None:
                    bad_here.append(f"port {p.item} at ({p.x},{p.y}) sits on nothing")
                elif p.kind == "pipe" and e["name"] != "pipe":
                    bad_here.append(f"pipe port {p.item} on {e['name']}")
                elif p.kind == "belt" and not e["name"].endswith("transport-belt"):
                    bad_here.append(f"belt port {p.item} on {e['name']}")
            for e in m.entities:                              # inserters: pick from / drop into the right thing
                if "inserter" not in e["name"]:
                    continue
                reach = 2 if e["name"] == "long-handed-inserter" else 1
                x, y = int(e["position"]["x"] - 0.5), int(e["position"]["y"] - 0.5)
                dx, dy = fluidcells.DIRV[e["direction"]]
                pick, drop = (x + reach * dx, y + reach * dy), (x - reach * dx, y - reach * dy)
                pn, dn = tiles.get(pick), tiles.get(drop)
                into = dn in fluidcells.MACHINES and pick[0] in belt_col and belt_col[pick[0]] == "in"
                out = pn in fluidcells.MACHINES and drop[0] in belt_col and belt_col[drop[0]] == "out"
                if not (into or out):
                    bad_here.append(f"{e['name']} at {(x, y)} picks {pn} drops {dn}")
            if len(Module.from_string(m.to_string()).entities) != len(m.entities):
                bad_here.append("blueprint string round trip lost entities")
        if bad_here:
            bad += 1
            problems.append(f"{r['name']}: {'; '.join(sorted(set(bad_here))[:2])}")
        else:
            ok += 1
    return ok, bad, rejected, problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", action="append", default=[], metavar="PAT",
                    help="run only cases whose name or arguments match this regex (repeatable)")
    ap.add_argument("--save", action="store_true", help="write this run to bench.json as the new baseline")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    ap.add_argument("--list", action="store_true", help="print the cases and exit")
    ap.add_argument("--full", action="store_true", help="include the cases tagged SLOW")
    ap.add_argument("--no-cells", action="store_true", help="skip the fluid cell structural check")
    ap.add_argument("-o", "--out-dir", default=os.path.join(HERE, "out", "bench"))
    ap.add_argument("--arg", action="append", default=[], help="extra argument for every compose.py run (repeatable)")
    ap.add_argument("-v", "--verbose", action="store_true", help="print the command of every case")
    args = ap.parse_args()

    cases = [c for c in CASES if not args.only or any(re.search(p, c[0]) or re.search(p, c[1]) for p in args.only)]
    if not args.full:
        cases = [c for c in cases if "SLOW" not in c[2]]
    if args.list:
        for n, a, t in cases:
            print(f"{n:<22}{t:<16}compose.py {a}")
        return 0
    os.makedirs(args.out_dir, exist_ok=True)
    base = {}
    if os.path.exists(BASELINE) and not args.save:
        with open(BASELINE) as f:
            base = {d["name"]: d for d in json.load(f)}

    first = [c for c in cases if "needs:" not in c[2]]        # cases that consume another case's output
    then = [c for c in cases if "needs:" in c[2]]
    if then and not any(c[0] in ["circuits"] for c in first):
        first, then = first + then, []                        # its input is not being built: let it fail loudly
    results, t0 = [], time.time()
    for group in (first, then):
        if not group:
            continue
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            results += list(pool.map(lambda c: run(c, args.out_dir, args.arg), group))
    results.sort(key=lambda d: [c[0] for c in cases].index(d["name"]))

    head = f"{'CASE':<22}{'SIZE':>11}{'AREA':>13}{'ENTITIES':>13}{'LANES':>7}{'LINKS':>7}{'WARN':>6}{'TIME':>7}"
    print(head)
    print("-" * len(head))
    failed, regress = [], []
    for d in results:
        b = base.get(d["name"])
        if not d["ok"]:
            failed.append(d)
            print(f"{d['name']:<22}{'FAILED':>11}  {d['error']}")
            continue
        bad = regressed(d, b)
        if bad:
            regress.append(d)
        size = f"{d['width']}x{d['height']}"
        area = f"{d['area']:,}" + (f" {(d['area'] - b['area']) / b['area'] * 100:+.0f}%" if b and b.get("area") and b["area"] != d["area"] else "")
        ents = f"{d['entities']:,}" + (f" {(d['entities'] - b['entities']) / b['entities'] * 100:+.0f}%" if b and b.get("entities") and b["entities"] != d["entities"] else "")
        print(f"{d['name']:<22}{size:>11}{area:>13}{ents:>13}{d['lanes']:>7}{d['links']:>7}"
              f"{d['warnings']:>6}{d['seconds']:>6.1f}s" + ("  REGRESSED" if bad else ""))
        if args.verbose:
            print(f"{'':<22}compose.py {dict((c[0], c[1]) for c in CASES)[d['name']]}")
    print("-" * len(head))
    tot_area = sum(d.get("area", 0) for d in results if d["ok"])
    tot_ents = sum(d.get("entities", 0) for d in results if d["ok"])
    print(f"{'TOTAL':<22}{'':>11}{tot_area:>13,}{tot_ents:>13,}"
          f"{'':>7}{sum(d.get('links', 0) for d in results if d['ok']):>7}"
          f"{sum(d.get('warnings', 0) for d in results if d['ok']):>6}{time.time() - t0:>6.1f}s")
    print(f"\n{len(results)} case{'s' * (len(results) != 1)}: {len(results) - len(failed)} built, "
          f"{len(failed)} failed, {len(regress)} regressed"
          + ("" if base else " (no baseline: run --save to record one)"))

    if not args.no_cells:
        ok, bad, rejected, problems = cells_check()
        print(f"CELLS {ok} fluid recipes build clean, {bad} broken, {rejected} rejected as too big for a cell")
        for pr in problems[:10]:
            print("  " + pr)
        failed += [{"name": "cells"}] * bad

    if args.save:
        with open(BASELINE, "w") as f:
            json.dump(results, f, indent=1)
        print(f"wrote {BASELINE}")
    return 1 if failed or regress else 0


if __name__ == "__main__":
    sys.exit(main())
