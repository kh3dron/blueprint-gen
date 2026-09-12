Current development handoff

Architecture priority: develop the [declarative constructor](factory_constructor/README.md)
and its player interpreter. The acceptance criterion is a production declaration generating a
program that the player executes and verifies. Extend reusable methods and composition instead
of adding another independently authored factory scenario. `program.json` carries the goal,
requirements, method provenance, subgoal hierarchy, actions and completion predicates;
`execution.json` carries the running stack and observed node outcomes.

The constructor's 10/min and 20/min iron declarations now pass live, selecting one and two lines
and measuring 15/min and 30/min. The latter includes generated procurement from the feed-ready
checkpoint. See [compact evidence and run paths](factory_constructor/integration/README.md).
All 240 tests pass. Next implement observed deployment reuse and recursive method/connection
composition. The existing completed iron world remains useful as an integration boundary.

`13_iron_supply/` produces 30 iron plates per minute. Two drills feed coal-fueled furnaces;
powered inserters collected 150 plates during five idle minutes after two startup minutes.
Ore depletion and production each totaled 150. The connected factory mined 75 coal, burned
50 and gained 25 coal in its buffers. All 62 added entities were paid native cursor builds.
Copper supply and gear/science assembly should be constructed through the goal compiler.
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

Python/Lua execute and verify the run. Read `run-summary.json` first and expand relevant
receipts only when needed. Full evidence stays on disk. `last_observed` can predate a failure;
its later boundary is in `user-data/script-output/live-trace.jsonl`. Use fixture replay for
verifier edits, bounded engine probes for uncertain APIs and checkpoints for continuation edits.
Read the installed `doc-html/runtime-api.json` before adding API calls.

Keep the isolated graphical player connected and idle for native attribution and construction.
Actions run at 10× and passive windows at 40×; running all actions at 40× failed earlier checks.
Native collision queries choose clear standing points within observed build reach. A two-minute
startup lets both drills receive coal before measurement. Paused commands can share ticks;
stage ledger boundaries use revisions.

Resume checks source hashes, paid materials and exact idle world/command state. It reconnects
the original character and loads current continuation Lua. Arbitrary in-flight recovery remains
unfinished. Earlier PNG cleanup and boiler-loop benchmarks are recorded in
`12_boiler_feed/integration/development-loop-benchmark.json`; experiments 09–12 use opt-in `--record`.
