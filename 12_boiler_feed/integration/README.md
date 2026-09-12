Boiler-feed evidence

The fixtures retain the verified Factorio 2.1.17 run from
`/private/tmp/blueprint-gen-feed-07`. Five consecutive idle minutes each supplied 60 kW
to the lab and delivered one new coal to the boiler. The mine produced 75 coal, combined
fuel buffers gained 56 coal, and the lab consumed twenty paid packs to complete Logistics.
Generation after connection was 18 MJ; the original fuel and steam reserve was about 6 MJ.

`feed-final-observation.json`, `feed-windows.json` and `feed-baseline.json` contain the
physical observations. `actions.json`, `player-crafts.jsonl` and `feed-reconciliation.json`
establish paid construction, native crafting and refusal of direction drift. The coal
checkpoint, design, material bill and verification summaries retain the earlier milestone.
Observer display names have been removed. Gameplay quantities are preserved.

Fourteen regression tests replay this evidence and reject broken endpoints, unmatched
depletion, idle power, manual refueling, inconsistent fuel counts, draining buffers and
missing native events or inventory. This establishes a finite research load supplied by
automatic coal delivery. It does not establish continuous science assembly.

Native PNGs from the development attempts were removed after evidence retention.
Their compressed text traces and game saves remain in the temporary run directories.
New runs capture images only when `--record` is selected.
