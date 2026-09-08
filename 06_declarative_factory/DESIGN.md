Toward a declarative factory

The user's two directions fit together: regular terrain removes much of the early spatial
search, and explicit module boundaries make incremental planning manageable. Use the flat
proving ground to establish the state/change semantics before asking the layout system to
solve arbitrary terrain or an entire science ladder.

**Three representations**

| Representation | Owns |
| --- | --- |
| Desired factory | Goals, requested capacity, module identities, explicit recipe/tier choices, ports and dependencies |
| Compiled design | Concrete module reservations, entity positions/settings, physical connections, construction bill, versioned artifact hashes |
| Observed deployment | Actual surface/force, entity identities/configuration, inventory, research, supply, power, production and capture freshness |

The current experiment implements typed declarations, compiled designs, additive diffs, and a
small engine observation adapter. A previous desired manifest is a comparison baseline, not
evidence that anything was built. A live implementation will reconcile all three representations.

Stable resource addresses follow module ownership and local coordinates. Blueprint entity
numbers are regenerated for export and never used as persistent IDs. Observations can bind
those addresses to actual engine unit numbers. Reordering Python declarations leaves placements
and entity addresses unchanged. Renaming or moving an established module requires a migration.

**Bus as a module with an interface**

The earlier `03_blueprint_objects` code already supplies useful concepts: typed input/output
ports, modules composed into modules, internal buses, and direct links for private intermediates.
Its `factory_tree()` groups an intermediate under its sole consumer and keeps shared inputs
on the parent bus. Preserve that rule as a strategy rather than making every intermediate a
global lane.

The next extension should give a bus stable lane assignments and reserved attachment points.
Appending a module should allocate a vacant slot and connect its ports without repacking old
modules. A new capacity request should first check spare installed capacity, then allocate an
additional module if needed. The current demo explicitly appends a module; it does not yet make
that optimization decision.

Reserve enough routing space to extend the bus. The flat environment makes this cheap. A later
compact layout optimizer can propose a separately costed migration, including interruption and
deconstruction costs, when keeping those reservations becomes expensive.

A connection contract eventually needs item/fluid identity, quality, direction, belt lane,
verified throughput, port position, clearance, power/fuel requirements, and input/output buffer
policy. This prototype covers declared item/belt interfaces and simple physical belt paths.
Compatibility of declarations must remain separate from demonstrated service under real load.
The main bus must account for aggregate demand along each segment, not only pairwise port rates.

**Update semantics**

Start with additive construction and explicit refusal of destructive migrations. Extend in this order:

1. Refresh a deployment from the read-only observer using surface/force/map identity and actual
   engine entity IDs. Recognize already completed work and partial construction.
2. Compare actual state with the previous compiled baseline. Classify missing entities, recipe
   drift, upgrades, and unmanaged obstacles before proposing changes.
3. Compile an ordered change plan: reserve space/materials, prepare supply/power, place entities,
   configure recipes, connect boundaries, verify flow, then record the new observed deployment.
4. Bind plans to a capture/revision and recheck before each action. A JSON hash detects changed
   input artifacts; it cannot detect a change in a running game by itself.
5. Add explicit migrations: update compatible settings, upgrade entities in place, move a module,
   and retire unused infrastructure. Show material cost, salvage, downtime, and dependency effects.

The Python library produces reviewable plans and blueprint artifacts. A future player frontend
should translate each planned resource into exact walking/placement/transfer instructions. A
test executor can follow the same instruction format in an isolated game. These consumers need
the same preconditions and completion observations.

**Joint milestone and next step**

The [finite opening experiment](../07_bootstrap_executor/README.md) now connects an actual starter
inventory to a declared furnace, its entity bill, native walking/mining, costed placement,
inventory transfers, 50 smelted plates and observed steam-power research. Its refresh retains the
empty furnace for the next copper job. Default and relocated-resource layouts pass. Placement is
a test adapter, and the file exchange uses deterministic replay across fresh profiles.

Next, make that exchange persistent and extend execution through copper smelting, power,
lab preparation, research, and observed 10 red science/minute. This should test module identity
and station reuse across multiple jobs before extending the approach to general bus attachments.

Keep the component-level gear test as an incremental-update regression. It provides no shortcut
past the costs, actions, and observations required by that opening benchmark.
