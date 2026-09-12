Iron production evidence

The fixtures retain the verified Factorio 2.1.17 run from
`/private/tmp/blueprint-gen-iron-build-07`. After two idle startup minutes, five consecutive
minutes each collected 30 iron plates. Ore depletion and furnace production both
totaled 150. The connected factory mined 75 coal, burned 50 and gained 25 coal in its buffers.

`iron-windows.json` and `iron-final-observation.json` retain the physical measurements.
`iron-baseline.json` establishes empty new-module buffers. The action, construction and
native crafting records establish payment for all 62 new entities. The previous boiler-feed
verification and endpoint designs retain the source module context. Observer display names
were removed; quantities and identities are unchanged. The JSON fixtures use compact formatting.

Tests reject broken ore/fuel/power connections, inconsistent extraction or production,
missing burner meters, lost coal, uncollected plates, manual intervention, unpaid builds and
missing native events. A revision-boundary test covers the prior Logistics command ending
at the same paused tick as iron preparation. Startup receipts retain both full minutes.
