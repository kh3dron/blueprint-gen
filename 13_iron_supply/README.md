Automatic iron plates

Two burner drills feed stone furnaces directly from the north edge of the surveyed iron
patch. The existing coal chest supplies both drills and furnaces through a belt trunk and
branch. Two electric inserters collect the plates in chests, using the existing steam network.

The Factorio 2.1.17 run collected 30 iron plates per minute for five consecutive idle minutes
after two startup minutes. It mined 150 ore and produced and collected 150 plates. Across
the connected coal, boiler and iron modules, 75 coal were mined, 50 burned and fuel buffers
grew by 25 coal. The player made no transfers or inventory changes during measurement.

All 62 new entities were paid native cursor builds. Repeated placement preserved entities
and inventory, and direction drift was refused. Earlier coal, power and boiler entities
kept their identities. `iron-materials.json` records the procurement bill.

From the repository root:

```sh
python3 13_iron_supply/run_iron.py --factorio /path/to/factorio \
  --from-feed 12_boiler_feed/out/checkpoints/feed-ready-20260911 \
  --out /tmp/iron-prepared-new --prepare-only

python3 13_iron_supply/run_iron.py --factorio /path/to/factorio \
  --resume 13_iron_supply/out/checkpoints/iron-ready-20260911 \
  --out /tmp/iron-retry-new

python3 -m unittest discover -s 13_iron_supply/tests -q
```

Preparation replays the boiler stage, checks the sites and procures the iron module.
The checkpoint retains 282 prior actions and the paid inventory. Replay executes 145 new actions.
The final verified replay took 38.1 seconds and wrote 31.2 MB with zero images. The retained
checkpoint is 6.83 MB. Player actions run at 10× and passive waits at 40×; `--wait-speed 10`
uses the slower wait mode. Leave the isolated game window idle.

Resume validates configuration, prerequisites, preparation, artifact hashes and the idle world.
Current continuation Lua loads into a copy of the save. Changed material bills require new
procurement. Native collision checks select clear standing points within observed build reach.

The verifier checks every ore, fuel, power and output endpoint. Per-tick meters cover all
connected burners. Window balances reconcile ore depletion, ore consumption, work in progress,
finished plates, collected plates and coal stocks. Eighteen tests also reject altered evidence,
missing native events, unpaid construction and shortened startup or measurement windows.

The layout supports a rectangular iron patch with a coal chest to its west; furnaces sit
outside the resource tiles. A general bus planner remains unfinished. The output receipt retains
chest identities and measurement ticks. Copper and gear/science assembly remain before 10 red science/min.

Compact evidence is in `integration/fixtures/`. The local completed save and text evidence
are retained in `out/verified-iron/`; the original run is `/private/tmp/blueprint-gen-iron-build-07`.
