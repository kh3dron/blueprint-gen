Experiment log — 2026-09-07

Question: can a small planner distinguish a factory design from an achievable and observed
production milestone, while providing useful finite-resource bootstrap instructions?

Latest milestone: [finite opening execution](../07_bootstrap_executor/integration/README.md)
now takes the runtime advisor's steam-power instruction through actual mining, costed furnace
placement, 50 new plates, and observed research. The final snapshot keeps the empty furnace
and asks for the next copper-smelting step. Default and relocated iron patches pass. The final
default stage runs at 65.7× real time for engine updates, or 47.5× including runner overhead;
five replay stages take 19.1 s total. This is still short of a complete 10-red-science/min opening.

The initial experiment uses authored snapshots and a base-only `2.1.14` rules subset. The next
action is evaluated against the snapshot without executing construction. A second experiment,
below, tests actual observation/import using Factorio 2.1.16 in a disposable headless scenario.

**Initial results**

Reproduce with `python3 05_advisor_experiment/bench.py` from the repository root.

| Snapshot | Common goal bound | Observed complete? | Next action |
| --- | --- | --- | --- |
| `start` | 0% | No | Produce additional iron plates for the steam-power trigger; finite smelting checklist |
| `starved` | 0% | No | Establish a missing input supply; a 1,000-pack inventory does not count as ongoing production |
| `missing-coal` | 0% | No | Deliver 2.16 coal/min for the furnaces |
| `brownout` | 29.09% | No | Increase available electricity to at least the modeled 197.5 kW active load |
| `ghosts` | 0% | No | Build the two missing red-science assemblers |
| `disconnected` | 0% | No | Repair the red-science connection; an old measurement cannot verify the changed revision |
| `ready` | 100% | No | Measure automated output |
| `observed` | 100% | Yes | The authored 60-second measurement meets the target |
| `oil-coproducts` | 100% | No | Verify installed output; all three refinery products are accounted for |

The red-science example targets 10 packs/min. It has two stone furnaces for iron, one for copper,
one assembler 1 for gears, two assembler 1s for science, and a lab. Sources deliver 20 iron ore/min,
10 copper ore/min, and three coal/min. Nominal smelting capacities are 37.5 iron and 18.75 copper
plates/min; requested smelting consumes 2.16 coal/min. The active-load model requires 125 kW for
science, 12.5 kW for gears, and 60 kW for the lab. At 100 kW total, the remaining 40 kW supports
`40 / 137.5 = 29.09%` of the production goal. Inserters and idle drain will increase real demand.

The oil example uses one advanced-processing refinery with 20 crude oil/s and 10 water/s.
It yields 5 heavy oil/s, 9 light oil/s, and 11 petroleum gas/s at a modeled 420 kW. These are
simultaneous products from one activity, not three independent refineries or discarded credits.

The initial regression suite contains 44 behavioral tests. It covers material conservation,
shared inputs and inventory, custom goals, fuel/power limits, installed machine tiers, partial
construction, recipe persistence, locked/foreign recipes, trigger/research bootstrap, and
measurement freshness. Small analytic linear-program cases check the solver independently
of the Factorio scenarios. CLI checks also run from a separate working directory.

**What this establishes**

The first model avoids several demonstrated failure modes of the existing planner: arbitrary
inventory cannot stand in for continuous supply; research is not completed by recommendation;
ghosts do not produce; fuel and shared inputs constrain output; explicit targets drive demand;
recipe identity survives persistence; and an estimated feasible rate is insufficient for `done`.

The experiment does not establish that a player can follow the opening without improvisation.
In particular, supply recommendations still require a mining plan, and equipment bills still
require placement, connections, fuel logistics, and power infrastructure. These are marked
pending by the interface. A hypothetical snapshot with authored production counts also does
not establish that any blueprint works in Factorio.

**Runtime observer results**

The [observer/import workflow](OBSERVER.md) now exports a bounded area, research, main inventory,
machine IDs/recipes/status/modifiers, and resolved runtime mechanics. A capture-specific review
supplies the remaining routing, delivery-rate, and generation facts. Unknowns stop planning at
an observation instruction. Imported rules are hashed separately from the original 2.1.14 profile.

Executed the disposable scenario with installed Factorio **2.1.16**, base plus observer 0.1.0,
for 3,800 ticks. The [raw captures and provenance](integration/README.md) are checked in.

| Check | Actual result |
| --- | --- |
| Stable 60-second window | 12 red science, 120 copper cable, 52 gears |
| Cable counter semantics | 60 `products_finished` increments, 120 items in output inventory; counter measures crafts |
| Output blockage | Gear assembler reports `full_output`; this overrides a contrary manual review |
| Recipe change during the next window | Entire window invalidated; Python importer discards its measurement |
| Runtime units | Assembler 1 uses 75 kW, furnace 90 kW fuel, lab 60 kW; automation research uses 10 seconds/unit |
| Missing review | `observe` with explicit missing routing, supply, power, and headless-inventory facts |
| Reviewed finite test stocks | Zero continuous supply and zero feasible sustained goal fraction; no false completion |

The test uses prebuilt machines, finite preloaded ingredients, test electricity, and no material
routes. It establishes the measurement/import boundary, not legal construction or a complete
opening. The empty lab's existence also does not establish working research. The smoke runner
requires JSON exports and semantic assertions; a successful process exit alone cannot pass.

The observer/import milestone brought the suite to **68 tests**: 44 original tests, 23 importer/packaging
tests, and one optional Lua harness exercising eight counter-window cases. The installed LuaJIT
ran that harness successfully. Cases include stale review hashes, forbidden mods/quality/bonuses,
multiple electric networks, actual blocked-output evidence, inactive labs, raw inventory handling,
counter resets, missing ticks, and edits restored before the end of a window. All nine authored
snapshot scenarios continue to pass.

**World survey results**

The [survey workflow](SURVEY.md), in observer 0.2.0, exports resources, water, obstacles, direct
inserter endpoints, and pole/network membership. A separate CLI groups patches, allocates finite
additional hand-mining quantities to exact tiles, and draws a standalone SVG with numbered targets.
It preserves the distinction between observed connections and verified sustained flow.

Ran the second disposable Factorio 2.1.16 scenario through tick 125. Its two actual captures
are [checked in separately](integration/README.md). The scenario established:

- Two adjacent iron tiles form a 55-unit patch. A 50-ore request allocates 30 from one tile and
  20 from the other; a four-coal request uses a third tile with 10 coal observed.
- A nearby 10,000-ore tile covered by a wall is excluded by the game's character-placement
  check, as is coal under a mining drill. This does not establish a path to the chosen targets.
- The observed water count is 19. Connected poles share a network and copper connection;
  the isolated pole has another network ID.
- The inserter's pickup/drop identities match the independently recorded chest/assembler IDs.
  Removing its source chest removes the observed pickup target and prompts inspection there.
- An unfueled burner drill is diagnosed by actual `no_fuel` status. The ordinary importer still
  leaves supply and generation unknown. Idle furnace and assembler-ghost export paths also run.

Sixteen new survey tests bring the suite to **84 tests**. They cover clipped patches, empty and
insufficient surveys, no double allocation, inventory independence, stochastic/fluid/infinite
resource rejection, identity/tick/area validation, fault observations, and standalone map/CLI use.
The SVG was rendered and visually checked. The original production scenario also runs with
observer 0.2.0, while historical 0.1.0 fixtures remain supported.

That survey scenario tests surveying and planning quantities, not execution or a legal opening
construction sequence. Walking and reach are tested separately below; clearance actions and
full placement validation remain pending.

**Walking and mining results**

Observer 0.3.0 adds `/advisor-route X Y COUNT`, a read-only request for a native path from the
actual character to one finite mineral tile. [The route CLI](ROUTES.md) validates its receipt,
preserves turns, and emits walking waypoints plus an exact additional mining quantity. Surveys
now attach that command to each gathering step. A matching survey can supply the background
for an SVG overlay of the approach and mining stance.

The disposable route scenario constructs a water strip and a friendly wall between the
character and iron ore. It also contains an unreachable mineral island and separate characters
for invalidation/current-reach checks. A first engine run exports receipts; Python compiles the
successful one; a second run follows those compiled instructions in a fresh copy of the scene.
The controller uses actual `walking_state`, selection, reach, and `mining_state`, without
teleporting or instantly mining during execution.

| Check | Actual Factorio 2.1.16 / observer 0.3.0 result |
| --- | --- |
| Water-and-wall detour | 23.3469 planned tiles; 23.3801 tiles walked; all waypoints reached |
| Exact finite gathering | 3 iron ore added to inventory, 3 removed from the target; wall preserved |
| End-to-end leg timing | 527 ticks / 8.78 simulated seconds from controller start |
| Island surrounded by water | `no_path`, no walking instructions |
| Character moves during pathfinding | `invalidated`, no walking instructions |
| Observed build event during pathfinding | `invalidated`, no walking instructions |
| Target already within conservative reach | `ready`, one current-position waypoint and no walking |
| Walkable belt covering a mineral | Request rejected before pathfinding because selection is obstructed |

Adding the wall exposed an empirical issue: with the character's raw tile-transition collision
mask, the native pathfinder returned a route across water. An independent collision sweep
rejected that route. Explicitly adding `water_tile` to the pathfinder mask and disabling tile
transition handling produced the detour that passed physical execution. Ready native receipts
now require the independent swept-character-box check as well as native success. The search
uses 0.25 tile extra clearance; the sweep queries bounding boxes covering every subsegment of
at most 0.125 tile. These conservative checks may reject valid narrow routes. This finding is
limited to the tested configuration and does not establish a general engine defect.

[Route fixtures](integration/README.md) preserve requests, compiled instructions, their shared
SHA-256, and actual execution evidence. Fifteen route tests bring the suite to **99 tests**.
They cover detour preservation, backtracking, profile/constraint mismatch, missing collision
evidence, stale ticks, invalidated/unreachable results, survey pairing, and CLI input preservation.
The map was rendered and visually checked. All nine original snapshot scenarios pass, and both
the original production/import and survey engine scenarios also pass with observer 0.3.0.

This is one controlled walking/mining leg. It does not prove optimal target order, natural-map
coverage, enemy avoidance, sustained mining, placement, or a complete opening. Post-receipt
edits require fresh observation; the standalone CLI cannot see the current game by itself.

**Next experiments**

The user's flat-map and declarative-module directions now have separate prototypes:

- [Flat proving ground](PROVING_GROUND.md): finite rectangular coal/iron/copper/stone deposits,
  a water rectangle, four trees, explicit starter inventory, and flat terrain generated on demand.
  Both the default row and an iron patch moved across four chunk boundaries pass Factorio 2.1.16
  checks. Each run verifies 256 observed mineral positions and amounts, 64 water tiles, four trees,
  no completed research, exact starter inventory, distant land, and no resource replenishment.
  Five configuration/isolation tests bring the advisor suite to **104 tests**.
- [Declarative factory revisions](../06_declarative_factory/README.md): stable nested addresses,
  anchored geometry, typed ports, explicit belt connections, incremental entity bills and blueprints,
  and baseline-bound drift checks. The engine test preserves 28 entities, adds 18 for a second gear
  module, adds zero on repeat, and rejects missing technology, an unmanaged wall, and recipe drift.
  Each module produces 18 gears through its physical feed. Its **16 separate Python tests** pass.

The declarative test uses granted research, construction entities, electricity, and finite input
plates. Declared rates remain unverified contracts; the test does not certify 60 gears/min/module.
Neither new experiment completes the finite opening. FLE source inspection and the choice to
implement this terrain directly against 2.1.16 are documented in the proving-ground workflow.

Prioritize joining these pieces into one finite starter-smelting run, then power/labs and red
science. Use the following experiments as the remaining backlog:

1. Expand approach validation across terrain, narrow obstacles, dynamic interference, and
   natural map seeds. Chain finite gathering legs with fresh observations after each action;
   record manual interventions and refusal causes. Add save/load and stale-receipt checks in
   the engine, and profile collection/path costs before adding continuous polling.
2. Add a placement-aware opening method. Generate a small burner-smelting/power/lab layout from
   surveyed resource/shoreline anchors. Include all inserters, poles, pipes, belts, fuel reserves,
   and construction order in its bill. Honor current technology for every entity. Replan around
   a partially built layout without inventing completed work.
3. Run the finite opening in Factorio. Begin from a fixed seed with finite starting inventory;
   record every instruction, manual intervention, construction cost, and observed result through
   powered labs and 10 red science/min. The game, not the snapshot LP, judges throughput.
4. Inject failures. Remove fuel, disconnect a belt, restrict power, and block an output. Check
   whether advice identifies the specific fault and observes recovery without needless rebuilding.
5. Extend the production/construction coupling. Replace raw supply requests with mining and
   fuel-supply methods, measure delivered inputs and actual available generation, introduce
   stock buffers and durations, then optimize alternative builds. Add fluids and oil construction
   only once coproduct disposal and starting conditions are represented.

Keep new modules and scenario assets in this experiment while their interfaces stabilize. The
existing blueprint generator can later supply layouts through a small adapter that validates
entity availability and preserves observed hardware. Changes to the original tools should be
separate, targeted work with their own validation.
