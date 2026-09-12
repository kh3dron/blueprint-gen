Current development handoff

Offline planning now has a `factory_constructor sequence` command. It generates eight
cumulative build blueprints from the empty surveyed opening to 10 red and 10 green
science per minute, with an HTML stage viewer, SVG maps, a blueprint book and a JSON state
ledger. Research gates and shared recipe demand are calculated without launching Factorio.
The plans include belts, inserters, splitters, underground crossings, automatic burner fuel
feeds and wired poles, with transport costs and power sizing. Static geometry and connectivity
are checked; startup and sustained output still need a native run. These plans carry
`execution_ready: false` and `goal_verified: false`; they are not deployment evidence.
See the offline sequence section in [the constructor README](factory_constructor/README.md).

Develop the [declarative constructor](factory_constructor/README.md)
and its player interpreter. The acceptance criterion is a production declaration generating a
program that the player executes and verifies. Extend reusable methods and composition instead
of adding another independently authored factory scenario. `program.json` carries the goal,
requirements, method provenance, subgoal hierarchy, actions and completion predicates;
`execution.json` carries the running stack and observed node outcomes.

The constructor's 10/min and 20/min iron declarations pass live, selecting one and two lines
and measuring 15/min and 30/min. Fresh-process deployment reuse also passes. Run
`/tmp/constructor-repeat-01` retained all 44 entities, built none, and measured 15/min in
40.618 seconds. Run `/tmp/constructor-expand-01` retained those 44 entities, added 16, and
measured 30/min with a 25-coal buffer gain in 50.75 seconds. Its completed checkpoint is
`/tmp/constructor-expand-01/checkpoints/factory-idle`.
See [compact evidence and run paths](factory_constructor/integration/README.md).

The 10 science/min declaration passed in `/tmp/constructor-science-12`. The generated program
retained 60 iron entities and paid for 158 native builds. After eight startup minutes, it
produced and collected 12 packs/min in each of five measured minutes, with a 59-coal buffer
gain. The run took 284.721 seconds from prepared inventory and captured zero PNGs. The completed
checkpoint is `factory_constructor/out/checkpoints/science-10`; the construction-ready input is
`factory_constructor/out/checkpoints/science-10-prepared`. Compact verifier evidence is in
`factory_constructor/integration/fixtures/science-10.json.gz`.
Fresh native restore preserved all 255 network entities and the exact world and ledger at tick
448266, revision 2031, with zero simulation advancement or PNGs. The restore report is in
`factory_constructor/integration/fixtures/science-10-restore.json`. All 90 constructor tests pass.

Python expands runtime recipes into copper, gears and science services, then generates geometry,
procurement batches and executable subgoals. The added coal drill feeds the original collection
route and draws fuel from its shared chest. The program reuses the iron supply and steam network,
adds copper mining/smelting, and connects one gear assembler and two science assemblers. Lua
performs paid placement, recipe selection and native observation. Independent service-method
composition and the execution-stack viewer remain unfinished.

The science layout supports at most 12 packs/min from the current verified two-output iron
checkpoint. Procurement batches respect the furnace's 50-item input limit. Sealed
`constructor-prepared` checkpoints preserve paid raw materials or construction items before
placement. Science startup lasts 5–30 simulated minutes and requires three consecutive balanced
windows before the separate five-minute service measurement. The startup check requires fresh
upstream supply, science collection at the target rate, and nondeclining connected fuel reserves.

`13_iron_supply/` produces 30 iron plates per minute. Two drills feed coal-fueled furnaces;
powered inserters collected 150 plates during five idle minutes after two startup minutes.
Ore depletion and production each totaled 150. The connected factory mined 75 coal, burned
50 and gained 25 coal in its buffers. All 62 added entities were paid native cursor builds.
The science method constructs copper supply and gear/science assembly through the goal compiler.
Existing iron stock can pay future construction only after observed, costed native transfers.

The reusable checkpoint is `13_iron_supply/out/checkpoints/iron-ready-20260911` (6.83 MB).
It preserves tick 187138, counter 282 and the procured inventory. Replay adds actions 283–427.
The completed save and receipts are in `13_iron_supply/out/verified-iron/`, with compact
regression evidence in `13_iron_supply/integration/fixtures/`. Generated outputs are ignored by Git.

```sh
python3 13_iron_supply/run_iron.py --factorio /path/to/factorio \
  --resume 13_iron_supply/out/checkpoints/iron-ready-20260911 \
  --out /tmp/iron-retry-new
python3 -m unittest discover -s 13_iron_supply/tests -q
```

Rebuild preparation with `--from-feed 12_boiler_feed/out/checkpoints/feed-ready-20260911`
and `--prepare-only`. Preparation took 102.9 seconds; final replay took 38.1 seconds with
zero images and 31.2 MB of output. Eighteen new tests cover physical evidence, planning,
checkpoint integrity and clear construction approaches.

Python/Lua execute and verify the run. Read `run-summary.json` first, then the failed stack in
`execution.json` and fresh `constructor-failure-state.json` when present. Compact text-only
progress reports each startup and measurement minute. Full receipts stay on disk;
`user-data/script-output/live-trace.jsonl` records later boundaries when `last_observed` predates
a failure. Use fixture replay for verifier edits, bounded engine probes for uncertain APIs and
checkpoints for continuation edits.
Read the installed `doc-html/runtime-api.json` before adding API calls.

Keep the isolated graphical player connected and idle for native attribution and construction.
Actions run at 10× and passive windows at 40×; running all actions at 40× failed earlier checks.
Native collision queries choose clear standing points within observed build reach. Iron uses
two startup minutes. Science startup stops after three balanced windows once its five-minute
minimum has elapsed, or fails at the 30-minute limit. Paused commands can share ticks; stage
ledger boundaries use revisions.

Resume checks source hashes, paid materials and exact idle world/command state. It reconnects
the original character and loads current continuation Lua. Arbitrary in-flight recovery remains
unfinished. Earlier PNG cleanup and boiler-loop benchmarks are recorded in
`12_boiler_feed/integration/development-loop-benchmark.json`; experiments 09–12 use opt-in `--record`.
