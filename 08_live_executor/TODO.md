Execution and inspection backlog

- **Hierarchical planning stack viewer — requested by the user.** Treat the plan like a running
  program: a goal such as “build a rocket” expands into nested subgoals, down to “walk to position
  X” and “place item Y.” Show the current stack, each frame's inputs and completion conditions,
  and the source of its instructions. Distinguish planned, running, observed-complete, waiting
  and failed nodes. Link a selected frame to the matching game-time/video position, observation,
  declarative module address and inventory delta. Include step-through, pause and breakpoints.
  Current milestone/command IDs are useful trace data, but are not this recursive plan model.
- Completed in [09_player_capture](../09_player_capture/README.md): attach a connected player
  without changing the starter inventory; native lab crafting receives force credit and unlocks
  its trigger. A headless control on the same engine version still lacks that credit.
- Completed in [09_player_capture](../09_player_capture/README.md): native graphical frames,
  GIF/MP4 export, observed action/progress overlays and source hashes. Next capture work: reduce
  raw PNG storage, test faster capture, add camera presets and verify reconnect behavior.
- Completed in [10_powered_lab](../10_powered_lab/README.md): native cursor placement for the
  furnace and steam power island; blocked/unpaid/out-of-reach refusals and repeat lab deployment;
  ten paid red science packs consumed by a real lab to unlock Automation.
- Extend the powered-lab result to continuous fuel, automated extraction and smelting, ingredient
  routing and science assembly. Keep finite handcrafting separate from the measured 10/min goal.
- Add native tree harvesting to the procurement actions. The powered-lab opening spends the
  starter wood; further poles need wood, while current native gather routes support minerals only.
- Replace the authored rectangular-pond power layout with a general shoreline/pipe/pole planner;
  connect its water, steam and electric contracts to the typed factory/bus model.
- Resume from an arbitrary saved checkpoint in a fresh Python process: restore command IDs,
  outstanding RPC outcomes, plan position and observed deployment state. Test lost responses,
  interrupted transfers, crafting queues, and crashes during save. Current restart coverage
  resumes the server within one surviving driver process.
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
