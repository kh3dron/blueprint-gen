Declarative factory constructor

The product being developed is a Python constructor and a player tool that executes its
generated program. A working scripted factory is evidence for a reusable method, rather than
the project's acceptance criterion. New production work should extend this constructor.

```python
from factory_constructor import Automate, Executor
from factory_constructor.compiler import compile_goal
from factory_constructor.methods import IronPlateMethod
from factory_constructor.player import PlayerPort

goal = Automate("iron-plate", per_minute=20)
program = compile_goal(goal, observation, snapshot, rules, [IronPlateMethod()])
# program is ordinary JSON data; it can be inspected and serialized before execution.
Executor(program, PlayerPort(driver, program), output_directory).run()
```

The constructor expands recipe rates with the existing advisor, selects a registered output
method, chooses its instance count, generates surveyed geometry, derives the recursive finite
procurement bill, and emits ordered work with explicit completion predicates. The interpreter
walks the serialized program through a capability adapter. It does not import a scenario runner
or choose a factory layout. Python owns these decisions; the native bridge owns engine actions
and observations.

[Engine evidence](integration/README.md): 10/min and 20/min declarations generated one and two
lines, then measured 15/min and 30/min for five minutes through the same interpreter. The larger
case also executed its generated procurement bill. Fresh-process checkpoint tests also repeat a
15/min service with zero construction and extend it to 30/min with 16 paid additions.

The 10 science/min declaration also passes through this compiler and interpreter. Run
`/tmp/constructor-science-12` retained 60 entities and built 158 through paid native placement.
It stabilized after eight minutes, then produced and collected 12 packs/min for five consecutive
minutes. Connected coal buffers gained 59 coal. Execution from prepared inventory took
284.721 seconds and captured zero PNGs. A fresh native process restored the completed checkpoint's
exact world and ledger without advancing simulation. All 90 constructor tests pass.

`program.py` defines the declaration, hierarchy, dependencies and interpreter. `compiler.py`
owns requirement expansion and method selection. `methods.py` contains reusable construction
knowledge. `player.py` maps capabilities to the tested native player operations. `legacy.py`
contains imports from the earlier experiments. The old declarative `Asset` validator checks
geometry; its profile-specific manifest and belt-only ports are not presented as live deployment
state. This first method collects plates into chests and declares that boundary explicitly.

Each executable node names its parent, dependencies, source method, operation, inputs and
completion predicate. `execution.json` records the current stack, node states and action receipt
IDs. A successful command still needs its completion observation. The goal finishes only after
the final service check passes. Failed predicates stop dependent work and preserve the failed
stack. This supplies the data model for the requested debugger/viewer; the UI remains pending.

**Current executable scope**

The iron method accepts a goal up to 30 plates/min on the fully surveyed rectangular ore patch,
with the established coal chest and steam network as explicit prerequisites. It uses the
minimum per-line collection measured in the connected iron fixture (15/min), capped by the
runtime furnace capacity. It checks the engine profile and resolved mechanics against that
evidence. This is a sizing estimate; every new deployment is measured again.

A 10/min declaration selects one line; 20/min selects two. Placements, transport, poles,
construction items and raw procurement all change with that choice. Inventory offsets finite
procurement and never counts as sustained production capacity. The player performs paid native
builds, verifies retained entities without spending again, waits through startup, and measures
five consecutive minutes. The verifier reconciles ore depletion, native smelting, collected
plates, every connected burner and the combined coal stocks.

Verified deployments preserve entity identities and configurations. A fresh declaration refreshes
that record against current observations, retains sufficient capacity, and adds the deficit.
The player checks retained entities before each capability, stopping drift before paid work.

The science method accepts a verified two-output iron checkpoint. `production_graph.py`
backchains science through gears and copper, shares available iron capacity, and derives machine
counts from runtime recipes. `science_layout.py` generates copper mining/smelting, gear and science
assembly, belt routes, and poles connected to the existing steam network. Its added coal drill
feeds the original collection route and receives automatic fuel from the shared coal chest.
The serialized hierarchy identifies each production service and its placements. Finite
construction procurement is separate from sustained production and is paid in full.

This is bounded construction knowledge: the current layout recognizes the surveyed opening,
supports at most 12 science/min, and uses one copper line and one gear assembler. Arbitrary terrain,
new coal/power bootstrap, and migration of an existing science deployment remain unsupported.
Unknown methods or unsupported boundaries produce a blocked program before player work.

**Run**

From the repository root:

```sh
.venv/bin/python -m factory_constructor plan \
  --observation 13_iron_supply/integration/fixtures/iron-opening-observation.json \
  --item iron-plate --per-minute 10 --out /tmp/iron-program.json
.venv/bin/python -m unittest discover -s factory_constructor/tests -q
.venv/bin/python -m factory_constructor apply \
  --checkpoint 13_iron_supply/out/checkpoints/iron-ready-20260911 \
  --factorio /path/to/factorio --item iron-plate --per-minute 10 \
  --out /tmp/constructor-iron-new
```

The iron-ready checkpoint contains paid construction items. To exercise generated procurement,
use `--checkpoint 12_boiler_feed/out/checkpoints/feed-ready-20260911 --from-feed`. That test
harness first completes the existing boiler-feed prerequisite, then passes its fresh observation
to the constructor. This setup is outside the constructor proof; autonomous coal/power bootstrap
is still work to do. Both paths disable recording and preserve the existing 10× action / 40× wait
policy. Read `run-summary.json` first; detailed evidence remains on disk.

**Science run**

```sh
.venv/bin/python -m factory_constructor apply \
  --checkpoint factory_constructor/out/checkpoints/science-10-prepared \
  --factorio /path/to/factorio --item automation-science-pack --per-minute 10 \
  --out /tmp/constructor-science-new
```

The prepared checkpoint retains the verified iron service and paid construction inventory.
The completed run12 checkpoint is `factory_constructor/out/checkpoints/science-10`; compact
evidence is in `factory_constructor/integration/fixtures/science-10.json.gz`. Starting from
`/tmp/constructor-expand-01/checkpoints/factory-idle` also exercises generated procurement.

Check the completed checkpoint in a fresh native process with:

```sh
.venv/bin/python -m factory_constructor.integration.restore_checkpoint \
  --checkpoint factory_constructor/out/checkpoints/science-10 \
  --out /tmp/science-restore-new --factorio /path/to/factorio
```

A `constructor-prepared` checkpoint saves paid construction inventory before placement. It is an
explicit preparation boundary, with no claim that the science goal is complete. A
`constructor-idle` checkpoint is written only after observed service verification. Both validate
sealed files, prerequisite code, deployment identity, and the exact native idle world on restore.

The science verifier requires five consecutive idle minutes of new science production and chest
collection at the target rate. Native machine counters, recipe inputs, work in progress, resource
depletion, all inventories, fuel meters, and electricity statistics must balance. Fresh upstream
production must sustain the measured output; drawing down a finite iron or fuel stock cannot
pass the service check.

Before that measurement, the player waits through 5–30 simulated startup minutes. Startup ends
after three consecutive balanced windows with enough fresh inputs, science collection at the
target rate, and nondeclining connected fuel reserves. Invalid accounting or disconnected
machinery stops execution immediately. Failure to stabilize within 30 minutes also stops the
program. Startup windows do not count toward the five-minute service proof.

The runner prints compact text-only progress for each startup and measurement minute and saves
the balance result in `constructor-stabilization.json`. On failure, read `run-summary.json`,
the persisted stack in `execution.json`, and `constructor-failure-state.json`. The native
`user-data/script-output/live-trace.jsonl` provides later action boundaries when the last full
observation is stale. Normal runs keep images disabled.

**Native video replay**

Record construction and the production test from paid inventory with:

```sh
.venv/bin/python -m factory_constructor apply \
  --checkpoint factory_constructor/out/checkpoints/science-10-prepared \
  --factorio /path/to/factorio --item automation-science-pack --per-minute 10 \
  --out /tmp/science-video-new --record
```

This requires Pillow and ffmpeg. Recording uses a fixed camera covering the factory, captures
build boundaries and five-second production samples, and encodes `recording/replay.mp4` and
`recording/preview.gif`. Temporary native frames are removed after encoding; a poster and
frame hashes remain. The video is labeled as a checkpoint replay and uses that replay's own
service verification. Recording remains opt-in; earlier text-only runs contain no native footage.

**Next acceptance criteria**

Extend composition to independently registered service methods, allocate remaining fuel and
power capacity quantitatively, and support more surveyed layouts. Add safe migration for an
existing science deployment and a viewer for the persisted execution stack. Arbitrary in-flight
recovery remains separate from the current idle checkpoint boundaries.

Method implementations may encode proven layouts and game mechanics. Per-experiment action
sequences, manually selected counts and a goal label attached after choosing commands do not
prove declarative construction.
