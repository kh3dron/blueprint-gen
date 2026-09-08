Native player/capture evidence — 2026-09-07

Fixtures come from `/tmp/blueprint-gen-player-06`, an actual Factorio **2.1.17** run with
observer **0.3.0**, a client attached to character **#12**, and game speed **10×**. Resources
and starting inventory are finite. Furnace **#14** is at **(-9, -14)**; the joining player's
temporary character consumed the intervening entity ID.

| Evidence | What it checks |
| --- | --- |
| `attachment.json` | Same character, position and inventory before/after; cheat mode off |
| `initial-observation.json`, `final-observation.json` | Raw capture-bound inventory, research, machines and production |
| `actions.json`, `milestones.json` | 28 commands; all three trigger technologies unlock |
| `player-crafts.jsonl` | 40 native player crafting events; lab at tick 23,353 |
| `verification.json` | Conservation, one furnace with 65 crafts, one credited lab |
| `next-action.json` | Prepare a powered lab; no further lab crafting requested |
| `performance.json` | 23,378 ticks, about 53.61 wall seconds including PNG capture, excluding encoding |
| `recording-summary.json` | Timing/coverage summary; image hashes remain with the local recording |
| `headless-2.1.17-verification.json` | Same-version control: same materials, zero lab credit |

The control ran at `/tmp/blueprint-gen-headless-2-1-17` with the default live controller and
its save/restart check. `/tmp/blueprint-gen-player-05` independently reached the same successful
attached-player inventory and research outcome.

`game.take_screenshot` renders on the client. The server writes the request-tick/state trace;
Python waits for complete PNGs at boundaries. Export requires every requested image and hashes
each source. The player-position ring and progress panel are renderer annotations.

Raw profiles, logs, PNGs and encoded video stay local because they are large and Steam logs
can contain account display information. Local generated media is available under
`09_player_capture/out/recording/`; the public runner recreates it in a fresh directory.

Coverage is limited to flat proving ground, with no graphical restart/reconnect test. Furnace
placement still uses the paid entity-creation adapter. The result does not establish a powered
lab or continuous science output.
