Finite opening executor experiment

This connects the [advisor](../05_advisor_experiment/README.md),
[flat proving ground](../05_advisor_experiment/PROVING_GROUND.md), and
[declarative factory objects](../06_declarative_factory/README.md) through one observed milestone:
produce 50 additional iron plates and unlock steam power from finite starting inventory.
It is a separate, mutating **test scenario**, excluded from the read-only observer package.

The real Factorio 2.1.16 run starts with eight iron plates, one wood, one furnace and one burner
drill. The advisor's 10-red-science/min goal selects the steam-power prerequisite. Its runtime
materials bill requires 50 ore and four coal. Python allocates surveyed mineral tiles, compiles
native route receipts, and declares a 2×2 furnace module at an engine-checked site. The character
walks and mines, the adapter debits and places the furnace, and transfers conserve inventory.
Ordinary furnace updates produce the plates; actual research and independent production counters
are checked before this milestone is reported complete.

The goal remains **10 red science/min**, and is still incomplete. This experiment establishes
the first smelting step. Electricity, copper smelting, lab construction, research, automated
mining, transport, and sustained science output still need execution methods.

Run from the repository root using a local Factorio 2.1.16 executable:

```sh
python3 07_bootstrap_executor/run_smoke.py \
  --factorio /path/to/factorio \
  --out /tmp/blueprint-gen-opening-new

python3 -m unittest discover -s 07_bootstrap_executor/tests -v
```

`--out` must be new. All mods, maps, saves, exports and logs stay in that disposable directory.
`--config` accepts the proving-ground JSON format. This first method requires the starter
furnace, one sufficiently stocked accessible tile per mineral, routes within 64 tiles, and a
clear furnace site near the final standing position. It refuses unsupported openings or paths.

Artifacts include `procurement.json`, `instructions.json`, readable `instructions.txt`, the
furnace blueprint, `final-snapshot.json`, `next-action.json`, verification and performance reports.
Every stage retains its raw observer captures and actual character inventory checkpoints.
The final advisor instruction is to smelt ten copper plates for electronics, reusing the
observed empty furnace. It conservatively budgets one new coal; residual burner energy is
recorded but not reused by construction planning yet.

**What execution proves**

- Native `walking_state` and timed `mining_state` collect exactly four coal and 50 ore, with
  matching depletion. No teleport, instant mining, or supplied factory inputs occur during execution.
- The typed module's entity bill is one stone furnace. Placement pays that item, preserves its
  stable address, and repeating placement retains the same entity without another debit.
- Loading and collection check reach, stock and destination capacity, and record paired debits
  and credits. Out-of-reach, collision, missing-item and short-transfer probes leave inventory intact.
- Furnace and force counters both record 50 newly produced plates. Starting plates remain intact.
  Smelting takes 9,602 ticks; research is observed 19 ticks after collection in the default run.

**Boundaries**

The benchmark has a standalone normal character, not a connected `LuaPlayer`. Cursor building
is a player-only API. `integration/adapter.lua` therefore uses a conservative center-distance
reach check, the engine's manual collision check, inventory debit, and `create_entity` with a
raised build event. It does not exercise the interactive cursor/build event path. Transfers
similarly use checked inventory operations, rather than GUI clicks. These are costed adapters
for controlled tests, not a finished player automation API.

Python and Factorio exchange files across five fresh replay stages: observe, request coal path,
walk/mine coal and request iron path, finish gathering and observe placement sites, then replay
and smelt. Each later path is requested from the **actually reached** checkpoint. Earlier
actions are replayed; native receipts are regenerated and must exactly match the receipts used
to compile their instructions. Runtime start/stock checks and an exact placement checkpoint
comparison also guard replay. Receipt comparisons happen after the disposable run; this is not
a continuously connected execution loop or a safe replay protocol for an unrelated live save.

Sites come from engine collision checks and exclude resource tiles. The nearest clear site is
chosen within build/transfer reach; it is not a long-term factory layout optimization. There is
no main-bus connection on this standalone furnace and no throughput claim for its finite batch.

Two small shared fixes were necessary: runtime `craft-item` filters now normalize to item names
without discarding unsupported quality constraints, and unchanged prerequisite sets retain the
reviewed policy's ordering rather than adopting alphabetical export order. Empty stone furnaces
are retained as built hardware with no recipe or modeled production; they can be reused by the
next finite construction bill. Unconfigured assemblers still require observation.

**Speed**

The shared engine runner uses `--benchmark`, which advances a fixed number of normal ticks
without real-time pacing. No extra `game.speed` setting is needed. `performance.json` separates
simulation seconds, engine update time, map creation, process overhead and total runner time.
Stage budgets include idle ticks, and stages repeat actions; their sum is not unique gameplay
progress. Hardware load also affects the reported speeds.

FLE's [`GameControl.set_speed`](https://github.com/JackHopkins/factorio-learning-environment/blob/e2a829d22a635a9a111d21bf5523e09e903ae145/fle/env/instance.py)
sets Factorio's `game.speed` through RCON and restores it on unpause. Thus 10×/40× pacing is an
option for a future persistent FLE session, subject to CPU capacity. We currently use the
installed Factorio binary directly. Speed changes do not justify shortcuts that grant items,
skip mining costs, or confuse simulated ticks with wall time.

The next useful experiment is a persistent checkpoint loop that can refill/reuse this furnace
for copper, then construct and observe steam power and a lab. That will also test whether the
same declarative addresses survive multiple jobs and refreshed live observations.

See [integration evidence](integration/README.md) for recorded outcomes and limitations.

The next experiment now exists separately in [08_live_executor](../08_live_executor/README.md).
It continues from an actual save in a persistent world, reuses this furnace for copper, and
records GIF/MP4 state replays. Native lab crafting exposes an uncredited research trigger;
that discrepancy is retained as the next observation task rather than bypassed.
