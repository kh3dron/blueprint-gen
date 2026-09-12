Player attachment and native game recordings

This separate experiment connects a graphical Factorio client to the
[persistent executor](../08_live_executor/README.md), attaches its player to the existing
starter character, and optionally records native images during the finite opening. It reuses the advisor,
surveyed paths and action driver. The headless experiment remains a comparison baseline.

**Result**

On Factorio **2.1.17**, attaching the player resolves the lab attribution gap: the native
character crafting queue produces one paid lab, the force production counter reaches one,
and `automation-science-pack` unlocks naturally. A fresh headless run on the **same version**
still produces the lab without credit. Research and production statistics are never granted
or patched. This establishes a working attachment path; the internal engine cause remains unknown.

Both runs mine six coal, 50 iron ore and 15 copper ore. Final inventory is 22 iron plates,
one wood, one burner drill and one lab; a built furnace completed 65 crafts. The attached
run records 40 native `on_player_crafted_item` events whose player IDs, times and outputs match
the jobs. Attachment preserves the character ID, position and starter inventory; cheat mode
stays off. The joining player's extra character is removed without transferring items.

The advisor now says **prepare a powered lab**. The lab is still in inventory. Power construction
and sustained red-science production remain unimplemented; goal completion is false.

**Run and record**

From the repository root, with Factorio and Pillow installed:

```sh
python3 09_player_capture/run_player.py \
  --factorio /path/to/factorio \
  --out /tmp/advisor-player-new \
  --speed 10 --record
```

The output directory must be new. The runner opens a 960×640 game window, connects to its own
server bound to `127.0.0.1`, executes the opening and closes both owned processes. Leave the
experimental window idle while the agent operates; manual input can invalidate observations.
The execution environment must permit GUI and local socket access.

Server and client have separate temporary configs, mods and saves inside the output folder.
The runner does not read or copy existing local profiles, saves or authentication files.
Steam builds still initialize Steam and may supply the account's display name. A local
`steam_appid.txt` prevents Steam relaunch from discarding the temporary config; blueprint-library
cloud synchronization is disabled for the client. Logs remain local, outside checked-in evidence.

`--speed` accepts 1, 10 or 40. Native capture has been verified at **10×**. The run advances
23,378 ticks (389.63 simulated seconds) in 53.61 wall seconds including conversion, startup,
planning and PNG capture, about 7.27× overall. Encoding is additional. Headless comparisons
can use 40× without the graphical capture cost.

Default runs retain text evidence without PNGs or periodic native traces. `--record` enables
screenshots and GIF/MP4 encoding. The player stays connected for native crafting attribution
even when recording is disabled. Rerender a previously recorded run without restarting Factorio:

```sh
python3 09_player_capture/render_native.py /tmp/advisor-player-new \
  --out /tmp/advisor-native-video-new --playback 12 --fps 12
```

Outputs are `run.mp4` (when ffmpeg is installed), `run.gif`, `poster.png` and `recording.json`.
MP4 is 1280×720; GIF is 960×540. Default playback lasts roughly 33.5 seconds, including a final
one-second hold. The video shows actual resource patches and the working furnace alongside
the current subgoal/action, production counters, inventory and research progress.

The tested engine's screenshots omit the player sprite. An explicitly labeled **Agent position
(observed)** ring marks the camera center, which is the character's observed position. Terrain
and machines are Factorio renders. Capture uses daylight, alt mode, and no game GUI/clouds/fog.
It does not screen-record the desktop or other applications.

With `--record`, images are requested every 60 game ticks, at action starts and at paused boundaries.
`native-trace.jsonl` pairs each request with its tick, action and state. Video frames hold
the latest captured image and that image's own state together, without interpolation. Metadata
records the trace hash, every image hash and the source-frame mapping. Missing or unreadable
PNGs refuse export, including frame loss when a client cannot keep up at higher speeds.
Raw PNGs consume about **0.6 GB per recorded opening**. They are needed for rerendering and
image-hash verification; after removal, native footage requires another recorded game run.
Generated media is ignored by Git. Compact evidence is in [integration/fixtures](integration/fixtures).

**Implementation boundaries**

The Lua extension wraps the live controller. Crafting still uses `LuaEntity.begin_crafting`;
the changed condition is that its character has a connected `LuaPlayer`. Furnace placement
still uses the paid test adapter, and transfers use paired inventory operations.

A separate RCON variant puts its completion marker in the **same scheduled Lua command** as
the request. The previous two-command marker could overtake the result with a connected peer.
Empty acknowledgments and fragmented responses are handled without retrying mutations. Native
route receipts for attached characters are read from client output; surveys still use server
output. These extensions leave headless defaults intact.

The separate [powered-lab experiment](../10_powered_lab/README.md) now implements native cursor
building and the first steam-powered lab research. Graphical reconnect/save-resume and sustained
science remain future work. See the shared [execution backlog](../08_live_executor/TODO.md), including
the requested recursive goal/subgoal planning stack viewer.

```sh
python3 -m unittest discover -s 09_player_capture/tests -v
```

Nine tests cover attribution, conservation, rejected missing/misattributed events, RCON reply
framing, incomplete image evidence and actual GIF export. See [integration notes](integration/README.md).
