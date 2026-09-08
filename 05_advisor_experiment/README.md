05_advisor_experiment — observed-state advisor research

A separate experiment for the direction described in [the project review](../RESEARCH_REVIEW.md).
It combines a supply/power feasibility calculation, finite-inventory construction checklists,
and read-only next-step advice. It imports none of the existing tools and never writes their
caches, notebook state, or blueprints.

This version establishes the model and a [real game observation path](OBSERVER.md). It is **not yet a complete
starting-inventory-to-red-science walkthrough**: mining equipment, world placement, material
routing, and power construction are still to be implemented. Recommendations flag these missing plans
explicitly. The nine `examples/` snapshots are authored; the separate
[integration fixtures](integration/README.md) were captured in Factorio 2.1.16.

The [world survey experiment](SURVEY.md) now locates finite mineral gathering on actual tiles
and draws a map of resources, water, obstacles, and direct connections. The separate
[walking approach experiment](ROUTES.md) now compiles native paths into waypoints and exact
hand-mining instructions. An actual character has followed one such leg around water and a wall
and collected the requested ore in a disposable engine test. Automatic mining layouts remain pending.

A [configurable flat proving ground](PROVING_GROUND.md) now provides rectangular resource patches,
water, wood, and finite starter inventory. The separate [declarative factory experiment](../06_declarative_factory/README.md)
uses it to test anchored modules and incremental blueprint additions while preserving existing entities.

**Run it**

Python 3.10+ and its standard library are sufficient. Run these from the repository root:

```sh
python3 05_advisor_experiment/advisor.py next 05_advisor_experiment/examples/start.json
python3 05_advisor_experiment/advisor.py analyze 05_advisor_experiment/examples/ready.json
python3 05_advisor_experiment/advisor.py next 05_advisor_experiment/examples/missing-coal.json
python3 05_advisor_experiment/advisor.py next 05_advisor_experiment/examples/observed.json --json
python3 05_advisor_experiment/advisor.py bill 05_advisor_experiment/examples/start.json lab=1
python3 05_advisor_experiment/advisor.py profile
```

`next`, `analyze`, and `bill` accept `--json`. The script works from other working directories
when given an appropriate snapshot path. There is no `apply` command: an instruction does not
change what has been observed. Bad inputs return exit code 2 with an explanation.

For game captures, [build the observer and import its JSON](OBSERVER.md), then pass the emitted
`--rules runtime-rules.json` to the advisor. Unknown routing, supply, and generation remain
visible as an `observe` action until reviewed. The original rules/examples below use 2.1.14.

The initial advice is to produce **50 additional iron plates** for the steam-power trigger.
Its checklist reserves the starter stone furnace, requests 50 ore and four coal, places the
furnace, and schedules 160 furnace-seconds of smelting. The eight plates already in inventory
remain available; having them does not satisfy a new-crafting trigger. The subsequent electronics,
lab-crafting, and hand-crafted science bootstrap are represented by the same mechanism.

**Files**

| File | Role |
| --- | --- |
| [advisor.py](advisor.py) | CLI and readable construction checklists |
| [advisor_core/rules.py](advisor_core/rules.py) | Versioned rules, recipe choices, explicit unlock checks |
| [advisor_core/model.py](advisor_core/model.py) | Snapshot validation and lossless JSON persistence |
| [advisor_core/linear.py](advisor_core/linear.py) | Small primal simplex solver for the material/power model |
| [advisor_core/production.py](advisor_core/production.py) | Feasible-flow upper bound and observed milestone checks |
| [advisor_core/construction.py](advisor_core/construction.py) | Inventory reservation, recipe batches, surplus, handcrafting and stone-furnace fuel |
| [advisor_core/planner.py](advisor_core/planner.py) | Trigger/research prerequisites, repairs, supply deficits, missing machines, power, and verification |
| [rules/nauvis.json](rules/nauvis.json) | Checked-in subset: 28 base recipes, 28 technologies, seven machine types |
| [examples/](examples/) | Nine illustrative snapshots, including failures and coproduct production |
| [bench.py](bench.py) | Executable scenario expectations |
| [tests/test_advisor.py](tests/test_advisor.py) | Behavioral regression tests |
| [observer/](observer/) | Read-only Factorio mod source; package with `tools/build_observer.py` |
| [import_game.py](import_game.py) | Capture-specific review and runtime snapshot/rules import |
| [advisor_core/game_import.py](advisor_core/game_import.py) | Import validation, provenance, and explicit observation gaps |
| [OBSERVER.md](OBSERVER.md) | Game export/import workflow, scope, and engine checks |
| [survey.py](survey.py), [advisor_core/survey.py](advisor_core/survey.py) | Resource inspection, finite mining targets, and standalone SVG maps |
| [SURVEY.md](SURVEY.md) | Survey workflow, captured results, and remaining spatial limits |
| [route.py](route.py), [advisor_core/routes.py](advisor_core/routes.py) | Validated engine path receipts, walking waypoints, and exact mining instructions |
| [ROUTES.md](ROUTES.md) | One-leg approach workflow, collision/reach checks, and actual walking/mining results |
| [proving_ground.py](proving_ground.py), [PROVING_GROUND.md](PROVING_GROUND.md) | Configurable flat scenario with finite rectangular deposits and an engine check |
| [integration/](integration/README.md) | Disposable engine scenarios and actual captured evidence |
| [tests/test_game_import.py](tests/test_game_import.py) | Import and counter-window regression checks |
| [tests/test_routes.py](tests/test_routes.py) | Route refusal boundaries, geometry, execution provenance, and CLI checks |
| [EXPERIMENTS.md](EXPERIMENTS.md) | Results, assumptions, and next experiments |
| [tools/build_ruleset.py](tools/build_ruleset.py) | Optional authoring tool using local prototype caches |

**The snapshot contract**

Copy an example to a new JSON file when experimenting. The bundled profile is base-only Factorio
`2.1.14`, normal quality, on Nauvis. `profile` prints its id and SHA-256. A different game version,
mod set, surface, or content hash is rejected. Changing those labels alone does not make a
different game's mechanics compatible: author and validate its ruleset first.

| Field | Meaning |
| --- | --- |
| `schema_version` | `1` |
| `ruleset_id`, `ruleset_sha256`, `factorio_version`, `mods`, `surface` | Exact identity of the rules the observation uses |
| `tick` | Snapshot time in game ticks, at 60 ticks per simulated second |
| `revision` | Stable factory/configuration identity; change after relevant construction, recipe, connection, supply, power, or research changes |
| `inventory` | Finite, accessible item counts reserved by construction planning; never an ongoing supply rate |
| `crafted` | Observed crafting counters for trigger guidance; research itself still requires explicit observation |
| `researched` | Actual completed technology names, including prerequisites |
| `research_units_completed` | Optional whole completed units per technology; fractional progress is conservatively omitted |
| `supplies_per_s` | Net continuous delivery rates at the modeled factory boundary; exclude output of machines already listed |
| `goals_per_min` | Explicit positive output targets; no implicit science ladder |
| `selected_recipes` | Optional item-to-recipe selection for new construction; stored without replacing installed recipes |
| `power.available_kw` | Available generation on the one modeled network, after loads outside this model; modeled labs/crafting are deducted by the solver |
| `power.required` | Whether electricity itself is a milestone condition; defaults to true |
| `require_lab` | Whether a built, connected, powered lab is a milestone condition; defaults to true |
| `machines` | Observed machine records with stable `id`, `prototype`, `recipe`, positive integer `count`, optional `position`, and explicit `built`, `connected`, `powered`, `output_open` booleans |
| `observations` | Production-count deltas over `start_tick` / `end_tick`, with a `revision`, `source`, and `produced` map |
| `observation_gaps` | Optional list of missing facts; any gap prevents completion and makes `next` ask for observation |
| `goal_window_seconds` | Minimum measurement window; defaults to 60 seconds |
| `max_observation_age_seconds` | Maximum age of its end relative to the snapshot; defaults to 10 seconds |

`source: "automated"` means newly produced output from the modeled machines. A chest emptying,
an item transfer, and handcrafting are not automated production measurements. Other supported
source labels are `handcrafted` and `unknown`; neither can establish completion. Counts are
integers, not sampled rate estimates. The observer measures per-machine craft deltas and keeps
whole-force crafting statistics separate.

A grouped machine record describes identical machines with the same flags and recipe. If one
machine loses power or a connection, split it into a separate record. A position on a group is
only a reference location; it is not a full placement layout. `built: false` describes ghosts.
Burner furnaces ignore the electric `powered` flag but require coal in the shared material balance.

This schema covers the subset's relevant inventory and equipment. It is not a raw serialization
of every object in a save. The importer rejects unsupported captured machines/recipes/modifiers,
reports omitted inventory, and requires manual review of routing, supply, and generation.
Imported machine records also include `active` and game `status`; inactivity and `no_fuel`
disable production. Inactive labs cannot satisfy research or milestone requirements.

**What the computation means**

The solver chooses crafts/second for installed machines and maximizes a common fraction of all
requested goal rates, capped at 100%. Every ingredient is consumed once across the factory;
every coproduct is credited. Activity is limited by machine speed/count, recipe availability,
observed operating flags, furnace fuel, and electricity. A source shortage propagates to consumers.

This is an **optimistic flow bound**, not a game simulation or a prediction of exact throughput:

- Connected machines share one material pool and one electric network. Individual belt/pipe
  paths and inserter rates are absent. The importer/operator currently supplies connectivity flags.
- Excess products are allowed to leave the modeled system. `output_open: false` disables the
  entire recipe, but tank capacity, outlet throughput, and fluid dynamics are not modeled.
- Active crafting and powered labs consume electricity. Idle drain and inserters are omitted.
  Available generation is an external observation; boiler fuel/water are not simulated here.
- Furnace fuel is part of recipe input demand. Net supplied ore/coal must already account for
  upstream extraction costs; miners are not part of this first solver.
- Steady-state balances cannot prove that catalyst cycles can start. Construction planning
  rejects cycles and coproduct recipes instead of expanding them incorrectly.
- Modules, productivity, quality, beacons, enemies, walking, and machine buffers are outside scope.

Completion requires the flow bound **and** a fresh, sufficiently long automated-production
measurement for the same revision, plus the configured lab/power conditions. It establishes
the measured window's average output and modeled feasibility, not indefinite operation. A
changed revision, lost supply, short window, or stale/handcrafted measurement cannot prove it.

**Construction and next-step behavior**

`bill` reserves available inventory across the whole request, recursively computes missing
ingredients, rounds whole recipe batches, and reuses surplus. It emits hand-gathering, supply,
handcrafting, furnace placement, and smelting steps. Furnace fuel is rounded up separately for
each scheduled batch; leftover fuel in the burner is not reused yet. Already built furnaces
can be used, but their existing jobs and buffers need manual coordination.

Locked recipe steps list the missing research. Their costs are a future procurement estimate,
not permission to craft them now. Unsupported construction processes are reported. Quantities
cover the requested equipment/items; a production-module bill does not yet include its belt,
inserter, pole, or pipe layout. Mining and placement gaps appear as pending fields in JSON/text.

`next` first surfaces any missing observations, then chooses prerequisites, asks for confirmation of already-met triggers, plans remaining
science units, repairs relevant disabled hardware, requests absolute supply targets, sizes only
missing machines, checks power, and finally requests measurement. It never unlocks research,
adds inventory, counts ghosts as hardware, or marks a recommendation executed.

The flow solver supports installed oil coproducts; the construction policy currently expands
single-product opening recipes. New oil factory construction remains an explicit unsupported
method. This keeps the broader production math usable while the progression policy develops.

**Checks and data maintenance**

```sh
python3 -m unittest discover -s 05_advisor_experiment/tests -v
python3 05_advisor_experiment/bench.py
```

The separate [finite opening executor](../07_bootstrap_executor/README.md) now connects this advisor's
first instruction to actual walking/mining, costed declarative furnace placement, transfers,
50 newly smelted plates and an observed steam-power unlock. It also tests relocated resources.
The normal observer remains read-only. Full power/lab/science construction is still pending.

Runtime crafting-trigger item filters are normalized without dropping unsupported quality
constraints. Identical prerequisite sets retain the reviewed policy's scheduling order rather
than the alphabetical order of exported maps. Empty stone furnaces retain their built identity
with no recipe or production credit, allowing the next finite bill to reuse the station.

The checked-in rules, examples, and engine fixtures make the Python checks independent of `.venv`,
Factorio, ignored `data/`, and the earlier tools. One additional counter-window harness runs when
Lua/LuaJIT is installed and is skipped otherwise. The suite has 108 tests, including that harness.
See [OBSERVER.md](OBSERVER.md), [SURVEY.md](SURVEY.md), and [ROUTES.md](ROUTES.md) for the separate
actual-engine checks.

In the original `rules/nauvis.json`, machine properties are manually reviewed constants; recipes/technology were
normalized from selected local base prototypes. Provenance and prototype hashes are embedded.
That dataset is transitional. Imported profiles instead use the game's final resolved prototypes.

If the local prototype/cache inputs have intentionally changed, the authoring command is:

```sh
python3 05_advisor_experiment/tools/build_ruleset.py
```

Review the resulting rules diff, update/revalidate example profile hashes if necessary, and
rerun the checks. Do not silently update a real snapshot's hash to bypass a mismatch. The
observer's runtime export preserves the actual game version and mod set in a separate profile.
