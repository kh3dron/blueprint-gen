Self-fueling coal supply

This separate experiment continues the [powered-lab opening](../10_powered_lab/README.md)
in the same live world. Its next module uses the spare starter burner drill, seven belts,
two burner inserters and a wooden chest. One inserter returns mined coal to the drill;
the other exports surplus to the chest. Each burner receives one paid seed coal.

The player harvests a surveyed tree with native selection and timed mining to obtain wood
for the chest. The tree must disappear, its native mining event must identify the same tree,
and the inventory gain must equal its runtime products. Construction uses the existing
runtime materials bill and normal player cursor. Repeating every module address retains
its entity; changing the existing drill's direction is refused.

```sh
python3 11_coal_supply/run_coal.py \
  --factorio /path/to/factorio \
  --out /tmp/advisor-coal-new --speed 10 --record

python3 11_coal_supply/render_coal.py /tmp/advisor-coal-new \
  --out /tmp/advisor-coal-video-new

python3 -m unittest discover -s 11_coal_supply/tests -v
```

Use a fresh output folder. The runner opens an isolated graphical client and a localhost
server; leave that experimental window idle. All profiles, saves, screenshots and recordings
stay in the output directory. Cleanup closes only owned processes. See the
[capture workflow](../09_player_capture/README.md) for Steam behavior and profile isolation.
The native MP4/GIF overlay shows the current action, chest contents, mined coal and burner
fuel. The labeled ring marks the observed actor position. Playback speed is independent
of simulation speed.

The local [MP4](out/recording/run.mp4) is 116.9 seconds at 12× playback, 1280×720,
and about 10.4 MB. [GIF](out/recording/run.gif), [poster](out/recording/poster.png), and
source-image hashes are alongside it. All 1,738 source frames were present; the export
contains 1,403 frames at 12 fps. The GIF is much larger (about 116 MB). Generated media and
raw captures are ignored by Git. Simulation speed accepts 10× or 40×; graphical validation
uses 10×. One-minute actions at 1× would exceed the inherited driver's wall-time limit.

`CoalLoop` is an immutable Python declaration anchored to one fully surveyed rectangular
coal patch. It gives entities stable addresses and names each output/fuel connection. This
is a small authored layout, not a general mine or bus router. The tree scout currently uses
one fixed intermediate waypoint on the flat proving ground; it does not search arbitrary maps.

The default Factorio 2.1.17 run passed. After a **60-second startup**, five consecutive idle
minutes delivered **12, 13, 13, 11 and 13 coal**: **12.4/min net** to the output chest.
Startup delivered another six, leaving 68 coal in the chest. The drill mined 75 during the
five measured minutes, and all three burners together started consuming 17 coal since seeding.
The total startup fuel energy, including native inserter wood, could power this drill for at
most 86.67 seconds; the observed run lasted 360 seconds with no refueling by the player.
The four tiles beneath the drill retain 3,911 coal.

The continuation costs 18 additional hand-mined iron ore, seven coal (four for conservative
smelting jobs and three for seeding), and one tree yielding four wood. It adds 11 native
cursor builds and 13 handcrafting batches. Final player stock is two wood, one belt and one
spare pole. The complete run, including the powered-lab opening, takes 83,406 ticks
(1,390.1 simulated seconds) and 171.77 wall seconds before encoding, about 8.1× overall at 10×.

Moving the coal patch eight tiles west and twelve south moves all 11 placements by the
same offset. That physical run also passes with identical costs, chest gains and fuel
accounting. Reproduce it with `--config 11_coal_supply/integration/shifted-coal.json`.

The verifier checks five consecutive one-minute idle windows after the recorded startup.
It joins runtime production
counters to deposit depletion and actual chest gains, checks belt and inserter endpoints,
accounts for coal in all lanes/hands/fuel inventories, and requires consumption beyond the
three-item seed. The engine's native initial wood energy in burner inserters is included in
the conservative seed-energy bound. No extra fuel or materials may be transferred during
the measurement. Measured output goes into a finite chest; resource patches remain finite.

The coal result does **not** establish 10 red science/min. It also does not prove coal delivery
to the boiler or smelters. Those connections, automated ore extraction and science assembly
remain next. The shared advisor continues to import zero established continuous supplies
until a separate integration can attach measured service evidence to the correct consumer.

`coal_profile.py` adds only `burner-inserter` to this experiment's reviewed recipe selection policy.
Its ingredients, outputs and timing are exported from the running engine. The observer and
driver now accept explicit profiles; experiments 05–10 retain their default catalog. A few
optional runner/placement hooks allow this experiment to reuse the powered-lab controller
without duplicating it. Coal entities live in their own registry, separate from furnaces
and the power island.

The output retains the powered-lab checkpoint as `final-observation.json`, `power-actions.json`
and `verification.json`. The continuation writes `coal-design.json`, `coal-materials.json`,
`coal-reconciliation.json`, `coal-warmup.json`, `coal-windows.json`, `coal-final-observation.json`,
`coal-verification.json` and a `coal-supply.zip` checkpoint. `actions.json` and native traces
cover the complete run. See [integration evidence](integration/README.md).

Eleven tests cover real default/shifted evidence and reject disconnected fuel return,
unmatched deposit depletion, stored coal without new delivery, player interventions,
missing native events, unpaid inventory and runs explainable by seed energy alone.
All 177 tests across experiments 05–11 pass.
