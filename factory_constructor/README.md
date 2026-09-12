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
case also executed its generated procurement bill. All 240 tests across experiments 05–13 and
the constructor pass, including 16 constructor/interpreter/evidence tests.

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

Missing construction methods produce a blocked program before player work. For example,
10 red science/min expands to 20 iron plates/min and 10 copper plates/min, with gear/science
recipes, but currently lacks executable composition and consumer routing. The iron method
refuses an existing managed iron deployment because incremental expansion and crash recovery
need observed deployment reconciliation. It also refuses unsupported geometry and larger goals.
There is no implicit demolition or fallback to a handwritten experiment.

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

**Next acceptance criteria**

1. Reconcile a desired module against a fresh observed deployment, retaining sufficient existing
   capacity and adding only the deficit. Prove repeat declarations need no construction.
2. Compose registered methods recursively for intermediate items and required services. Share
   dependencies, allocate fuel/power capacity, and generate actual consumer connections.
3. Reach the red-science target through that compiler and interpreter, varying requested rate,
   inventory and supported world layout without changing the runner.
4. Persist safe execution boundaries and add the stack viewer, then extend to in-flight recovery.

Method implementations may encode proven layouts and game mechanics. Per-experiment action
sequences, manually selected counts and a goal label attached after choosing commands do not
prove declarative construction.
