06_declarative_factory — anchored modules and incremental blueprint plans

This separate experiment develops the proposed Terraform-style factory interface. Typed Python
objects describe modules, nested groups, named ports, and explicit connections. Compilation
produces a stable design manifest; comparing revisions produces an additive construction plan
and a blueprint containing the additions. Existing modules keep their addresses and positions.

The first engine test imports a gear module from `03_blueprint_objects`, places it on the
[flat proving ground](../05_advisor_experiment/PROVING_GROUND.md), and attaches a second copy.
It preserves **28 existing entities**, adds **18**, and adds **zero** when repeated. Both modules
receive iron through their declared connections and produce gears. Missing research, a blocking
wall, and an unexpected existing recipe change are rejected.

This is an additive design and reconciliation prototype. Saved manifests describe designs;
they do not certify construction or throughput. The ordinary Python interface never changes a
game. Physical application is currently available only inside the disposable engine test.

**Run the Python example**

Python 3.10+ and the standard library suffice. From the repository root:

```sh
python3 06_declarative_factory/demo.py --out 06_declarative_factory/out/example
python3 -m unittest discover -s 06_declarative_factory/tests
```

Use a fresh output directory. The example writes:

| Artifact | Meaning |
| --- | --- |
| `first.json`, `expanded.json` | Compiled design manifests with stable addresses, geometry, ports, dependencies, and hashes |
| `initial-plan.json`, `incremental-plan.json` | Additions, retained entities, replacement/removal conflicts, and incremental entity bill |
| `expanded.blueprint.txt` | Complete expanded design |
| `additions.blueprint.txt` | New module and connecting belts only |
| `expansion.svg` | Retained entities in blue; additions in gold |

Blueprint strings are importable Factorio artifacts. The manifest stores absolute world
coordinates; Factorio's ordinary blueprint cursor can translate them. Align against the existing
factory deliberately. An observation-aware frontend that anchors placement automatically is pending.

**Declaration structure**

[demo.py](demo.py) contains the executable example. Its core composition looks like this:

```python
gear = Module("gear-a", gear_asset(), Tile(0, 0))
group = Group("main", Tile(0, 0), (feed_module, gear))
desired = Factory("gear-capacity", (group,), links=(feed_link,))

first = desired.compile()
change = plan(expanded.compile(), first)
```

`expanded` adds `main/gear-b` at `(24,0)` with its own connection. Groups may contain groups;
their transforms add and their names form addresses such as `main/smelting/iron-a`. Grouping
preserves explicit declarations; it does not yet automatically synthesize a recursive subfactory
from a production target.

The demo reserves two separate iron feed columns, exposing named attachment sockets. These
are a minimal bus boundary. They are not a completed shared trunk with working splitter taps.
The next bus implementation can expose those same port contracts while owning its physical
routing internally. See [DESIGN.md](DESIGN.md) for that direction and the state model.

**What is checked**

- Unique hierarchical module/port/link identities and nonoverlapping module reservations.
- A small explicit entity-geometry vocabulary, tile alignment, internal entity overlap, boundary
  belt ports, direction, and wire endpoint references. Unsupported settings and geometry fail.
- Matching item and transport type, sufficient declared source rate, and yellow-belt capacity.
  Generated connections currently require full-belt ports, adjacent cardinal tiles, no crossings,
  and correct entry/exit directions. Lane-specific ports can be exposed, but connecting them
  needs a separate method. Fan-out/merging requires explicit splitter modules and distinct ports.
- Additions preserve established geometry. Removals, relocation, recipe/configuration changes,
  and reservation resizing produce a blocked migration plan. There is no implicit demolition.
- An optional engine observation is bound to the baseline manifest and exact profile; missing
  or changed retained entities cause drift conflicts. The current observation adapter is scoped
  to the proving-ground harness, not arbitrary live saves. An observation does not prove freshness
  after later game changes.

Unconnected inputs and outputs remain explicit in the manifest. Declared rates are intended
service contracts; they are not measurements or proof that inserters, power, and supply meet
them. The demo requests 60 gears/min per module, based on assembler capacity. The physical test
confirms delivered materials and production, but does **not** certify that requested throughput.
The goal solver should eventually use separately measured/certified service rates.

The incremental bill is **1 assembling machine 1, 2 inserters, 1 small pole, and 14 belts**.
It is an entity-item bill, not a recursive raw-material procurement plan. The existing advisor's
construction planner is the intended next adapter for converting it into finite gathering and
crafting work, after checking actual research and inventory.

**Reuse of existing blueprints**

[assets/legacy-gear.module.json](assets/legacy-gear.module.json) was generated by the existing tool:

```sh
.venv/bin/python 03_blueprint_objects/make.py iron-gear-wheel 1 \
  --machine assembling-machine-1 --belt transport-belt --no-render \
  -o /tmp/advisor-gear-source
```

The checked-in asset preserves that output. `gear_asset()` explicitly adapts its medium pole
to a small pole at the same position, then assigns stable port names. The old tools and their
templates are unchanged. Their local source data identifies 2.1.14; the adapted geometry,
gear recipe selection, connections, and production have been tested separately in 2.1.16.
No blanket compatibility or throughput guarantee is inferred for other old blueprints.

**Actual-engine validation**

```sh
python3 06_declarative_factory/run_smoke.py \
  --factorio /path/to/factorio --out /tmp/advisor-declarative-run-01
```

The runner builds the flat world, stages compiled designs, and runs 1,805 ticks. Before each
mutation the test checks retained entity configurations, research, and actual engine placement
with `forced=false`. It checks that a wall blocks the entire addition before any entity is
created, preserves old unit IDs, and verifies repeated application creates nothing. Each gear
module makes **18 gears** after **96 plates** are inserted into its feed column during the run;
remaining plates can be in transit or buffers. A final recipe change blocks another update in
both Lua preflight and Python reconciliation.

The harness deliberately grants research, test electricity, construction entities, and finite
input plates. Those are setup for module/interface testing and are not a legally achieved opening.
It does not use a character to place entities, debit starter inventory, or certify 60 gears/min.
Wire migrations are excluded from this particular engine fixture. The normal observer package
contains none of the mutating controller. [integration/README.md](integration/README.md) describes
the retained evidence. There are **16 Python tests** for revision/connection behavior and that evidence.

The [finite opening experiment](../07_bootstrap_executor/README.md) now uses these objects to
declare a starter furnace, derive its one-item bill, choose an observed clear site, pay from
finite inventory, and verify actual smelting in Factorio. It tests both default and shifted
resource patches. Its costed placement adapter is separate from this module-expansion harness;
neither yet exercises interactive player cursor building or a general live deployment loop.
