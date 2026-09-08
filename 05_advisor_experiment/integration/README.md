Observer integration evidence

[scenario/control.lua](scenario/control.lua) is a **test-only factory-mutating scenario**.
The normal observer package excludes it. The smoke runner stages it only inside an isolated
temporary game profile, with preloaded finite materials and an electric energy interface.
This tests measurement/import behavior; it does not test building the factory legally from
starting inventory or supplying it indefinitely.

The checked-in JSON was captured on 2026-09-07 with the installed macOS ARM64 Factorio **2.1.16**
(build 87294). Active packages were base 2.1.16 and blueprint-gen-observer 0.1.0; expansions and
other packages were disabled in the temporary mod list. JSON formatting was changed for
readability; captured values were not authored or corrected by hand.

| Artifact | Evidence |
| --- | --- |
| [fixtures/stable.json](fixtures/stable.json) | Raw capture at tick 3630; the window beginning at tick 30 produced 12 red science, 120 cable, and 52 gears |
| [fixtures/recipe-change.json](fixtures/recipe-change.json) | Raw capture at tick 3770; changing one recipe at tick 3710 invalidated the window beginning at 3650 |
| [fixtures/engine-counters.json](fixtures/engine-counters.json) | Independent scenario counters and cable output inventory at tick 3631; 60 cable crafts and 120 cable items |
| [fixtures/verification.json](fixtures/verification.json) | Compact assertions/report from the engine runner and Python importer |
| [fixtures/observer-0.2-verification.json](fixtures/observer-0.2-verification.json) | Successful rerun of the original production scenario with observer 0.2.0; historical raw 0.1.0 captures are preserved |
| [fixtures/observer-0.3-verification.json](fixtures/observer-0.3-verification.json) | Original production/import assertions also pass with observer 0.3.0 |

The gear assembler reached `full_output` at 52 items. Red-science inputs were preloaded into
each machine; cable/gears had their own separate finite stocks. There are no material routes.
The lab has electricity but no active research. Headless execution has no player inventory,
which is explicitly marked unobserved. A completed review for this controlled fixture records
zero continuous external supplies and disconnected material routes; the resulting flow goal
fraction is zero despite the measured production.

Reproduce with the command in [OBSERVER.md](../OBSERVER.md). Each run requires a new output
directory. After intentionally changing the observer or scenario, inspect the new exports and
verification report before replacing these fixtures. Do not silently replace them just to make
a regression pass. Different map seeds/entity IDs may change captures without changing the
counter assertions. The test clears its bounded work area and does not exercise resource maps.

**Survey evidence**

[survey-scenario/control.lua](survey-scenario/control.lua) is a second test-only scenario, run
with Factorio 2.1.16 and observer 0.2.0. Its hand-placed resource fixtures isolate observation
and allocation behavior; they do not establish coverage across natural map seeds.

| Artifact | Evidence |
| --- | --- |
| [survey-fixtures/connected.json](survey-fixtures/connected.json) | Tick 120: finite deposits, water/obstacles, actual chest/inserter/assembler endpoints, copper connections, and separate electrical networks |
| [survey-fixtures/removed-source.json](survey-fixtures/removed-source.json) | Tick 122, after the source chest was destroyed at tick 121: the inserter's pickup entity is absent |
| [survey-fixtures/engine-entities.json](survey-fixtures/engine-entities.json) | Scenario-side identities of the constructed entities, used to check exported endpoints and poles independently |
| [survey-fixtures/verification.json](survey-fixtures/verification.json) | Engine/Python assertions for finite mining targets, obstruction, grouping, wiring, and fault diagnostics |
| [survey-fixtures/observer-0.3-verification.json](survey-fixtures/observer-0.3-verification.json) | Same survey assertions pass with observer 0.3.0; historical raw captures retain their original version |

The 50-iron/4-coal request produces three targets: 4 coal, 30 ore, then 20 ore. A wall-covered
10,000-ore tile and coal under a burner drill are excluded by character-placement checks. The
unfueled drill is diagnosed, and the inspector detects the removed chest. The capture includes
an idle furnace and an assembler ghost; neither becomes working production hardware.

These are actual engine captures, reformatted as JSON only, recorded on 2026-09-07. Reproduce
with `tools/run_survey_smoke.py` as documented in [SURVEY.md](../SURVEY.md). The runner creates
an SVG map and plan in its output directory. It does not execute any mining or walking.

**Walking/mining evidence**

[route-scenario/control.lua](route-scenario/control.lua) is a third test-only scenario. The
normal observer package excludes it and its controller. It constructs a water strip, a wall,
finite deposits, and characters in a cleared area. Request and execution stages run as separate
Factorio 2.1.16 profiles with observer 0.3.0. These fixtures were captured on 2026-09-07; only
JSON formatting was changed.

| Artifact | Evidence |
| --- | --- |
| [route-fixtures/detour.json](route-fixtures/detour.json) | Native route around water and a wall, with explicit water blocking and independent swept collision validation |
| [route-fixtures/unreachable.json](route-fixtures/unreachable.json) | No path to the water-enclosed mineral island |
| [route-fixtures/moved.json](route-fixtures/moved.json) | Pending route invalidated after deliberate character movement |
| [route-fixtures/in-reach.json](route-fixtures/in-reach.json) | Actual reach check yields a single current-position waypoint |
| [route-fixtures/world-changed.json](route-fixtures/world-changed.json) | Pending route invalidated by a raised build event |
| [route-fixtures/preflight.json](route-fixtures/preflight.json) | A walkable belt over coal prevents a mining approach request |
| [route-fixtures/survey.json](route-fixtures/survey.json) | Matching tick-119 survey for the approach map |
| [route-fixtures/compiled-plan.json](route-fixtures/compiled-plan.json) | Python-generated walking/mining instructions and source receipt SHA-256 |
| [route-fixtures/execution.json](route-fixtures/execution.json) | Physical replay: positions, distance, all waypoints reached, actual reach, exact ore gain/depletion, preserved wall, and matching receipt SHA-256 |
| [route-fixtures/verification.json](route-fixtures/verification.json) | Assertions across request and execution stages |

The request stage deliberately teleports a separate character to test invalidation. The
execution stage starts a fresh copy of the scene, embeds the Python-compiled plan into the
test-only [route_plan.lua](route-scenario/route_plan.lua), and uses `walking_state` and
`mining_state` without teleport or instant mining. The normal template is empty; the runner
writes instructions only into its temporary scenario copy.

The replay walks 23.3801 tiles and collects exactly three ore in 527 ticks, with all waypoints
reached and the friendly wall preserved. Scene construction is test setup and is not paid for
from starter inventory. The timing covers walking/mining after controller start, not path
request latency or setup. Unreachable/invalidation/preflight results are engine exercised;
the busy-pathfinder branch and stale-tick CLI behavior are currently Python regression cases.

Reproduce using `tools/run_route_smoke.py` as documented in [ROUTES.md](../ROUTES.md). The runner
requires fresh output directories and validates actual files and semantics at both stages.
The approach map, compiled JSON, raw exports, execution evidence, and logs remain under that
directory. This validates one controlled leg, not full opening construction or natural-map coverage.

**Flat proving-ground evidence**

[proving-ground/](proving-ground/) is the configurable terrain implementation, separate from the
observer. [proving-ground-smoke/control.lua](proving-ground-smoke/control.lua) supplies only the
test probes. These captures come from Factorio 2.1.16, base plus observer 0.3.0, on 2026-09-07.

| Artifact | Evidence |
| --- | --- |
| [ground-fixtures/default-survey.json](ground-fixtures/default-survey.json) | Default resource row, rectangular water, trees, and player marker |
| [ground-fixtures/default-verification.json](ground-fixtures/default-verification.json) | Exact resource counts/amounts and 256 surveyed coordinates, starter inventory, zero research, distant flat land, and no replenishment |
| [ground-fixtures/shifted-survey.json](ground-fixtures/shifted-survey.json) | Iron patch moved to `(29,29)`, spanning four chunk boundaries |
| [ground-fixtures/shifted-verification.json](ground-fixtures/shifted-verification.json) | Same checks pass with the changed resource location and a distinct configuration hash |
| [ground-fixtures/boundary-tree-verification.json](ground-fixtures/boundary-tree-verification.json) | Shifted iron plus a tree at a chunk edge; neighboring chunk initialization preserves all four trees |

Each resource rectangle contains 64 tiles and 64,000 initial units. The probe removes three units
from the first coal tile directly to test repeated chunk handling; the subsequent survey shows
997 there. That is deliberately separate from the route harness's actual character mining.
The headless character receives the configured finite starting inventory. The ordinary player
join handler has not been separately exercised in an interactive session.

Default dimension zero is normalized by the installed engine to 2,000,000 tiles per axis. Terrain
generation uses a high elevation and applies explicit tiles/resources per chunk. The check requests
new chunks at x=1,024 during runtime, beyond the initial area. These are controlled maps, not
coverage tests for normal terrain. Reproduce with [PROVING_GROUND.md](../PROVING_GROUND.md).

The separate [declarative engine fixture](../../06_declarative_factory/integration/README.md) uses
this same terrain implementation for module placement and incremental update checks.

The [finite opening execution evidence](../../07_bootstrap_executor/integration/README.md) now
joins the survey, native routes and runtime construction bill to one paid declarative furnace.
It mines four coal and 50 ore, smelts and collects 50 plates, observes steam-power research,
and retains the empty furnace for the next bill. Default and relocated-resource runs pass.
Its placement adapter and sequential replay limits are documented separately.

All shared engine runners now write `performance.json`: simulated tick duration, unthrottled
engine update time, map conversion/process durations and total runner time. Benchmark mode
already runs without real-time pacing; it does not need FLE or a `game.speed` override.
