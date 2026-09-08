Opening execution evidence — 2026-09-07

Captured with macOS ARM64 Factorio **2.1.16**, base plus observer **0.3.0** only. All execution
occurs in disposable profiles; `adapter.lua` and `control.lua` are not packaged in the observer.
See the [experiment README](../README.md) for the command, method and player-placement limitation.

| Check | Default ground | Iron patch moved to `(12,-8)` |
| --- | --- | --- |
| Additional materials mined | 4 coal, 50 iron ore | 4 coal, 50 iron ore |
| Furnace center selected from actual available sites | `(-2,-14)` | `(11,1)` |
| Walking distance | 34.3924 tiles | 53.4936 tiles |
| First observation → completed milestone | 16,394 ticks / 273.233 s | 16,526 ticks / 275.433 s |
| Furnace processing through collection | 9,602 ticks / 160.033 s | 9,602 ticks / 160.033 s |
| New iron plates, furnace and force counters | 50 | 50 |
| Final player inventory | 58 iron plates, one wood, one burner drill | Same |
| Steam power researched without granting it | Yes | Yes |
| 10 red science/min completed | No | No |

The furnace consumes four coal items, leaving 1,598,400 J in its burner after the batch. This
remaining energy is observed, not counted as a continuing coal supply. Research appears 19
ticks after plate collection in the default run; the controller waits for that actual state.

Default raw captures and compiled artifacts come from `/tmp/blueprint-gen-opening-07`. Shifted
execution comes from `/tmp/blueprint-gen-opening-shifted-02`. JSON was formatted for readability;
raw captured values were not altered. The shifted run predates the empty-furnace importer fix,
so its retained compact verification covers execution; the final next-action fixture comes from
the default run with that fix. Both execution records pass the current Python verifier.

| Fixture | Purpose |
| --- | --- |
| [initial-capture.json](fixtures/initial-capture.json), [initial-state.json](fixtures/initial-state.json) | Matching real resource/rule survey and finite character inventory before actions |
| [receipts.json](fixtures/receipts.json) | Native coal and iron routes requested from actual sequential character positions |
| [instructions.json](fixtures/instructions.json) | Advisor bill, compiled routes, observed placement candidates, typed furnace manifest and incremental entity bill |
| [execution.json](fixtures/execution.json) | Timed mining and depletion, paid placement/repeat/refusal checks, transfer ledger, furnace and force counters, delayed research |
| [final-capture.json](fixtures/final-capture.json) | Independent observer sees the same built furnace, 50 crafts and steam-power research; its empty furnace has no selected recipe |
| [next-action.json](fixtures/next-action.json) | Ten copper plates for electronics, using the already built furnace; no extra furnace bill |
| [verification.json](fixtures/verification.json) | Compact checked outcome and source hashes |
| [performance.json](fixtures/performance.json) | Separate update/process/runner timing for all five stages |
| [shifted-instructions.json](fixtures/shifted-instructions.json), [shifted-execution.json](fixtures/shifted-execution.json) | Resource relocation changes native paths and the declared furnace site, with unchanged costs |
| [shifted-verification.json](fixtures/shifted-verification.json), [shifted-performance.json](fixtures/shifted-performance.json) | Relocated-ground results and timing |

The default final stage runs **278.217 simulated seconds in 4.234 s of engine update time**:
65.7× real time. Including map conversion, process startup/shutdown and verification, that
stage takes 5.857 s, or 47.5×. The complete five-stage experiment takes 19.096 s. Its earlier
stages replay actions and include idle budget ticks, so summing simulated stage durations
would overstate useful progress. These are local measurements, not performance guarantees.

The Python tests check item/counter conservation, missing stock/sites, insufficient/obstructed
deposits, checkpoint mismatches, receipt drift, actual trigger timing, relocation, and empty
furnace reuse without production credit. They also ensure a furnace ghost cannot satisfy the
next construction bill. Interactive cursor placement, natural-map coverage, recovery from a
partially failed live action, and full red-science construction remain untested.
