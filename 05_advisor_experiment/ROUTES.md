Walking approaches and exact hand-mining instructions

Observer **0.3.0** can request a native Factorio path from the player's character to one mineral
tile. The separate `route.py` CLI turns its receipt into walking waypoints, a mining stance, and
an exact additional item count. The normal mod remains read-only: it requests paths and exports
observations; it never walks, mines, or places anything for the player.

A separate engine harness has followed the Python-compiled instructions using an actual
character's walking and mining controls. This establishes one controlled gathering leg, not a
complete opening, automatic mining layout, or general coverage of natural maps.

**Try the captured approach**

From the repository root with Python 3.10+; no game installation is needed to read the fixtures:

```sh
python3 05_advisor_experiment/route.py \
  05_advisor_experiment/integration/route-fixtures/detour.json \
  --survey 05_advisor_experiment/integration/route-fixtures/survey.json \
  --map 05_advisor_experiment/out/approach.svg
```

The character starts at `(-8.5, 0.5)` and approaches iron at `(8.5, 0.5)`, detouring around a
water strip and a friendly wall. Open the SVG: the gold line follows the checked waypoints,
the white dot marks the mining stance, and the numbered target is the ore tile. The final
instruction requests **three additional iron ore**. `--json` includes the full waypoint list,
receipt hash, captured tick, preconditions, and completion check.

**Request a leg in your game**

Build observer 0.3.0 and use the separate game profile described in [OBSERVER.md](OBSERVER.md).
Use the [survey workflow](SURVEY.md) to locate finite additional mineral quantities first:

```text
/advisor-survey 32
```

```sh
python3 05_advisor_experiment/survey.py gather capture-survey.json iron-ore=50 coal=4
```

Each gathering step now prints an `/advisor-route X Y COUNT` command for that target. Request
the next leg from your current character position. For example, the captured test target uses:

```text
/advisor-route 8.5 0.5 3
```

Use the coordinates and quantity from your own survey. Stay still until the result is announced.
The request runs asynchronously and writes
`script-output/blueprint-gen-observer/route-character-ID-request-SEQUENCE.json`. Copy that file
to your working directory and read it:

```sh
python3 05_advisor_experiment/route.py receipt.json
python3 05_advisor_experiment/route.py receipt.json --json
```

Follow the turns, check actual mining reach, then mine the stated additional quantity. Check
the inventory increase and matching depletion. Capture again and request the next leg from
the new position. Gathering order is still greedy by straight-line distance; the CLI does not
optimize a tour or pretend later legs have already been checked.

If supplying `--survey capture-survey.json --map approach.svg`, the survey must precede the
request by at most 600 ticks, match the mods, map seed, force, surface, and generation, and cover
the entire route and target. A previous survey from another scenario cannot supply the map.

**Receipt states and freshness**

| Receipt state | CLI behavior |
| --- | --- |
| `ready` | Emit walking/mining instructions; an already-reachable target needs no walking |
| `no_path` | Ask for observation; no path found under the conservative constraints |
| `invalidated` | Ask for a fresh request; character/resource/world changed, or the returned path failed validation |
| `retry` | Ask to retry after a busy pathfinder or 600-tick request timeout |

A ready receipt is evidence of a checked approach at its completion tick. It is not evidence
that the player followed it, nor proof that the current world is unchanged. Requests are
invalidated if the character moves/changes, the target changes, or an observed configuration
event changes the generation while pathfinding. Edits after the receipt require a new request.

`--current-tick N` additionally refuses instructions more than **600 ticks (10 simulated
seconds)** old. Without that argument the CLI cannot determine current age. Even a recent tick
does not establish an unchanged world; moving entities, enemies, and unobserved edits can
invalidate an approach. No receipt automatically advances a construction checklist or milestone.

**Scope and collision checks**

- Base plus observer only, Factorio 2.1, Nauvis, a normal character outside a vehicle. Engine
  validation currently covers **2.1.16** only.
- Finite deterministic one-item-per-cycle iron ore, copper ore, coal, and stone. Quantities are
  integers from 1–1,000, within the tile's observed stock and the character's inventory capacity.
  Targets must be within 64 tiles. Fluid-requiring/infinite/stochastic resources are rejected.
- A selectable entity over the target, including a walkable belt, prevents mining instructions.
  Clearing it is a separate action; it is never silently destroyed.
- Native paths use the character collision box plus **0.25 tile** clearance and a goal radius
  **0.5 tile inside** the observed resource reach. Gates, destruction, paths through owned
  entities, and cached paths are disabled. Returned routes are limited to 256 tiles and 2,048
  waypoints; there are at most eight pending requests and one per character.
- The pathfinder mask explicitly blocks water. An independent check then sweeps the actual
  character box across every path segment, using subsegments at most **0.125 tile** long and
  checking engine terrain/entities. Each query box encloses the full subsegment, including the
  space between samples; only the requesting character is ignored. Conservative geometry can
  reject valid narrow approaches. The current-reach branch uses `can_reach_entity` directly.
- The compiler removes duplicates and collinear points only while continuing in the same
  direction. It preserves corners and backtracking. Neither route distance nor the isolated
  timing below predicts completion time on an arbitrary save.

In the controlled wall/water scenario, the native pathfinder with the raw character mask
returned a path across water. Explicit water blocking plus the independent sweep rejected that
approach and produced a route the actual character could follow. This is an observed failure
case and a conservative workaround, not a general claim about all engine pathfinding.

**Engine evidence and reproduction**

```sh
python3 05_advisor_experiment/tools/run_route_smoke.py \
  --factorio /path/to/factorio --out /tmp/advisor-route-run-01
```

Supply a fresh output directory. The runner stages two disposable profiles, excluding all
scenario/controller code from the normal observer package:

1. `request/` constructs a bounded scene and requests five routes: a water/wall detour, an
   unreachable island, movement invalidation, an already-reachable target, and world-edit
   invalidation. It separately checks rejection of a belt-covered mineral. Python validates
   the exported receipts and writes `compiled-plan.json` and `approach.svg`.
2. `execution-scenario/` embeds those compiled waypoints and their receipt hash. `execute/`
   starts a fresh copy of the scene and controls a real character using `walking_state` and
   `mining_state`. This phase uses no teleport or instant mining. It checks actual reach,
   selection, all waypoints, exact inventory increase/depletion, and preservation of the wall.

The captured **2.1.16 / observer 0.3.0** run planned **23.35 tiles**, walked **23.38 tiles**, and
collected exactly **3 ore**, removing exactly **3** from the target. It completed in **527 ticks
(8.78 simulated seconds)** after controller start. Setup creates terrain, entities, and an empty
character inventory for the test; it does not construct this scene legally from starter items.

[Fixtures and provenance](integration/README.md) retain request, survey, compiled-plan, and
physical execution evidence separately. The original production/import and survey scenarios
also pass with observer 0.3.0. The Python suite has **104 tests**, including 15 route tests and
the optional Lua counter harness.

Next: test more terrain and obstacle arrangements, then connect these gathering legs to legal
starter furnace/drill placement and observed smelting. Sustained extraction, logistics, power
construction, and the full finite-inventory opening still require their own engine evidence.
