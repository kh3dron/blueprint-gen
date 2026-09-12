Constructor engine evidence

The iron declarations were compiled from fresh observations, serialized to JSON, and interpreted
by the same `Executor` and `PlayerPort` on Factorio 2.1.17. Each program completed its observed
subgoals and passed the independent connected-production verifier.

| Declaration | Generated lines / builds | Measured plates/min, five minutes | Connected coal buffer gain | Execution time |
| --- | --- | --- | --- | --- |
| 10 iron plates/min | 1 / 44 | 15, 15, 15, 15, 15 | 45 coal | 46.102 s |
| 20 iron plates/min | 2 / 62 | 30, 30, 30, 30, 30 | 25 coal | 150.433 s |
| Repeat existing 15/min service | 1 / 0 | 15, 15, 15, 15, 15 | 44 coal | 40.618 s |
| Extend existing service to 30/min | 2 / 16 | 30, 30, 30, 30, 30 | 25 coal | 50.750 s |

The first run used the paid iron-ready checkpoint. The second started from feed-ready,
completed that existing prerequisite, and executed the generated procurement bill of 104 iron
ore, 7 copper ore, 14 coal, 20 stone and a request for 6 wood. Whole-tree harvesting yielded
8 wood, which the final inventory ledger accounts for. Time includes the second run's feed
setup and procurement, and excludes approximately five seconds of client shutdown. Neither run
captured images. Both final saves passed ZIP integrity validation before shutdown.

The initial raw runs are `/tmp/constructor-iron-10-03` and `/tmp/constructor-iron-20-01`. Their client logs
record `Disconnecting multiplayer connection. Reason: Quit.` followed by `Goodbye`. The test
runner closes the client deliberately; the disconnect handshake took about five seconds.

The fresh-process runs are `/tmp/constructor-repeat-01` and `/tmp/constructor-expand-01`.
The repeat retained all 44 entities and spent no construction items. Expansion retained those
identities and added 16 paid entities, for 60 total. Both ran the same compiler and interpreter
against restored idle observations and passed fresh production checks. The expansion checkpoint
at `/tmp/constructor-expand-01/checkpoints/factory-idle` supplies the verified iron service for
science development.

`fixtures/iron-10.json.gz` and `fixtures/iron-20.json.gz` contain ordinary JSON compressed to
62,119 and 79,337 bytes. They preserve the program, execution state, compact report and all
inputs needed to replay the service/payment verifier. Earlier action receipts outside the
constructor's revision boundary are excluded. Existing prerequisite evidence remains in the
numbered experiment fixtures. The legacy service verifier's `goal_complete: false` refers to
the unfinished red-science milestone; `summary.goal_complete` and the program execution state
refer to the actual iron declaration.

`fixtures/iron-repeat.json.gz` and `fixtures/iron-expand.json.gz` retain the reuse and expansion
proofs in 63,858 and 74,434 bytes. They include the prior deployment and verify retained
identities, incremental payment, and each new idle measurement.

The regression tests replay both physical verifications, bind every native action to its plan
node and declared goal, verify the generated procurement, and reject false idle-recipe evidence.
The one-line run exposed a native furnace boundary state: an empty furnace can clear its recipe
between deliveries. That state is accepted only with zero progress and empty input/output;
native products, ore consumption, collected plates and fuel must still balance over every window.
The earlier direction-drift rejection tests remain in experiment 13. A negative probe is not
part of the user's normal construction program.

Retain another successful run with:

```sh
.venv/bin/python -m factory_constructor.integration.retain_evidence \
  /tmp/constructor-iron-new factory_constructor/integration/fixtures/iron-new.json.gz
```

The 10 science/min declaration passed in `/tmp/constructor-science-12`. Its 339-node program
retained 60 entities and made 158 paid native builds. Startup stabilized after eight simulated
minutes. The five subsequent samples each produced and collected 12 packs/min, with a combined
59-coal buffer gain. The run took 284.721 seconds from prepared inventory and captured zero PNGs.
`run-summary.json`, `constructor-stabilization.json` and `constructor-verification.json` in that
run record these results.

The measured interval produced 150 iron plates, 75 copper plates, 60 gears and 60 science packs.
The connected factory mined 150 coal, burned 91 and retained the remaining 59 in its buffers.
Native generation supplied 58.906 MJ during measurement, exceeding the 12.018 MJ of initial
steam and electric reserves.

`fixtures/science-10.json.gz` contains compact replay evidence. The durable completed checkpoint
is `factory_constructor/out/checkpoints/science-10`; the prepared construction input is
`factory_constructor/out/checkpoints/science-10-prepared`. Both paths are relative to the
repository root.

A fresh native process restored all 255 network entities and the exact world and ledger at tick
448266, revision 2031, with zero simulation advancement and zero PNGs. The original report is
`/tmp/constructor-science-restored-01/restore-verification.json`; the compact copy is
`fixtures/science-10-restore.json`. All 90 constructor tests pass. Repeat the restore check with:

```sh
.venv/bin/python -m factory_constructor.integration.restore_checkpoint \
  --checkpoint factory_constructor/out/checkpoints/science-10 \
  --out /tmp/science-restore-new --factorio /path/to/factorio
```

The generated production graph adds copper extraction and smelting, one gear assembler, two
science assemblers, and their belts and poles. It reuses the iron supply and steam network.
The added coal drill feeds the original collection route and receives fuel from the shared coal
chest. Machine counts come from runtime recipes and declared demand. `procurement.py` splits
gathering and processing into bounded actions, including the furnace's 50-item input limit.
The Lua bridge performs paid cursor builds and records recipes, inventories, production,
deposits, fuel and electricity.

The science layout supports at most 12 packs/min from the current verified two-output iron
checkpoint. A `constructor-prepared` checkpoint records paid raw materials or construction
items and the retained iron deployment. Startup lasts 5–30 simulated minutes, with three
consecutive balanced windows required before measurement. Each must meet production and
collection rates; fresh upstream inputs and connected fuel reserves must cover the interval.
Disconnected routes or invalid accounting fail immediately. Exceeding the startup limit fails
the program. Completion requires five consecutive idle minutes of balanced service after startup.

The runner prints compact text-only production counts each minute. Read `run-summary.json`
before opening full receipts. `constructor-stabilization.json` records the startup assessment;
`execution.json` preserves a failed node and its stack. `constructor-failure-state.json` records
native state at failure when the engine remains reachable. The native
`user-data/script-output/live-trace.jsonl` contains action boundaries beyond a stale full
observation. These diagnostics do not require screenshots or rendered traces.

Independent service-method composition, arbitrary terrain, and migration of an existing science
deployment remain unfinished. Earlier experiments still establish the initial coal/power boundary.
