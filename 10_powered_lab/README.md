Native construction and a powered lab

This separate experiment continues the [player-attached opening](../09_player_capture/README.md)
through steam power and **Automation research**. Every placed structure, including the starter
furnace, uses the connected player's real cursor. No construction items, electricity, fluids,
research or production statistics are granted.

The agent surveys the pond, declares a small power island, procures its runtime materials bill,
walks to the site and places a pump, pipe, boiler, steam engine, pole and lab. It loads three
paid coal, crafts ten red science packs, returns to the lab and starts Automation research.
Normal game ticks consume all ten packs and complete the technology in 6,000 ticks (100 seconds).

The finite run mines **91 iron ore, 26 copper ore, 16 coal and five stone**. The same furnace
completes 117 crafts. Final player inventory is one unused burner drill and one spare small
electric pole; the pole recipe makes two at a time. Seven native `on_built_entity` events match
seven one-item cursor debits. Blocked placement, out-of-reach placement and missing items are
refused without changing inventory or entities; repeating the lab declaration retains its entity.

Both the default pond and a pond moved eight tiles east and twenty south pass. The shifted
run takes 53,607 ticks (893.45 simulated seconds) and 113.79 wall seconds before encoding,
about 7.85× overall at the requested 10× game speed. Its last five research seconds show **60 kW**
generated and consumed; cumulative lab consumption is **6,001,066.67 J**, including initial buffer charge.

**Run and inspect**

From the repository root, with Factorio, Pillow and optionally ffmpeg installed:

```sh
python3 10_powered_lab/run_power.py \
  --factorio /path/to/factorio \
  --out /tmp/advisor-powered-lab-new --speed 10 --record

python3 10_powered_lab/render_power.py /tmp/advisor-powered-lab-new \
  --out /tmp/advisor-power-video-new
```

The output folder must be new. The runner opens an isolated graphical client connected to its
own localhost server. Leave the experimental window idle while it operates. Profiles, saves,
logs, screenshots and recordings stay under that folder; cleanup closes only owned processes.
The [player/capture documentation](../09_player_capture/README.md) explains Steam initialization,
temporary profile isolation, required GUI/socket access and source-image hashing.

The video shows native Factorio imagery with the current action, inventory, actual five-second
electric generation/load averages and Automation research progress. The labeled ring is the
observed character position; native screenshots omit its sprite in the tested build. Playback
speed is independent of game speed. `--speed` accepts 1, 10 or 40; graphical testing uses 10×.
Raw captures use roughly 1.4 GB for this longer run; generated media is ignored by Git.
The local [default-run MP4](out/recording/run.mp4) lasts 75.3 seconds at 12× playback and is about
6.7 MB. GIF, poster and image-hash metadata sit alongside it. The full `--record` workflow was
also verified on the shifted-pond run.

**Planning and evidence boundaries**

`PowerIsland` is an immutable Python declaration with stable placement addresses and explicit
water, steam and electric connections. It anchors an authored east-shore layout to **one fully
observed rectangular pond**. It does not solve arbitrary shoreline geometry or fluid routing.
Native preflight checks the proposed sites; native cursor checks run again at placement. The
layout is separate from the older belt-port factory model, which does not yet model fluid/power ports.

Resource procurement uses the existing advisor's runtime recipes and finite-stock bill.
Mineral routes use the observer's native receipts and Python validation. Construction-site
walks use native paths and the live executor's swept collision checks. The player walks normally;
placement transfers an existing stack to the cursor, builds once, returns the remainder and
verifies the exact inventory delta. Inventory transfers into machines still use paired API debits
and credits, with reach checks; they do not yet emulate dragging stacks through the game GUI.

The live executor has optional state/action hooks whose default is empty. This experiment supplies
the hooks and cursor adapter in its disposable scenario, reusing the existing command ledger,
pause boundaries and recorder. The earlier headless and player-capture experiments keep their defaults.

The final verifier checks native build/craft events, inventory and deposit conservation, matching
power-network IDs, lab energy, measured electric load/generation, consumed science and actual
research state. Finite steam reserves are **not** imported as a continuous power supply. The
boiler's three-coal allocation is exhausted by the end; residual steam remains in the engine.
The advisor now requests ongoing ore delivery. **Sustained 10 red science/min is still incomplete**:
continuous fuel, automated mining, smelting, transport and science assembly are next.

The separate [coal-supply continuation](../11_coal_supply/README.md) now reuses this opening
in the same world and adds native tree harvesting plus a measured self-fueling coal module.
Its coal output still needs routing to the power island and smelters. Optional runner,
observer-profile and cursor-registry hooks keep this experiment's defaults unchanged.

```sh
python3 -m unittest discover -s 10_powered_lab/tests -v
```

See [integration evidence](integration/README.md) and the shared
[execution/inspection backlog](../08_live_executor/TODO.md).

Eight tests check actual event/cost/research evidence, reject broken power and conservation,
and compare physical default/shifted layouts. All 166 tests across experiments 05–10 pass.
