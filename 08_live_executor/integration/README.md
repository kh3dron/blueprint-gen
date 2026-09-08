Live execution and recording evidence — 2026-09-07

The raw fixture comes from `/tmp/blueprint-gen-live-05`, running the installed macOS ARM64
Factorio **2.1.16** with base and observer **0.3.0** only. Its two server processes use the same
saved world; there is no replay from the opening after the first process exits. Both local
servers were stopped at the end. No starting stocks beyond the ground configuration were added.

| Evidence | Recorded outcome |
| --- | --- |
| [actions.json](fixtures/actions.json) | 28 requests with simulation intervals, wall durations, stable IDs, milestone labels and actual results |
| [restart.json](fixtures/restart.json) | Exact state match after saving and restarting; old placement request returns its result without another debit/build; stale new request refused |
| [initial-observation.json](fixtures/initial-observation.json) | Real starter inventory and matching runtime rules/resource capture |
| [final-observation.json](fixtures/final-observation.json) | Same furnace #13, 65 crafts, 22 iron plates and a paid lab in character inventory; actual force lab count remains zero |
| [milestones.json](fixtures/milestones.json) | Steam power and electronics observed complete; lab-trigger research unobserved after 600 ticks |
| [verification.json](fixtures/verification.json) | Finite inventory, machine identity, actual production and conservative final outcome |
| [next-action.json](fixtures/next-action.json) | Observe the lab attribution discrepancy before attempting another lab |
| [performance.json](fixtures/performance.json) | 399.233 simulated seconds, 13.144 wall seconds including setup/restart/planning; requested 40× speed |
| [live-world.json](fixtures/live-world.json), [live-trace.jsonl](fixtures/live-trace.jsonl) | Configured terrain and 874 actual state frames sampled every 30 ticks plus boundaries, sufficient to rerender without Factorio |

The character mines 50 iron ore, 15 copper ore and six coal. Three smelting jobs make 50 iron,
then ten copper, then five more copper for the lab's ingredients. All use the same paid furnace.
Native handcrafting makes 30 cables, ten circuits, twelve gears, four belts and one lab; individual
queue completion checks conserve the entire inventory against the runtime recipe. Handcrafting
is real, but the final lab's force-production/research credit is not observed. This difference
is retained in the fixture and visible in the recording, rather than changed to a successful trigger.

A second physical run, `/tmp/blueprint-gen-live-shifted-01`, moves the copper rectangle to `(24,8)`.
It reaches the same material/research outcome after 24,955 ticks and exercises nontrivial native
paths back to the furnace. Its compact [verification](fixtures/shifted-verification.json) and
[approach results](fixtures/shifted-approaches.json) retain the extra route evidence. This is
controlled flat terrain, not coverage of natural map obstacles or enemies.

Raw observations and command outcomes are retained without changing their values. The verification
report can be regenerated from them by the current verifier. Local output media is deliberately
ignored by Git; use the commands in the [README](../README.md) to render GIF/MP4/poster artifacts.
Those are schematic state replays, not native game screenshots. Source hashes bind the generated
recording metadata to the exact trace and world description used for rendering.
