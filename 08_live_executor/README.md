Persistent execution and run recordings

This separate experiment continues the advisor's opening in one running Factorio world. It
uses a local RCON connection, pauses at action boundaries, imports fresh observations, and
executes the next finite construction bill. It saves after steam power, restarts the server,
and continues from the saved world with the same character, furnace, inventory and command ledger.
The earlier [replay experiment](../07_bootstrap_executor/README.md) remains separate.

The run mines six coal, 50 iron ore and 15 copper ore, smelts 65 plates in the same paid furnace,
and natively handcrafts the ingredients and one lab. Steam power and electronics unlock. Final
inventory is **22 iron plates, one wood, one burner drill and one lab**; the furnace remains built.
The 10-red-science/min goal is still incomplete.

The lab exposes a real engine integration gap: `begin_crafting` on the standalone character
consumes ingredients, advances its crafting queue and produces the lab in inventory, but the
force's lab production count remains zero and its research trigger stays locked. The controller
records that discrepancy after a bounded observation interval and stops. It neither grants the
research nor keeps making labs. The separate [player attachment experiment](../09_player_capture/README.md)
now resolves this gap: on Factorio 2.1.17, the same queue with an attached player receives force
credit and unlocks the science recipe. A same-version headless control still shows the discrepancy.

**Run and record**

From the repository root, with Factorio 2.1.16 installed:

```sh
python3 08_live_executor/run_session.py \
  --factorio /path/to/factorio \
  --out /tmp/advisor-live-run-new \
  --speed 40 --record
```

The output directory must be new. The server and RCON ports bind to `127.0.0.1`; no public or LAN
server is advertised. Profiles, mods, saves, logs and recordings stay in that directory. The
runner stops its own server on completion or error. Local socket access must be permitted by
the execution environment. The existing Factorio profile is not used.

Supported game speeds are 1×, 10× and 40×. Unlike the unthrottled `--benchmark` runner, this is a
paced server using `game.speed`, the same mechanism FLE exposes. The default recorded run advances
399.233 simulated seconds in 13.144 wall seconds, including map conversion, two server starts,
planning pauses and verification: about 30.4× overall. Rendering is measured separately.

Execution uses the Python standard library. `--record` additionally requires Pillow; MP4 output
uses `ffmpeg` when it is available. Without ffmpeg the GIF and poster still work. You can render
or rerender any recorded run independently:

```sh
python3 08_live_executor/render_trace.py /tmp/advisor-live-run-new \
  --out /tmp/advisor-video-new --playback 12 --fps 16

# No Factorio process is needed to render the checked-in actual run:
python3 08_live_executor/render_trace.py 08_live_executor/integration/fixtures \
  --out /tmp/advisor-fixture-video-new
```

The renderer produces `run.gif`, `run.mp4` when ffmpeg is available, `poster.png` and recording
metadata with source hashes. At the defaults, the sample is about 34 seconds long, including a
one-second final hold. Playback speed is independent of the speed used to execute the game.

**What the recording shows**

The recording is a **schematic replay of actual observed game state**, rather than native game
footage. It shows the resource row, the character and its recent path, the real furnace position,
crafting activity and craft count, inventory, force production counters, current subgoal/action,
game time, and observed research progress. The lab's missing credit is visible alongside its
presence in inventory. Positions and counts are held from recorded samples, never interpolated
or filled in from a predicted plan. The fixed camera currently frames the mining row; terrain
outside that view is omitted.

Frames are recorded every 30 game ticks and at action/observation boundaries, in `live-trace.jsonl`.
`live-world.json` describes the configured proving ground. The tiny player marker and furnace
symbol represent observed entities; there are no game sprites or fake completed machines.
Native game footage is now available through [09_player_capture](../09_player_capture/README.md).
The hierarchical planning stack viewer remains in [TODO.md](TODO.md).

**Continuation and action semantics**

`actions.json` records each request, its observation tick/revision, stable command ID, milestone,
label, measured ticks and outcome. Repeating the same command ID and payload returns its stored
outcome, including after a save/restart. Reusing an ID with another payload is refused. A new
command with an old tick/revision is refused. The engine verifies inventory/reach/collision
preconditions again, and pauses on action completion or failure. Unknown RPC outcomes are not
automatically retried with new IDs.

Mineral approaches use the read-only observer's native path receipts and Python validation. The
executor follows the corresponding native path in the same world. Returning to the furnace uses
an additional bounded native path with swept character collision checking. A shifted-copper
test exercises those return paths. Mining uses timed `mining_state`; handcrafting uses the native
crafting queue; smelting advances normal furnace ticks. Transfers debit and credit real inventories.
Furnace placement still uses the [costed test adapter](../07_bootstrap_executor/integration/adapter.lua),
not a connected player's cursor interface.

This is a controlled proving ground with one managed furnace and no concurrent players or
external scripts editing the world. Revisions track executor operations, not arbitrary live-world
changes; moving obstacles and partially failed operations need stronger recovery before this
becomes a general automation API. The driver automatically tests one save/restart boundary;
a fresh Python process cannot yet resume an arbitrary saved plan through the CLI. The game saves
and command ledger are real, and the remaining driver recovery work is explicit in the backlog.

Artifact directories include `observations/`, the three advisor bills, native route receipts,
the declarative furnace design, action/transfer ledgers, restart evidence, milestone outcomes,
performance, final verification and next-action reports. No finite inventory or batch production
is turned into a continuous supply rate or a completed science goal.

```sh
python3 -m unittest discover -s 08_live_executor/tests -v
```

There are 14 tests covering the recorded run, conservation, restart identity, refusal boundaries,
the uncredited lab trigger, RCON packet fragmentation, trace chronology, playback sampling and
actual GIF export. See [integration evidence](integration/README.md).
