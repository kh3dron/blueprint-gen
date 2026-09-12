Execution and inspection backlog

- **Architecture priority:** extend [the constructor](../factory_constructor/README.md), where
  a production declaration generates the player program. The first method sizes iron supply
  from a requested rate, expands procurement, and emits inspectable nodes. Next add observed
  incremental deployment and recursive method/connection composition; do not make a standalone
  copper action sequence the next milestone.
- **Hierarchical planning stack viewer — requested by the user.** Treat the plan like a running
  program: a goal such as “build a rocket” expands into nested subgoals, down to “walk to position
  X” and “place item Y.” Show the current stack, each frame's inputs and completion conditions,
  and the source of its instructions. Distinguish planned, running, observed-complete, waiting
  and failed nodes. Link a selected frame to the matching game-time/video position, observation,
  declarative module address and inventory delta. Include step-through, pause and breakpoints.
  The constructor now supplies hierarchy, source, inputs, predicates and node statuses in
  `program.json` and `execution.json`; visual stepping and the debugger UI remain pending.
- Completed in [09_player_capture](../09_player_capture/README.md): attach a connected player
  without changing the starter inventory; native lab crafting receives force credit and unlocks
  its trigger. A headless control on the same engine version still lacks that credit.
- Completed in [09_player_capture](../09_player_capture/README.md): native graphical frames,
  GIF/MP4 export, observed action/progress overlays and source hashes. Development runs now
  capture PNGs only with `--record` and retain compact boundary traces by default. Next capture
  work: camera presets and faster optional footage export.
- Completed in [10_powered_lab](../10_powered_lab/README.md): native cursor placement for the
  furnace and steam power island; blocked/unpaid/out-of-reach refusals and repeat lab deployment;
  ten paid red science packs consumed by a real lab to unlock Automation.
- Extend the powered-lab result to automatic copper supply, ingredient
  routing and science assembly. Keep finite handcrafting separate from the measured 10/min goal.
- Completed in [11_coal_supply](../11_coal_supply/README.md): native tree harvesting for paid
  chest construction, self-fueling coal extraction, and measured net delivery to a chest over
  five idle minutes after startup. Next connect that output to boiler and ore-smelting modules;
  test that consumers remain supplied and fuel/input buffers do not simply drain.
- Generalize tree procurement beyond the current proving-ground scout waypoint and one-tree
  harvest method. Account for whole-tree surplus and validate clearing obstructed build sites.
- Completed in [12_boiler_feed](../12_boiler_feed/README.md): connect the coal chest to the
  boiler with paid belts and burner inserters; five idle minutes deliver new coal, maintain
  60 kW of useful lab demand and grow fuel buffers. Twenty finite science packs unlock Logistics.
- Completed in [13_iron_supply](../13_iron_supply/README.md): two ore drills feed coal-fueled
  furnaces with powered plate collection. Five idle minutes each collect 30 plates. Ore,
  plate and connected coal balances reconcile; fuel buffers gain 25 coal. Native construction
  uses clear standing points within observed build reach. Copper and science assembly remain.
- Attach measured module service evidence to typed ports: record item, observed output entity,
  consumer endpoint, test window, startup phase, finite reserves and available buffer capacity.
  Do not import chest production as boiler fuel delivery or ignore startup when claiming a rate.
- Replace the authored rectangular-pond power layout with a general shoreline/pipe/pole planner;
  connect its water, steam and electric contracts to the typed factory/bus model.
- Resume from an arbitrary saved checkpoint in a fresh Python process: restore command IDs,
  outstanding RPC outcomes, plan position and observed deployment state. Test lost responses,
  interrupted transfers, crafting queues, and crashes during save. The development checkpoint
  in `12_boiler_feed/` supports a sealed idle boundary with restored driver state; in-flight
  recovery remains unfinished. See [development loop](../DEVELOPMENT_LOOP.md).
- Recheck arbitrary world changes, moving obstacles, force/reach changes and machine drift
  between preflight and execution; refuse concurrent edits rather than trusting only the
  executor's revision counter.
- Continue through automated extraction/transport and a measured 10-red-science/min production
  window. Lab placement, steam generation and the first real lab research work in `10_powered_lab/`.
- Reuse observed fuel remaining in the burner and fuel inventory when budgeting subsequent jobs.
  The current conservative bill gathers an extra coal for each smelting batch.
- Extend the recorder's world schema and camera to larger factories, belts/inserters, power,
  buffers, and multiple modules. Support camera presets and a scrubber over raw observations.
- Test the return-to-furnace path on obstructed terrain and the mining controller on a tile
  that is exhausted by the requested quantity. Current physical runs use spacious flat ground
  and 1,000-unit resource tiles.
