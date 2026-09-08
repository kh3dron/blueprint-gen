World survey and finite mining targets

Observer **0.2.0** introduced an on-demand survey of nearby mineral deposits, water, collision obstacles,
inserter endpoints, mining drills, poles, and electrical network membership. The separate
`survey.py` CLI locates exact tiles for additional hand-mining, inspects direct faults, and
produces a standalone SVG map. This grounds the construction checklist's mineral gathering in
the actual map. Current observer **0.3.0** retains this survey and adds a separate
[walking approach workflow](ROUTES.md) for each selected target.

**Try the captured scenario**

Run from the repository root with Python 3.10+; the checked-in capture needs no game installation:

```sh
mkdir -p 05_advisor_experiment/out
python3 05_advisor_experiment/survey.py inspect \
  05_advisor_experiment/integration/survey-fixtures/connected.json
python3 05_advisor_experiment/survey.py gather \
  05_advisor_experiment/integration/survey-fixtures/connected.json \
  iron-ore=50 coal=4 --map 05_advisor_experiment/out/survey.svg
```

This locates the following **additional** materials:

| Order | Instruction | Observed stock on that tile |
| --- | --- | --- |
| 1 | Hand-mine 4 coal at `(-7.5, -3.5)` | 10 coal |
| 2 | Hand-mine 30 iron ore at `(-10.5, 0.5)` | 30 ore |
| 3 | Hand-mine 20 iron ore at `(-11.5, 0.5)` | 25 ore |

The nearby 10,000-unit iron tile is excluded because a wall prevents local character placement.
The existing finite-inventory construction bill determines missing quantities; pass its mineral
`gather` quantities to this command. Existing inventory is not deducted again. `iron-ore=50`
means collect 50 more, regardless of current stock.

Each step also prints `/advisor-route X Y COUNT`. With observer 0.3.0, run that command from
your current character position and use `route.py` to read the resulting approach. Request one
leg at a time; the survey allocation alone does not establish a path or mining reach.

Open the generated SVG for water, obstacles, copper connections, inserter pickup/drop segments,
patches, and numbered mining targets. Cyan dots mark inserter drop positions. A patch's
“eligible” quantity is the supported, locally unobstructed mineral stock; it does not establish
a walking route. The map labels up to 12 nearby patches and eight targets; CLI/JSON retain the
full bounded result. Resource tiles have SVG titles with captured amounts and coordinates.

**Capture your own area**

Build the current observer with `tools/build_observer.py` and use a separate Factorio profile as
described in [OBSERVER.md](OBSERVER.md). From the in-game console:

```text
/advisor-survey 32
```

The integer radius defaults to 32 and is limited to 1–64. The command writes a regular raw
capture with an additional `survey` object, to
`script-output/blueprint-gen-observer/player-N-tick-T-survey.json`. It samples once and does not
run in the per-tick production monitor. `/advisor-export` and `/advisor-observe` retain their
existing behavior; a survey alone contains no production measurement.

```sh
python3 05_advisor_experiment/survey.py inspect capture-survey.json --map nearby.svg
python3 05_advisor_experiment/survey.py gather capture-survey.json stone=5 coal=4 --json
```

The importer accepts 0.1.0, 0.2.0, and 0.3.0 captures, each with its exact exporter/mod
identity. It still requires review of material routing, sustained boundary supply, and available
generation. The survey CLI reads the raw capture and changes no reviews, snapshots, or game state.

**What the survey establishes**

| Observation | Use and boundary |
| --- | --- |
| Resource position, amount, products, fluid requirement, infinite flag | Finite one-item-per-cycle iron ore, copper ore, coal, and stone can be assigned to hand-mining targets. Infinite/fluid/stochastic resources cannot. |
| Local `can_place_entity` check for a character | Excludes obstructed target tiles. Does not check walking connectivity or mining reach from another location; an existing character can itself block this placement check. |
| Water tiles and entity collision boxes | Context for approaches and future layouts. Use a separate 0.3.0 route request for a checked path; clearing, landfill, and cliff removal remain unplanned. |
| Inserter pickup/drop entities and positions | Shows a removed source or destination at its actual position. A missing entity can be intentional ground-item handling; diagnosis requests inspection. |
| Pole copper connectors and electric network IDs | Shows direct wiring and observed network membership. Wire references can include ghosts; network IDs establish actual membership. |
| Generator prototype maximum, energy buffers, entity status | Context and direct fault evidence. A prototype rating or stored joules are not available generation. |
| `no_fuel`, `no_power`, blocked output | Inspection instruction at the affected coordinates. Does not guess fuel reserve quantities or construction costs. |

Patch grouping uses four neighbouring resource tiles of the same type. Patches touching the
scope edge are marked, and absent resources mean “not observed here,” not “absent from the map.”
Ungenerated chunks are reported. The mod does not generate terrain or change entities to survey
them. It uses the runtime API's bounded world access; it is not a player line-of-sight simulation.

Limits are a 128×128 tile square, 8,192 resources, 4,096 collision obstacles, 2,048 infrastructure
entities, and 16,384 total queried entities. Exceeding a limit fails explicitly and asks for a
smaller radius. The ordinary capture's 256-machine/ghost limit also applies. Dense-factory costs
at these limits have not been profiled.

Mining selection is deterministic and greedy by straight-line distance. It splits requests
across tiles without allocating any tile twice. When stock or eligible tiles run out, `unplanned`
lists remaining quantities; the known subset is still a partial checklist. `all_quantities_located`
means only that the requested stock was located. Verify safe access, mining reach, and inventory
space before following a step; capture again after depletion or construction. No walking time,
mining rate, automatic supply, or completed milestone is inferred.

**Engine validation**

```sh
python3 05_advisor_experiment/tools/run_survey_smoke.py \
  --factorio /path/to/factorio --out /tmp/advisor-survey-run-01
```

This reuses the isolated headless runner with a separate
[survey scenario](integration/survey-scenario/control.lua). It clears its disposable work area,
places finite deposits, a blocking wall, 19 water tiles, connected and isolated poles, an
unfueled burner drill, and a chest/inserter/assembler connection. It captures tick 120, removes
the chest, then captures tick 122. Assertions check allocation, blocked-tile exclusion, grouping,
actual endpoints/network membership, missing-source/fuel diagnostics, and continued supply/power
unknowns. It emits `survey.svg`, `gather-plan.json`, and `verification.json` under its new output
directory, without touching live Factorio data.

The [survey fixtures](integration/README.md) come from **Factorio 2.1.16**, base and observer 0.2.0;
the same scenario also passes with 0.3.0, with a separate verification report.
The scenario also exercises export of an idle furnace and an assembler ghost. It does not execute
player walking/mining or validate a finite-resource factory construction. The Python suite has
104 tests, including 16 survey tests, 15 route tests, and the optional Lua counter harness.

The [route experiment](ROUTES.md) now checks walking approaches and mining reach, including one
actual character replay. Next: connect these gathering legs to a legal starter furnace/drill
layout with exact placement and connection costs. Measure delivered inputs and real generation
to replace more manual review.
