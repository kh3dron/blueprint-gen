# 03_blueprint_objects

Blueprints as objects with typed INPUT / OUTPUT ports, a generator for single-recipe objects, and a bus
that stitches objects into larger objects. All commands from this directory with `../.venv/bin/python`.

## 1.0 Files

| File | Role |
|---|---|
| `module.py` | `Port`, `Module`: model, vanilla blueprint string export/import (ports ride in the description), checks |
| `templates.py` | single-recipe objects from `samples/<N>_to_1.md`, N = ingredient count 1-4, stacked to n machines |
| `make.py` | CLI: `make.py <item> <rate>` -> `out/<item>.module.json|txt|png` |
| `bus.py` | `Bus`, `Lane`, `compose()`: lanes, pull, push, merge, lane crossing, export drops |
| `compose.py` | CLI: `compose.py <name> <spec>...` -> `out/<name>.module.json|txt|png` |
| `samples/` | hand-made cells `1_to_1.md` .. `4_to_1.md`, `bus_merge.md` (merge in / merge out reference) |
| `out/` | generated objects |

## 2.0 Model (`module.py`)

- `Port`: `io` in/out, `kind` belt/pipe, `item`, `lane` left/right/both, tile `(x, y)` (object-local, (0,0) top-left), `direction` of flow (0 N, 4 E, 8 S, 12 W), `rate` items/s. One port = one lane of one tile.
- `Module`: `name`, `width`, `height`, `entities`, `tiles`, `wires`, `inputs`, `outputs`, `notes`.
- Convention: inputs enter the bottom edge northbound, left to right; outputs leave the bottom edge southbound at the right. Composites keep the same convention, so they nest.
- `to_string()` / `from_string()`: vanilla blueprint; `description` carries `SIZE WxH` plus one `PORT IN|OUT kind item lane (x,y) DIR rate/s` line per port. Survives a trip through the game.
- `Port.compatible(other)`: OUT feeds IN iff same kind and item, and IN lane is `both` or equal.

## 3.0 Single-recipe objects (`make.py`, `templates.py`)

    make.py <item> <rate> [--machine NAME] [--belt NAME] [--recipe NAME] [--layout template|row]

Template anatomy: inputs enter the bottom row northbound (ingredient order); bends under the machine merge them onto lanes (N=2: in1 left lane, in2 right lane; N=3,4: a second belt column reached by a long-handed inserter); output exits bottom-right southbound on the far lane. The machine's 3 rows + the pole row form a 4-row cell; cells stack upward with straight belts in every column the template's top row carries a belt, poles wired.

Machine count `n = ceil(crafts/s * time / speed)`; machine = category default (`assembling-machine-2`, `electric-furnace`) or `--machine`.

Scaling out: a module is one column of stacked cells unless a port would exceed what its belt can carry. Port capacities (yellow, scaled by belt tier): inputs per template N=1 [15], N=2 [7.5, 7.5], N=3 [15, 7.5, 7.5], N=4 [7.5 x4]; output 7.5 (one belt-lane). Machines per column = `min over ports of floor(cap_port * n / rate_port)`; columns = `ceil(n / per_col)`, machines distributed evenly, columns side by side (stride = template width + 1, bottom-aligned, bottom poles wired). Each column has its own ports, so a module's `inputs`/`outputs` may list the same item several times (rate split by machine share). A recipe whose single machine already exceeds a port's capacity adds a WARNING note. There is no height limit.

Examples: `iron-plate 5.75` -> 1 column of 10 furnaces; `iron-plate 57.5` -> 92 furnaces in 8 columns (output 7.2/s each); `copper-cable 20` -> 4 columns; `electronic-circuit 12` -> 8 columns of 1 (cable 4.5/s per port).

## 4.0 Bus and composition (`bus.py`, `compose.py`)

    compose.py <name> <spec>... [--belt NAME] [--export ITEM]... [-o DIR] [--no-render]
    compose.py <item> <rate>  [--raw ITEM]... [--belt NAME] [-o DIR] [--no-render]

`<spec>` = `path.module.json` or `item=rate`. Modules are topologically ordered (producers west of consumers). Items consumed but not produced = external inputs; produced but not consumed (or `--export`) = outputs.

Factory mode (second form): the recipe tree of `<item>` is walked with `01_recipe_generatpr/recipe.py` (same recipe choice rules: recipe named after the item, else non-recycling recipe with fewest outputs), rates are summed per intermediate, and one module is generated per intermediate at its total. External inputs = `RAW` resources (ores, coal, stone, crude-oil, water, ...), `--raw` items, and anything the templates cannot build (fluid ingredient/result, >4 ingredients, category without a 3x3 machine, e.g. plastic-bar, sulfur, processing-unit); each is printed with its reason. Output name `<item>-factory`.

| Command | Result |
|---|---|
| `compose.py military-science-pack 1` | 9 modules (iron-plate 5.75/s, copper-plate, steel-plate, stone-brick, firearm-magazine, piercing-rounds-magazine, grenade, stone-wall, military-science-pack), one column each, 13 lanes in 13 rows, 106x58, 1,150 entities, 42 lane ducks; IN iron-ore 5.75/s, copper-ore 0.5/s, coal 5/s, stone 10/s; OUT 1/s |
| `compose.py military-science-pack 10` | same modules scaled out where a port would exceed its belt (iron-plate 8 columns, stone-brick 7, ...), 31 lanes in 31 rows, 335x173, 10,206 entities, 519 lane ducks; 4 ports short by 0.3-0.9/s (packing fragmentation, see LIMITS) |
| `compose.py electronic-circuit 2 --raw iron-plate --raw copper-plate` | plates fed from outside instead of smelted |

Geometry (composite-local tiles, y down; `E` external inputs, `L` lanes, `R = 4`; `spacing` and `gap` are searched, see below):

| Region | Columns | Rows |
|---|---|---|
| External input risers | `0..E-1`, lane j at column j, northbound | bottom row up to `row(j)`, N->E curve |
| Modules | from `E+gap`, `gap` apart, bottom-aligned on `by = max(height)-1`; a module's footprint also covers its bus columns | `0..by` |
| Routing band | | `by+1 .. by+R` |
| Bus | | one row per lane: `row(j) = B0+j`, `B0 = by+R+1`; one spare row `B0+L` below |
| Export drops | `x_max+3+(L-1-j)`, deeper lanes further west, southbound | `row(j)` to bottom row |

Lanes and capacity (`allocate()`): an item may occupy several lanes, each `LANE_CAPACITY` (15/30/45/60 for yellow/red/blue/turbo). A module output is one belt-lane wide and is pushed onto a lane's left belt-lane (start curve or splitter merge) or right belt-lane (sideload from the south), whichever has more room, so two half-belt pushes fill one lane. Pulls of produced items take the tightest lane whose unclaimed supply covers the port, else the largest with a `WARNING ... short x/s` (in game that port runs under-supplied); external pulls are first-fit on capacity and open new external lanes as needed. Lane order: external lanes first (creation order), then internal. Non-exported lanes end at their last consumer. Exports = internal lanes with surplus for items no module consumes (or `--export`).

Ports of one module are grouped by proximity (column gap <= 2); port k of a group gets nominal bus column `bc = first_px + spacing*k` and jog row `B0-1-k`.

| Operation | Mechanism |
|---|---|
| pull (input k) | If this is the last consumer of the lane (no pull, merge, or export east of it), the lane itself turns north at `bc`. Otherwise a splitter on the lane at `bc-1` (rows `j-1`, `j`); the branch exits east into `(bc, j-1)` and turns north. Then straight up to jog row `B0-1-k`, across to the port column, up to the port. Placement is a candidate search: `bc, bc+1, ..., bc+spacing-1` are tried in a grid transaction and rolled back on any tile collision (pushes are placed first, so chains route around the module's own push columns) |
| push (lane starts here) | port belt south to `row(j)-1`; S->E curve at `row(j)` |
| merge, left belt-lane | descent to `row(j)-2`, east feeder at `row(j)-1` into the upper input of a splitter at `(col+1, rows j-1..j)`; its upper output is blocked (the next lane's underground exit or nothing), so the whole flow continues on the lane (as in `samples/bus_merge.md`) |
| merge, right belt-lane | chain passes straight through `row(j)` (the lane ducks under it), east along `row(j)+1` for two tiles, north at `col+2` to sideload the lane from the south |
| crossing | vertical chains never tunnel. Each lane ducks under every run of foreign tiles in its row (crossing chains, other lanes' splitters, merge feeders): underground in on the free tile before the run, out on the free tile after. Runs separated by one free tile merge. A plain "lane continues" tile after a splitter may itself become the underground entrance |
| search | `compose()` tries `(spacing, gap)` in `SEARCH = (3,3),(4,3),(4,4),(5,4),(6,5)`; a `PackError` (a run longer than `MAX_GAP[belt]` = 4/6/8/10, or no free tile to surface) moves to the next candidate |
| power | medium pole in each inter-module gap on row `by`, wired to each neighbour's nearest pole within 9 tiles |

Other tile conflicts raise `ValueError`. A consumer placed west of its lane's start is rejected.

Verified objects in `out/`:

| Name | Specs | Result |
|---|---|---|
| `circuits` | `copper-cable=6 electronic-circuit=2` | 4 lanes, 26x18, IN copper-plate 3/s + iron-plate 2/s, OUT electronic-circuit 2/s |
| `inserters` | `inserter=1 electronic-circuit=1 iron-gear-wheel=1 copper-cable=3` | 6 lanes, 50x16, 3-input module pulling from 3 lanes |
| `inserters-nested` | `out/circuits.module.json iron-gear-wheel=1 inserter=1` | composite inside composite, 58x28 |

All round-trip through the blueprint string with ports, wires, and recipes intact.

LIMITS
- Lane packing is greedy. With exact supply = demand (factory mode) and discrete column sizes, some ports can end up on a lane with less unclaimed supply than they need; each is reported as `WARNING ... short x/s`. Mitigations: `--belt fast-transport-belt` (larger lanes, fewer fragments) or a small rate margin on the top-level item.
- Port spacing assumes template port columns satisfy `px_k <= 2k+2` (true for the four samples).
- One row of modules per bus (no vertical stacking of modules).
- The `(spacing, gap)` search is small; spacings above 3 cannot route 3- and 4-port templates (the third bus column would pass the module's own push column), so in practice a pack must succeed at spacing 3. If it does not, the error names the lane and columns.
- A pull splitter diverts up to half the lane into the branch; the branch backs up when the module is full, which is the intended behaviour.
- The gap pole cannot reach a nested composite's poles (they sit above its internal bus); WARNING printed, connect in game.
- No fluids; belts only.
