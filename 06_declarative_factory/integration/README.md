Declarative module engine evidence

[control.lua](control.lua) is a test-only controller staged by `../run_smoke.py` into a new
Factorio profile. It imports the same flat-terrain implementation used by
`05_advisor_experiment/proving_ground.py`; the production observer remains unchanged.

[fixtures/verification.json](fixtures/verification.json) contains actual Factorio **2.1.16**
observations with base and observer **0.3.0**, captured on 2026-09-07:

- `before`: baseline manifest hash, tick, actual configurations and unit numbers for the first
  module, reserved feeds, and its connection.
- `after`: the expanded design and all actual configurations/unit numbers. Every baseline
  entity is preserved; only the second module and its connection are added.
- `drift`: a later observation of the baseline addresses after the first assembler's recipe
  was deliberately changed. Python reconciliation rejects extension from this state.
- Counts: 28 entities initially created; 18 added; zero on repeat. Both modules produced 18
  gears; 96 plates were supplied to each feed column. Research, obstacle, and drift checks passed.

JSON was reformatted for readability; observed values were not authored. The fixture hashes bind
to the manifests compiled by the checked-in demo and asset. The engine validates actual entity
configurations and IDs rather than merely returning a successful process exit.

This fixture grants all research, test electricity, construction entities, and finite input
plates. Its purpose is to test physical module connections and additive update semantics. It
does not validate a starter-inventory build, manual placement/reach, infinite input supply, or
the declared maximum throughput. Reproduce with the command in [README.md](../README.md), using
a new output directory; inspect new evidence before intentionally replacing this capture.
