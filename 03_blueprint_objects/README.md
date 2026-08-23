# 03_blueprint_objects

Blueprints as objects with typed INPUT / OUTPUT ports, a generator for single-recipe objects, and a bus
that stitches objects into larger objects. All commands from this directory with `../.venv/bin/python`.

## 1.0 Files

| File | Role |
|---|---|
| `module.py` | `Port`, `Module`: model, vanilla blueprint string export/import (ports ride in the description), checks |
| `templates.py` | single-recipe objects from `samples/<N>_to_1.md`, N = ingredient count 1-4, stacked to n machines |
| `make.py` | CLI: `make.py <item> <rate>` -> `out/<item>.module.json|txt|png` |
| `fluidcells.py` | generated columns for fluid machines (chemical plant, oil refinery) from prototype fluid boxes; pipe ports |
| `bus.py` | `Bus`, `Lane`, `compose()`: belt and pipe lanes, pull, push, merge, lane crossing, export drops |
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

Column count defaults to the belt-capacity minimum (narrowest blueprint). `plan()` sizes an item without building; `build_from_plan(columns=...)` builds; `compose.py --cells N` caps machines per column (splits more, wider and shorter), `--tune` tries N's neighbours and keeps the smallest real area; `choose_cells()` is the area-estimate picker used only when asked. `make.py` is unaffected.

## 3.5 Fluid cells (`fluidcells.py`)

Recipes with fluid ingredients or results (categories `chemistry` -> chemical plant 3x3, `oil-processing` -> oil refinery 5x5) are built from the prototype fluid boxes (`data/base/prototypes/entity/entities.lua`, north orientation, rotated in code): chemical plant inputs (−1,−1),(1,−1) exit north, outputs (−1,1),(1,1) exit south; refinery inputs (−1,2),(1,2) exit south, outputs (−2,−2),(0,−2),(2,−2) exit north. Machines face so that fluid inputs are on the west and outputs on the east, stacked every `size` rows.

| Element | Placement |
|---|---|
| fluid input i | external tile of box i; i = 0: plain pipe stub, vertical main one column further west; i >= 1: pipe-to-ground pair tunnelling out, main 2 columns further per i. Mains never touch |
| fluid output j | same scheme mirrored to the east; when the recipe has item belts the tunnels skip past them |
| item input (<= 1) | inserter at the machine's middle row picking from a northbound belt at base+1 |
| item output (<= 1) | long-handed inserter on an unused output row dropping on a southbound belt at base+2 |
| power | medium pole west of each machine, plus one on the bottom row east side (reachable by bus pole chains), all wired |
| ports | bottom row: every main is a `pipe` port (inputs flow N, outputs S), belts as usual |

Fluid ports are not capacity-limited; item belts split columns exactly as templates do. `make.py <item> <rate>` uses this automatically for fluid recipes (e.g. `make.py plastic-bar 2`, `make.py petroleum-gas 20 --recipe advanced-oil-processing`). Recipes with 2 item inputs or outputs (sulfuric acid) are not yet supported.

## 4.0 Bus and composition (`bus.py`, `compose.py`)

    compose.py <name> <spec>... [--belt NAME] [--export ITEM]... [--roboports [SPACING]] [-o DIR] [--no-render]
    compose.py <item> <rate>  [--raw ITEM]... [--from-plates] [--no-smelting] [--belt NAME] [--roboports [SPACING]] [-o DIR] [--no-render]

`--from-plates` = `--raw iron-plate --raw copper-plate`; `--no-smelting` makes every smelting-category product (plates, steel, bricks) an external input.

`<spec>` = `path.module.json` or `item=rate`. Modules are topologically ordered (producers west of consumers). Items consumed but not produced = external inputs; produced but not consumed (or `--export`) = outputs.

Factory mode (second form): the recipe tree of `<item>` is walked with `01_recipe_generatpr/recipe.py` (same recipe choice rules: recipe named after the item, else non-recycling recipe with fewest outputs), rates are summed per intermediate, and one module is generated per intermediate at its total. Fluid recipes go through `fluidcells`. Oil is planned separately: demand for petroleum-gas / heavy-oil / light-oil is met by advanced oil processing with all surplus heavy and light oil cracked (`oil_plans`: refinery crafts `c = (P + 0.5 H + 2/3 L) / 97.5`, heavy cracking `(25c − H)/40`, light cracking `(45c + 30 hc − L)/30`); crude oil and water become external pipe inputs. External inputs = `RAW` resources (ores, coal, stone, crude-oil, water, ...), `--raw` items, and anything no cell can build (>4 item ingredients, 2 item inputs on a fluid recipe, ...); each is printed with its reason. Output name `<item>-factory`.

| Command | Result |
|---|---|
| `compose.py military-science-pack 1` | 9 intermediates, 5 north / 4 south, 13 lanes, 86x87, 1,253 entities (one-sided: 98x58); IN iron-ore 5.75/s, copper-ore 0.5/s, coal 5/s, stone 10/s; OUT 1/s |
| `compose.py military-science-pack 10` | 33 column-modules, 17 north / 16 south, 31 lanes, 260x310, 11,672 entities (one-sided: 368x173); 4 ports short by 0.3-0.9/s (packing fragmentation, see LIMITS) |
| `compose.py military-science-pack 10 --raw iron-plate --raw copper-plate --roboports` | 267x306, 9,862 entities, 42 roboports, one pole network (one-sided: 465x73) |
| `compose.py electronic-circuit 2 --raw iron-plate --raw copper-plate` | plates fed from outside instead of smelted |
| `compose.py military-science-pack 1 --roboports` | 112x87, 6 roboports (bottom-left first), all wired |
| `compose.py plastics plastic-bar=2` | 15x12; IN petroleum-gas (pipe) 20/s + coal 1/s, OUT plastic 2/s |
| `compose.py advanced-circuit 1 --from-plates` | 92x66, 1,276 entities; 12 lanes (5 pipe: crude, water, heavy, light, petgas); refinery + heavy/light cracking + plastic + cable + circuits; IN copper-plate 5/s, iron-plate 2/s, crude-oil 20.5/s, water 27.2/s, coal 1/s; OUT advanced-circuit 1/s |
| `compose.py advanced-circuit 1` | same from ore: 105x75, 1,554 entities |
| `compose.py advanced-circuit N --raw iron-plate --raw copper-plate --roboports --one-sided` | N=2: 182x55, 2,027 entities, 8 roboports; N=5: 315x83, 4,633; N=10: 555x92, 11,007 entities, 11 refineries, 128 assemblers, 24 roboports. N=100 (392 modules, ~3,600 columns, 103 refineries in one column) does not pack: lane packing dead-ends late in the build |

Geometry (composite-local tiles, y down; `E` external inputs, `L` lanes, `R = 4`; `spacing` and `gap` are searched, see below). Modules sit on BOTH sides of the bus (`--one-sided` to disable): each module goes to the side whose x cursor is further west, and is never placed west of the push columns of its producers. South modules are mirrored vertically (`module.mirror`: rows flipped, N<->S directions, ports on the top edge).

| Region | Columns | Rows |
|---|---|---|
| External input risers | from `x_start` (5 with roboports), one column per external lane, skipping roboport bands and never putting two pipe risers side by side, northbound | bottom row up to `row(j)`, N->E curve |
| North modules | x cursor, `gap` apart, bottom-aligned on `by = max(north height)-1` | `0..by` |
| North routing band (`R = 5`) | belt port k jogs on row `B0-2-k` (south: `spare+2+k`); row `B0-1` holds the branch curves of lane-0 pulls | `by+1 .. by+R` |
| Bus | | one row per lane: `row(j) = B0+j`, `B0 = by+R+1`; spare row `B0+L` |
| South routing band | | `B0+L+1 .. B0+L+R` |
| South modules (mirrored) | x cursor, top-aligned on `bys = B0+L+R+1` | `bys ..` |
| Export drops | from `x_max+3`, deeper lanes further west, southbound | `row(j)` to bottom row |

Pipe lanes: a fluid is one lane of kind `pipe` (unlimited throughput). Two pipe lanes never sit on adjacent rows (a blank row is inserted), pipe risers and drops never sit on adjacent columns. A pipe pull or push is a straight vertical pipe from the port column to the lane, which tees into it (no splitter, no jog); pipe lanes duck under foreign tiles with pipe-to-ground pairs (span 9), belt lanes duck under pipe chains with belt undergrounds. Pipe ports reserve their neighbour columns so two chains never run side by side.

Cross-side conflicts: a module reserves its bus columns (push col..col+2, nominal pull bc-1..bc, pipe chains +-1); a later module whose columns would overlap a reserved one slides east. Pull candidates also reject a column where the lane could not surface before the splitter/turn, where the chain would sit beside another continuing lane's splitter/turn, or inside a roboport band.

Lanes and capacity (`allocate()`): an item may occupy several lanes, each `LANE_CAPACITY` (15/30/45/60 for yellow/red/blue/turbo). A module output is one belt-lane wide and is pushed onto a lane's left belt-lane (start curve or splitter merge) or right belt-lane (sideload from the south), whichever has more room, so two half-belt pushes fill one lane. Pulls of produced items take the tightest lane whose unclaimed supply covers the port, else the largest with a `WARNING ... short x/s` (in game that port runs under-supplied); external pulls are first-fit on capacity and open new external lanes as needed. Lane order: external lanes first (creation order), then internal. Non-exported lanes end at their last consumer. Exports = internal lanes with surplus for items no module consumes (or `--export`).

Ports of one module are grouped by proximity (column gap <= 2); port k of a group gets nominal bus column `bc = first_px + spacing*k` and jog row `B0-1-k`.

| Operation | Mechanism |
|---|---|
| pull (input k) | If this is the last consumer of the lane (no pull, merge, or export east of it), the lane itself turns toward the module at `bc`. Otherwise a splitter on the lane at `bc-1` (north module: rows `j-1`, `j`, branch exits into `(bc, j-1)`; south module: rows `j`, `j+1`, branch into `(bc, j+1)`). Then straight to jog row `k` of that side's band, across to the port column, into the port. Placement is a candidate search: `bc, bc+1, ..., bc+spacing-1` are tried in a grid transaction and rolled back on any tile collision (pushes are placed first, so chains route around push columns) |
| push (lane starts here) | port belt to the row beside the lane; curve into `row(j)` |
| merge, natural belt-lane (north: left, south: right) | feeder on the module-side row into the module-side input of a splitter at `(col+1)` spanning the lane row and that row; its other output is blocked, so the whole flow continues on the lane (as in `samples/bus_merge.md`) |
| merge, far belt-lane | chain passes straight through `row(j)` (the lane ducks under it), two tiles east along the far-side row, back toward the lane at `col+2` to sideload it |
| crossing | vertical chains never tunnel. Each lane ducks under every run of foreign tiles in its row (crossing chains, other lanes' splitters, merge feeders): underground in on the free tile before the run, out on the free tile after. Runs separated by one free tile merge. A plain "lane continues" tile after a splitter may itself become the underground entrance. The pair uses the slowest underground tier whose span covers the run (yellow 4, fast 6, express 8, turbo 10), so a yellow lane may duck with a fast pair under a 5-6 tile run |
| search | `compose()` tries `(spacing, gap)` in `SEARCH = (3,3),(4,3),(4,4),(5,4),(6,5)`; a `PackError` (a run longer than `MAX_GAP[belt]` = 4/6/8/10, or no free tile to surface) moves to the next candidate |
| power | a chain of medium poles along each module row between consecutive modules, every 9 tiles until the next module's nearest pole is in reach; the south network is bridged to the north one by a pole path after the chains are laid; each roboport gets a pole beside it, wired to a pole in reach or connected by a pole path (vertical, then horizontal, steps never longer than the remaining distance; on lane rows a path pole keeps two free tiles on each side so the lane can duck) |
| roboports (`--roboports [SPACING]`) | first roboport at the bottom-left (tiles 0-3 x H-4..H-1), then every SPACING tiles in both directions (default 48; 50 is the logistic-area touching limit, 110x110 construction area). Column bands `[SPACING*i-1, SPACING*i+4]` (roboport, pole, one surfacing tile) are kept free of modules, chains, and drops; risers start at column 5; lanes duck under the roboports that sit in the bus band. A module wider than `SPACING-7` cannot be placed, which is why `item=rate` specs and factory mode hand each column of a scaled-out module to the bus as its own module |

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
- Scale: hundreds of modules on one bus (e.g. red circuits at 100/s) produce kilometre-wide layouts and eventually a lane that cannot surface before its own splitter; no retry strategy covers that yet. Split such factories into several composites (plates, oil + plastic, circuits) and compose those, or use per-minute rates.
- The `(spacing, gap)` search is small; spacings above 3 cannot route 3- and 4-port templates (the third bus column would pass the module's own push column), so in practice a pack must succeed at spacing 3. If it does not, the error names the lane and columns.
- A pull splitter diverts up to half the lane into the branch; the branch backs up when the module is full, which is the intended behaviour.
- The gap pole cannot reach a nested composite's poles (they sit above its internal bus); WARNING printed, connect in game.
- Roboport power paths are greedy (vertical, then horizontal, with a waypoint past the riser wall for the west column); a roboport boxed in by south modules can stay unpowered — `WARNING roboport at (x, y) has no pole path` names it (1 of 42 in the 10/s roboport build). Connect it in game.
- Fluids: chemical plant and refinery only (no pumps, storage tanks, pumpjacks, offshore pumps); one item in / one item out per fluid recipe; pipe throughput not modelled; oil planning assumes advanced processing with full cracking (no basic processing, coal liquefaction, or heavy-oil consumers beyond direct demand).
