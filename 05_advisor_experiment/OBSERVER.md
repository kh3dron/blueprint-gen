Factorio observer and importer

The advisor can now read a bounded area from Factorio and measure its machines' production.
The observer exports resolved runtime rules, actual research, player main inventory, and machine
IDs, positions, recipes, status, power buffers, network IDs, and modifiers. It reads the factory;
it changes only its own bookkeeping and writes JSON files. It does not execute advice.

The engine integration was tested on **Factorio 2.1.16, base plus observer 0.1.0, 0.2.0, and 0.3.0**. The importer
accepts the 2.1 series with matching runtime catalogs, but other patches have not been engine
validated. Space Age, other gameplay mods, non-normal quality, modules/beacons/bonuses, and
multiple electric networks are rejected. Nauvis opening recipes are the supported scope.

Version 0.2.0 added a separate [world survey command and mining-target CLI](SURVEY.md).
Version 0.3.0 adds [native walking approaches and exact hand-mining instructions](ROUTES.md)
through `/advisor-route X Y COUNT`. Earlier captures remain supported with their original
hashes and profiles. Route requests do not move or mine with the character.

**Try a real capture without installing anything**

From the repository root, with Python 3.10+:

```sh
mkdir -p 05_advisor_experiment/out
python3 05_advisor_experiment/import_game.py convert \
  05_advisor_experiment/integration/fixtures/stable.json \
  --out 05_advisor_experiment/out/snapshot.json \
  --rules-out 05_advisor_experiment/out/runtime-rules.json
python3 05_advisor_experiment/advisor.py \
  --rules 05_advisor_experiment/out/runtime-rules.json \
  next 05_advisor_experiment/out/snapshot.json
```

The result is an `observe` instruction listing missing facts. That is expected: this fixture
measured 12 red science packs in a minute, but the snapshot alone does not establish sustained
input delivery, routing, or available generation. Its materials were preloaded finite stocks.

**Build and use the mod**

```sh
python3 05_advisor_experiment/tools/build_observer.py
```

This creates `out/mods/blueprint-gen-observer_0.3.0/` inside the experiment. It does not install
anything. Copy that generated directory into the mods directory of a separate Factorio profile,
enable base and the observer, and load a copy of a Nauvis save. The source `observer/` directory
alone is incomplete: packaging generates the catalog. A build refuses to reuse an existing mod
directory; pass a different `--out` when making another build. Test scenarios are excluded from
the normal package.

In the game console, as a player:

```text
/advisor-export 32
/advisor-observe 32
```

`export` captures immediately. `observe` measures 60 **simulated** seconds and exports at the
end. The integer radius defaults to 32 tiles, with a range of 1–128. The square area stays fixed
at the player's starting location and is restricted to their force and surface. The observer
allows at most 256 machines/ghosts in the query; reduce the radius for larger factories. Running
`observe` again replaces that player's pending window. No monitoring runs between windows.

Find the announced file under Factorio's user data directory:
`script-output/blueprint-gen-observer/player-N-tick-T.json`. In multiplayer, player commands
address the requesting client's output. The engine smoke uses a headless scope and its isolated
write-data directory. Multiplayer delivery has not been separately exercised.

Avoid construction, recipe/settings changes, and research completion during a measurement.
Configuration changes invalidate the entire interval, including a recipe changed back to its
original setting. Build/mine/rotate/research/tile events and closing a GUI conservatively
invalidate running windows globally, even outside the area. Per-tick machine signatures also
detect changes without such events. Saving/loading preserves observer state; missed ticks,
counter resets, or changed configuration prevent that interval from proving completion.

**Review what the game export cannot establish**

Copy the raw capture into your working directory as `capture.json`, then generate its review:

```sh
python3 05_advisor_experiment/import_game.py review capture.json --out review.json
```

Edit the review's goals and fill only checked facts:

| Review field | What to establish |
| --- | --- |
| `goals_per_min` | The requested output rates; defaults to 10 red science/min |
| `require_lab` | Whether a usable lab is part of this milestone |
| `supplies_per_s` | Sustained net input delivery across the scope boundary, excluding production already represented by captured machines and upstream extraction costs |
| `available_power_kw` | Generation available to the one modeled network after outside loads; a machine energy buffer is not generation |
| `machines.ID.connected` | Ingredients and fuel can reach that machine within the modeled material pool |
| `machines.ID.output_open` | Products have an available destination; inspect handling for every coproduct |
| `inventory` | Only for captures lacking player inventory, such as the headless test; finite accessible stock, never a rate |

`null` means unknown. `{}` for supply means confirmed zero, and `false` for a machine flag
means a confirmed fault. Unknowns remain explicit `observation_gaps`; conservative placeholders
cannot establish completion or justify a build recommendation. Direct `full_output` evidence
overrides an operator's `output_open: true`. Inactive machines and fuel/power failures also limit
capacity. The export includes output inventories for inspection but does not turn them into
new production or supply. Only the player's main inventory is imported; unmodeled items and
quality are omitted with notes. Chests, machine input buffers, and cursor stacks are not counted
as construction inventory.

Each review is bound to the full capture's SHA-256. A review from another export is rejected.
Do not copy the hash into an old review to bypass this check. After relevant changes, export
again and check the new facts. The external CLI reasons about the captured tick; it cannot
detect edits that happened after the export or know the game's current tick.

```sh
python3 05_advisor_experiment/import_game.py convert capture.json --review review.json \
  --out snapshot.json --rules-out runtime-rules.json
python3 05_advisor_experiment/advisor.py --rules runtime-rules.json next snapshot.json
python3 05_advisor_experiment/advisor.py --rules runtime-rules.json analyze snapshot.json
```

The runtime ruleset gets a new identity/hash. Its recipe times, amounts, unlocks, machine speeds,
energy use, fuel value, and technology costs come from the game's resolved prototypes. The
catalog and recipe/machine selection policy remain reviewed subsets from this experiment.
The original `rules/nauvis.json` and its nine authored examples remain pinned to **2.1.14**.
Use the emitted `--rules` file with imported snapshots; changing version labels is insufficient.

**Production evidence**

The observer samples each machine's `products_finished` every tick during the window and
multiplies positive craft deltas by deterministic recipe outputs. The engine test verifies the
important distinction: 60 cable crafts produce 120 items. Player crafting, inventory transfers,
old output stocks, and whole-force production totals do not contribute to this measurement.
Whole-force item production counters are exported separately for trigger guidance; only actual
researched technology flags establish a completed unlock.

A valid interval must have continuous ticks, unchanged configuration and generation, normal
quality and no unsupported modifiers, non-resetting counters, and a final tick matching the
capture. The importer discards an invalid window with an explanation. Goal verification still
requires sufficient duration, measured rate, flow feasibility, and all requested lab/power
conditions. A measured minute establishes that minute's average; it does not prove unlimited
future supply. Unconfigured assemblers and their ghosts without recipe identity produce an
observation gap. Empty stone furnaces retain their built identity with a null recipe and zero
modeled activity, so later finite construction bills can reuse the station. Furnace ghosts
remain unbuilt and cannot satisfy those bills.

**Run the engine check**

Supply the path to your local executable and a new output directory:

```sh
python3 05_advisor_experiment/tools/run_observer_smoke.py \
  --factorio /path/to/factorio --out /tmp/advisor-observer-run-01
```

On macOS Steam, the executable is typically
`~/Library/Application Support/Steam/steamapps/common/Factorio/factorio.app/Contents/MacOS/factorio`.
Quote paths with spaces. The runner finds `data/core` beside the executable on macOS/Linux
installation layouts. It places config, mod list, saves, logs, and exports beneath `--out`;
it does not use the player's live mods, settings, or saves. No GUI or server is started.

The runner stages a test-only scenario, converts it to a save, and runs 3,800 benchmark ticks.
The scenario creates two red-science assemblers, cable/gears assemblers, a lab, test electricity,
and finite ingredients. The first window is stable; the second contains a scripted recipe
change. Assertions require actual exports, correct measured output and runtime units, recipe
change rejection, blocked-output handling, and conservative imported advice. Missing exports
fail even if Factorio exits successfully. `verification.json` contains a compact report;
`snapshot.json` and `runtime-rules.json` can be opened with the advisor. See the checked-in
[fixtures and provenance](integration/README.md).

```sh
python3 -m unittest discover -s 05_advisor_experiment/tests -v
python3 05_advisor_experiment/bench.py
```

Python tests run without Factorio. If `luajit` or `lua` is present, they also run eight pure
window fault cases; otherwise that one harness test is explicitly skipped. These checks and
this production smoke do not validate a finite-inventory construction sequence, belts,
inserters, fluid routing, power infrastructure, or the full opening. A separate
[route harness](ROUTES.md) tests actual walking and finite hand-mining in one controlled scene.
Polling cost at the 256 entity limit has not been profiled.

API references used: the installed 2.1.16 `doc-html/runtime-api.json`, with public counterparts
for [LuaEntity](https://lua-api.factorio.com/latest/classes/LuaEntity.html),
[LuaEntityPrototype](https://lua-api.factorio.com/latest/classes/LuaEntityPrototype.html),
[LuaTechnology](https://lua-api.factorio.com/latest/classes/LuaTechnology.html), and
[LuaHelpers](https://lua-api.factorio.com/latest/classes/LuaHelpers.html). Public `latest` may
describe a newer version; the local engine run is the evidence for this implementation.
