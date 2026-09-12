Automatic boiler fuel

This experiment continues the [self-fueling coal supply](../11_coal_supply/README.md)
by connecting its output chest to the existing boiler. The player pays for two burner
inserters and a belt route, then loads twenty handcrafted red science packs into the lab
for Logistics research. Five one-minute observation windows measure fuel delivery and
useful electric power while the player stands idle.

```sh
python3 12_boiler_feed/run_feed.py \
  --factorio /path/to/factorio \
  --out /tmp/advisor-feed-new --speed 10

python3 12_boiler_feed/run_feed.py \
  --factorio /path/to/factorio \
  --resume /tmp/advisor-feed-new/checkpoints/feed-ready \
  --out /tmp/advisor-feed-retry --speed 10 --wait-speed 40

python3 -m unittest discover -s 12_boiler_feed/tests -v
```

Use a fresh output directory and leave the isolated experimental game window idle.
The runner repeats the opening and coal-supply checks before building the feed.
It saves a sealed checkpoint after materials procurement. `--prepare-only` stops there;
`--resume` starts a new process from a copy of that checkpoint and runs only the connection
and research test. The checkpoint retains the game, command counter, completed action
history, native crafting events, earlier verification evidence and source hashes.

Resume refuses changed prerequisite code, configuration, preparation logic, material bills,
corrupt evidence, or a loaded world that differs from the saved state. The cloned save
loads current continuation Lua while preserving its binary world and serialized storage.
Changes to the connection itself can therefore be tested against the same paid inventory.
This supports an explicit idle boundary; arbitrary crash recovery remains separate work.

`--wait-speed 40` accelerates only the six passive boiler-feed observation minutes. Player
actions use `--speed 10`, and their speed is restored after each window. The engine still
checks every tick for player inactivity and accounts for all coal and power. Both speeds
default to 10. Running all actions at 40× failed native mining and idle checks in local
benchmarks; use the separate wait speed for faster development runs. For native footage,
keep `--wait-speed 10` so the capture client can keep up.

Default runs write text evidence and action-boundary traces. They produce no screenshots
or videos. `run-summary.json` contains timings, measured checks and artifact paths.
Failures include the complete failed request and error, recent action labels and the
last observed inventory. Full action receipts and observations remain available for diagnosis.

Use `--record` when native footage is needed. This enables PNG capture and video encoding
for that run. Native footage must be captured during a rerun, such as a checkpoint replay;
JSON alone cannot reproduce the original pixels. Old completed footage remains readable
with the existing renderer. The graphical player stays attached even without recording
because native crafting attribution and cursor construction require it.

Profiles, saves and logs stay in the output directory. Cleanup closes the
processes that the runner started. The [player-capture notes](../09_player_capture/README.md)
describe profile isolation and native recording.

`BoilerFeed` derives the route from the observed chest and boiler positions. It supports
a north-facing boiler west of the chest, with the belt routed south of both endpoints.
The engine checks every placement before procurement is deployed. This authored route
does not search around arbitrary obstacles. Existing coal and power entities retain their
identities. Repeating each feed address must preserve its entity and player inventory.
The cursor adapter refuses changes to an existing entity's direction.

Both new burner inserters receive their normal initial wood energy from Factorio.
They pick coal from their input and refuel themselves. The player transfers no coal after
the connection baseline. The runtime construction bill still includes hand-mined coal
for the earlier smelting jobs.

The verifier follows native belt and inserter endpoints through to this boiler.
A meter counts coal arriving in its fuel inventory and coal that starts burning each tick.
Window checks reconcile those counts, coal deposit depletion, and all observed coal in
chests, belts, inserter hands and burner inventories. The combined fuel buffers must not
drain during the five-minute measurement.

The lab must draw at least 59 kW and advance research throughout each measurement minute.
Generation since connection must exceed the boiler's original fuel, stored steam and
electric reserves. Native crafting/build events and inventory receipts establish payment
for every added item. The final lab must have consumed all twenty packs and completed
Logistics research.

The recording overlay shows the current action, coal delivered to the boiler, remaining
fuel, electric demand and research progress. The science packs are a finite research load.
Automated ore extraction, smelting and sustained 10 red science/min remain ahead.

The continuation writes `feed-design.json`, `feed-materials.json`, `feed-baseline.json`,
`feed-reconciliation.json`, `feed-windows.json`, `feed-final-observation.json`,
`feed-verification.json` and a `boiler-feed.zip` checkpoint. Earlier powered-lab and coal
artifacts retain their own checkpoints. `coal-actions.json` ends at the coal milestone;
`actions.json` covers the complete run.
