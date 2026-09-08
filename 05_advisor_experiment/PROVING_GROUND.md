Configurable flat proving ground

The new scenario prepares a simple Nauvis environment for testing complete opening instructions:
flat buildable land, four rectangular mineral deposits in a row, a rectangular water source,
and four trees for wood. Terrain extends as chunks are explored. Each ore tile and the starter
inventory are finite; no script replenishes resources, completes research, supplies power, or
places production equipment during ordinary play.

This is a separate scenario under `integration/proving-ground/`. It does not change the normal
observer mod or the existing production, survey, and route scenarios.

**Build and customize**

From the repository root:

```sh
python3 05_advisor_experiment/proving_ground.py \
  --out 05_advisor_experiment/out/scenarios/advisor-proving-ground
```

The output is a standalone scenario directory. Copy it into `scenarios/` in a separate Factorio
profile, enable base plus the packaged observer, and select the scenario when starting a game.
The builder itself does not install or launch it. See [OBSERVER.md](OBSERVER.md) for observer
packaging and profile isolation. The initial instruction is to produce 10 red science/minute;
the complete player guidance loop is still under construction.

To change the layout, copy [config.json](integration/proving-ground/config.json), edit its
rectangles, and pass `--config my-ground.json --out PATH` with a fresh output directory.
Positions are integer tile coordinates; resource entities sit at tile centers. Width and height
give exact tile counts. A rectangle may cross chunk boundaries.

| Default region | Top-left tile | Size / contents |
| --- | --- | --- |
| Water | `(-48, -24)` | 8×8 water tiles |
| Coal | `(-24, -24)` | 8×8, 1,000 per tile |
| Iron ore | `(-8, -24)` | 8×8, 1,000 per tile |
| Copper ore | `(8, -24)` | 8×8, 1,000 per tile |
| Stone | `(24, -24)` | 8×8, 1,000 per tile |
| Wood | `(40, -24)` through `(49, -24)` | Four trees, spaced three tiles apart |
| Player | `(0, 0)` | 8 iron plates, 1 wood, 1 furnace, 1 burner drill |

The area south of the resource row is available for an anchored factory and future bus.
The scenario omits the crash site, weapons, and naturally generated enemies/obstacles. Inventory
is an explicit controlled opening fixture, not a claim to reproduce every freeplay starting item.
Each joining player receives that inventory once; multiplayer behavior has not been engine tested.

Map dimensions are configured as zero, Factorio's convention for the normal maximum extent.
The installed 2.1.16 engine reports this as **2,000,000 × 2,000,000 tiles**, generated on demand.
“Infinite flat space” here means that standard practical extent, not an actually infinite array.
High terrain elevation prevents natural water even in neighboring chunks still being prepared;
the chunk handler paints grass and the declared water/resource rectangles. A persistent chunk
ledger prevents repeated events or re-entry from replenishing ore.

Moving a deposit means editing the configuration and building a new scenario. It does not move
resources under an existing factory. Terrain edits, chunk deletion, or save migration are not
supported update operations for this fixture.

**Engine check**

```sh
python3 05_advisor_experiment/tools/run_ground_smoke.py \
  --factorio /path/to/factorio --out /tmp/advisor-ground-run-01
```

The runner builds an isolated profile and checks all resource counts and amounts, water/tree
counts, finite inventory, absence of researched technologies, distant flat terrain at x=1,024,
and lack of resource replenishment when a chunk is processed again. It writes a normal survey,
`ground.svg`, and `verification.json` under `--out/engine/`. The depletion check changes one ore
tile by three units only in the test harness; it is not a hand-mining execution test.

The same runner accepts `--config`, including a layout with the iron rectangle moved to `(29,29)`
across four chunk boundaries. [Captured evidence](integration/README.md) records the checked
layouts. The existing [survey](SURVEY.md) and [route](ROUTES.md) tools can be used in this world.
An additional boundary case preserves a tree whose collision box reaches into a neighboring
chunk: terrain initialization clears natural entities by their owning center position.
The [declarative module experiment](../06_declarative_factory/README.md) also runs its physical
placement/update test on this ground, with its extra test supplies explicitly separated.

The [finite opening executor](../07_bootstrap_executor/README.md) now uses the actual starter
inventory on this ground: walk/mine four coal and 50 ore, pay for a declared furnace from the
starting stock, smelt and collect 50 plates, and observe steam power unlocked. Moving the iron
patch to `(12,-8)` produces new routes and a new furnace site with the same costs. Placement
uses a costed test adapter; the interactive player cursor path is not yet exercised.

**FLE research**

Inspected Factorio Learning Environment at commit
[`e2a829d22a635a9a111d21bf5523e09e903ae145`](https://github.com/JackHopkins/factorio-learning-environment/tree/e2a829d22a635a9a111d21bf5523e09e903ae145):

- Its [cluster runner](https://github.com/JackHopkins/factorio-learning-environment/blob/e2a829d22a635a9a111d21bf5523e09e903ae145/fle/cluster/run_envs.py)
  defaults to `default_lab_scenario`, whose directory includes a saved blueprint/map archive.
- Its [ore creation script](https://github.com/JackHopkins/factorio-learning-environment/blob/e2a829d22a635a9a111d21bf5523e09e903ae145/data/scripts/init/create_ore.lua)
  creates a square resource grid with a specified amount on each tile.
- Its [map settings](https://github.com/JackHopkins/factorio-learning-environment/blob/e2a829d22a635a9a111d21bf5523e09e903ae145/fle/cluster/config/map-gen-settings.json)
  document the zero-width/height convention. Its
  [resource reset helper](https://github.com/JackHopkins/factorio-learning-environment/blob/e2a829d22a635a9a111d21bf5523e09e903ae145/fle/env/tools/admin/regenerate_resources/server.lua)
  refills resources and resets force state; that behavior is unsuitable for measuring a finite opening.

This confirms useful mechanisms and the lab-scenario direction. The exact layout embedded in
FLE's saved archive was not reconstructed or run. Our scenario is an independent implementation
against installed Factorio 2.1.16; FLE is not installed or added as a dependency.

FLE's [`GameControl.set_speed`](https://github.com/JackHopkins/factorio-learning-environment/blob/e2a829d22a635a9a111d21bf5523e09e903ae145/fle/env/instance.py)
sets `game.speed` via RCON, allowing accelerated pacing such as 10× or 40× when the CPU can
keep up. Our `--benchmark` runs are already unthrottled. Shared runners now record update time,
simulation duration and startup overhead separately in `performance.json`; see the
[measured opening timings](../07_bootstrap_executor/integration/README.md).
