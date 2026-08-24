# 03_blueprint_objects

Blueprints as objects with typed INPUT / OUTPUT ports, a generator for single-recipe objects, and a bus
that stitches objects into larger objects. All commands from this directory with `../.venv/bin/python`.

## 1.0 Files

| File | Role |
|---|---|
| `module.py` | `Port`, `Module`: model, vanilla blueprint string export/import (ports ride in the description), checks, `port_table` / `port_summary` |
| `templates.py` | single-recipe objects from `samples/<N>_to_1.md`, N = ingredient count 1-4, stacked to n machines |
| `make.py` | CLI: `make.py <item> <rate>` -> `out/<item>.module.json|txt|png` |
| `fluidcells.py` | generated columns for fluid machines (chemical plant, oil refinery, assembling machine on `crafting-with-fluid`) from prototype fluid boxes; pipe ports, item belts in the same cell |
| `bus.py` | `Bus`, `Lane`, `compose()`: belt and pipe lanes, pull, push, merge, lane crossing, export drops |
| `compose.py` | CLI: `compose.py <name> <spec>...` -> `out/<name>.module.json|txt|png`; `factory()` flat, `factory_tree()` nested |
| `samples/` | hand-made cells `1_to_1.md` .. `4_to_1.md`, `bus_merge.md` (merge in / merge out reference) |
| `bench.py` | CLI: runs every case in `CASES` through `compose.py`, prints the result table against `bench.json` |
| `bench.json` | recorded baseline for `bench.py` (28 cases) |
| `out/` | generated objects (`out/bench/` is the benchmark's scratch, git-ignored) |

## 2.0 Model (`module.py`)

- `Port`: `io` in/out, `kind` belt/pipe, `item`, `lane` left/right/both, tile `(x, y)` (object-local, (0,0) top-left), `direction` of flow (0 N, 4 E, 8 S, 12 W), `rate` items/s. One port = one lane of one tile.
- `Module`: `name`, `width`, `height`, `entities`, `tiles`, `wires`, `inputs`, `outputs`, `notes`, `no_mirror` (a vertical flip would break it; `mirror()` refuses and `bus.compose()` keeps it north).
- Convention: inputs enter the bottom edge northbound, left to right; outputs leave the bottom edge southbound at the right. Composites keep the same convention, so they nest.
- `to_string()` / `from_string()`: vanilla blueprint; `description` carries `SIZE WxH` plus one `PORT IN|OUT kind item lane (x,y) DIR rate/s` line per port. Survives a trip through the game.
- `Port.compatible(other)`: OUT feeds IN iff same kind and item, and IN lane is `both` or equal.

## 3.0 Single-recipe objects (`make.py`, `templates.py`)

    make.py <item> <rate> [--machine NAME] [--belt NAME] [--recipe NAME] [--layout template|row]

Template anatomy: inputs enter the bottom row northbound (ingredient order); bends under the machine merge them onto lanes (N=2: in1 left lane, in2 right lane; N=3,4: a second belt column reached by a long-handed inserter); output exits bottom-right southbound on the far lane. The machine's 3 rows + the pole row form a 4-row cell; cells stack upward with straight belts in every column the template's top row carries a belt, poles wired.

Machine count `n = ceil(crafts/s * time / speed)`; machine = category default (`assembling-machine-2`, `electric-furnace`) or `--machine`.

Ingredients are not tied to their recipe position: every input belt has its own inserter into the same machine, so any ingredient can sit on any input port. `plan(prefer=ITEM)` puts one on the leftmost port — the only one a direct link from the module next door can always reach (4.4) — and drops the swap if the resulting port capacities would cost a column. `compose.py` passes the ingredient that exactly one module produces and exactly one module consumes.

Scaling out: a module is one column of stacked cells unless a port would exceed what its belt can carry. Port capacities (yellow, scaled by belt tier): inputs per template N=1 [15], N=2 [7.5, 7.5], N=3 [15, 7.5, 7.5], N=4 [7.5 x4]; output 7.5 (one belt-lane). Machines per column = `min over ports of floor(cap_port * n / rate_port)`; columns = `ceil(n / per_col)`, machines distributed evenly, columns side by side (stride = template width + 1, bottom-aligned, bottom poles wired). Each column has its own ports, so a module's `inputs`/`outputs` may list the same item several times (rate split by machine share). A recipe whose single machine already exceeds a port's capacity adds a WARNING note. There is no height limit.

Examples: `iron-plate 5.75` -> 1 column of 10 furnaces; `iron-plate 57.5` -> 92 furnaces in 8 columns (output 7.2/s each); `copper-cable 20` -> 4 columns; `electronic-circuit 12` -> 8 columns of 1 (cable 4.5/s per port).

Column count defaults to the belt-capacity minimum (narrowest blueprint). `plan()` sizes an item without building; `build_from_plan(columns=...)` builds; `compose.py --cells N` caps machines per column (splits more, wider and shorter), `--tune` tries N's neighbours and keeps the smallest real area; `choose_cells()` is the area-estimate picker used only when asked. `make.py` is unaffected.

## 3.5 Fluid cells (`fluidcells.py`)

Recipes with fluid ingredients or results are built from the prototype fluid boxes (`data/base/prototypes/entity/entities.lua`, north orientation, rotated in code), one machine per category:

| Category | Machine | Fluid boxes (prototype north) | Item ports the cell can hold |
|---|---|---|---|
| `chemistry` | chemical plant 3x3 | in (−1,−1),(1,−1) exit north; out (−1,1),(1,1) exit south | 4 minus the rows the used boxes take |
| `oil-processing` | oil refinery 5x5 | in (−1,2),(1,2) exit south; out (−2,−2),(0,−2),(2,−2) exit north | 4 |
| `crafting-with-fluid` | assembling machine 2 3x3 | in (0,−1) exit north; out (0,1) exit south | 4 |

Machines face so that fluid inputs are on the west and outputs on the east, stacked every `pitch` rows (`pitch` = machine size, +1 only when no row is left for the pole). `A = size//2 + 1` is the column beside the machine; `b` = item belts on that side.

| Element | Placement |
|---|---|
| fluid box k of a side | connects at its external tile (column ±A). `b = 0`, `k = 0`: plain pipe stub, main at A+1. Otherwise a pipe-to-ground pair tunnels past the item belts to a main at A+2+b+2k, partner one column inside it. Mains are 2 columns apart so they never touch (longest span in the recipe set: 4 tiles, limit 10) |
| item port, slot 0 of a side | inserter at column ±A picking from / dropping on the belt at ±(A+1) |
| item port, slot 1 of a side | long-handed inserter at column ±A reaching the belt at ±(A+2) |
| item port rows | the rows of column ±A that no fluid box uses, outermost first; a side offers `min(2, free rows)` slots |
| item port sides | ingredients fill the west slots, results the east ones (inputs west, outputs east, as the fluid mains already are); a port that does not fit its own side takes a far slot on the other one. Input belts run north, output belts south |
| power | medium pole on a free row of column A (west first, else east, else a spare row under the machine), plus one on the bottom row east of the machine (reachable by bus pole chains), all wired |
| ports | bottom row: every main is a `pipe` port (inputs flow N, outputs S), belts as usual. An item output port's lane is the belt's far lane from its inserter: `left` on the east side, `right` on the west |

So one cell holds up to 4 item ports plus the machine's fluid boxes: 28 of the 60 recipes with both item and fluid ingredients build (`processing-unit`, `sulfuric-acid`, `battery`, `concrete`, `refined-concrete`, `express-transport-belt`, `electric-engine-unit`, `coal-liquefaction`, ...). 4 are rejected for needing 5 item ports (`foundry`, `foundation`, both overgrowth soils); the other 28 use a space-age machine that has no model here (`metallurgy`, `organic`, `electromagnetics`, `cryogenics`).

Fluid ports are not capacity-limited; item belts split columns exactly as templates do (input belt = whole belt, output = one lane, scaled by tier). `make.py <item> <rate>` uses this automatically for fluid recipes (`make.py processing-unit 0.2` -> 10x10, `make.py sulfuric-acid 10` -> 10x4, `make.py plastic-bar 2` -> 9x4, `make.py petroleum-gas 20 --recipe advanced-oil-processing`); `--machine assembling-machine-3` overrides the crafting-with-fluid machine.

A cell sets `Module.no_mirror` unless every fluid box it uses sits on the machine's centre row. A recipe binds fluid ingredient k to box k, so mirroring a chemical plant or refinery vertically would feed each fluid into its neighbour's box; `bus.compose()` keeps those modules on the north side. Assembling machine cells have both boxes on the centre row and mirror freely, so `crafting-with-fluid` modules still use both sides of the bus. The flag rides in the blueprint description as a `NO-MIRROR` line and survives a round trip.

## 3.9 Benchmark (`bench.py`)

    bench.py [--only PAT]... [--save] [--full] [--jobs N] [--list] [--no-cells] [--arg=X] [-v]

28 compose.py command lines — spec mode, factory mode, fluid cells, 4-ingredient recipes, roboports,
`--nested`, `--one-sided`, `--no-links`, `--tune`, `--cells`, and the scaled-out builds — each run with
`--stats`, which writes a one-line JSON summary (size, entities, wires, lanes, links, warnings, modules,
ducks, roboports, spacing, gap, seconds). Every number is printed against `bench.json`; a case that grew
by more than `TOL` (2%) is marked REGRESSED and the exit code is 1, so it works as a check as well as a
report. The whole suite takes ~1 s (~2 s with `--full`, which adds the 10/s processing units).

    $ ../.venv/bin/python bench.py
    CASE                         SIZE         AREA     ENTITIES  LANES  LINKS  WARN   TIME
    --------------------------------------------------------------------------------------
    circuits                    21x16          336           97      3      1     0   0.1s
    military-1                  62x87        5,394        1,044     10      3     0   0.1s
    utility-turbo             219x203       44,457        5,335     20      5     0   0.2s
    ...
    28 cases: 28 built, 0 failed, 0 regressed
    CELLS 42 fluid recipes build clean, 0 broken, 4 rejected as too big for a cell

`--only` takes a regex against the case name or its arguments (`--only 'science|circuit'`), `--arg=X`
adds an argument to every run (`--arg=--no-links` to see what the links are worth), `--save` records the
current numbers as the new baseline. CELLS is a structural check of every fluid recipe's generated cell
rather than a layout: entity overlaps, tiles outside the module, ports sitting on the right entity,
every inserter's pickup and drop in both orientations, and a blueprint-string round trip.

## 4.0 Bus and composition (`bus.py`, `compose.py`)

Console report: one `[n/m] LABEL` line per stage (RECIPE or SPECS, MODULES or TREE, BUS, CHECK, WRITE, RENDER) with its numbers indented under it, then the composite size, a port summary (one row per item: port count, total rate, column span) and the warnings grouped by kind. Everything goes to stdout in order; nothing is interleaved from stderr. `-v` adds the per-plan table, the lane table, the module roll-call, every port, and the full text of every warning and every failed `(spacing, gap)` retry. Warnings are also written into the blueprint description, so the artifact keeps them.

    compose.py <name> <spec>... [--belt NAME] [--export ITEM]... [--roboports [SPACING]] [-o DIR] [--no-render] [-v]
    compose.py <item> <rate>  [--raw ITEM]... [--from-plates] [--no-smelting] [--belt NAME] [--roboports [SPACING]] [--nested [--nest-min N]] [--no-links] [-o DIR] [--no-render] [-v]

`--from-plates` = `--raw iron-plate --raw copper-plate`; `--no-smelting` makes every smelting-category product (plates, steel, bricks) an external input.

`<spec>` = `path.module.json` or `item=rate`. Modules are topologically ordered (producers west of consumers). Items consumed but not produced = external inputs; produced but not consumed (or `--export`) = outputs.

Factory mode (second form): the recipe tree of `<item>` is walked with `01_recipe_generatpr/recipe.py` (same recipe choice rules: recipe named after the item, else non-recycling recipe with fewest outputs), rates are summed per intermediate, and one module is generated per intermediate at its total. Fluid recipes go through `fluidcells`. Oil is planned separately: demand for petroleum-gas / heavy-oil / light-oil is met by advanced oil processing with all surplus heavy and light oil cracked (`oil_plans`: refinery crafts `c = (P + 0.5 H + 2/3 L) / 97.5`, heavy cracking `(25c − H)/40`, light cracking `(45c + 30 hc − L)/30`); crude oil and water become external pipe inputs. External inputs = `RAW` resources (ores, coal, stone, crude-oil, water, ...), `--raw` items, and anything no cell can build (>4 item ingredients, >4 item ports on a fluid recipe, a machine with no model, ...); each is printed once with its total and its reason. Output name `<item>-factory`.

| Command | Result |
|---|---|
| `compose.py military-science-pack 1` | 9 intermediates, 10 lanes, 3 direct links, 62x87, 1,044 entities (`--no-links`: 13 lanes, 86x89, 1,280); IN iron-ore 5.75/s, copper-ore 0.5/s, coal 5/s, stone 10/s; OUT 1/s |
| `compose.py military-science-pack 10` | 33 column modules, 31 lanes, 280x310, 11,824 entities; 4 ports short (packing fragmentation, see LIMITS) |
| `compose.py military-science-pack 10 --raw iron-plate --raw copper-plate --roboports` | 267x306, 9,945 entities, 42 roboports, one pole network |
| `compose.py military-science-pack 1 --roboports` | 74x89, 1,174 entities, 4 roboports (bottom-left first), all wired |
| `compose.py electronic-circuit 2 --raw iron-plate --raw copper-plate` | 21x16, 97 entities; plates fed from outside instead of smelted, cable linked straight into the circuits (`--no-links`: 24x32, 170) |
| `compose.py advanced-circuit 1 --from-plates` | 77x65, 1,122 entities; 11 lanes (5 pipe: crude, water, heavy, light, petgas); refinery + heavy/light cracking + plastic + cable + circuits; IN copper-plate 5/s, iron-plate 2/s, crude-oil 20.5/s, water 27.2/s, coal 1/s; OUT advanced-circuit 1/s |
| `compose.py advanced-circuit 1` | same from ore: 107x73, 1,533 entities |
| `compose.py advanced-circuit N --raw iron-plate --raw copper-plate --roboports --one-sided` | N=2: 183x55, 2,027 entities, 8 roboports; N=10: 582x92, 11,249 entities, 26 roboports (`out/advanced-circuit-factory.*`). N=100 (392 modules, ~3,600 columns, 103 refineries in one column) does not pack: lane packing dead-ends late in the build |
| `compose.py processing-unit 10 --raw iron-plate --raw copper-plate --roboports --belt fast-transport-belt` | 1,410x320, 68,169 entities, 129 modules (67 north / 62 south), 71 lanes (6 pipe), 210 roboports, 16 s including the render; 721 assemblers, 52 chemical plants, 25 refineries; IN crude-oil 487/s, water 821/s (both pipe), iron-plate 241/s, copper-plate 400/s, coal 20/s; OUT 10/s. 14 ports short, 1 roboport with no pole path (see LIMITS) |
| `compose.py utility-science-pack 1 --raw iron-plate --raw copper-plate --belt turbo-transport-belt` | 219x203, 5,335 entities, 22 modules, 20 lanes (6 pipe), 5 direct links, no warnings; 20 intermediates incl. flying robot frames, electric engine units, batteries, oil |
| `compose.py utility-science-pack 1 --from-plates` | same from plates on yellow belt: 413x177, 9,932 entities, 43 modules |
| `compose.py production-science-pack 1 --from-plates` | 284x219, 6,796 entities, 30 modules |
| `compose.py processing-unit 1 --from-plates --belt fast-transport-belt` | 198x112, 3,484 entities, 2 direct links; refinery + cracking, sulfur, sulfuric acid, plastic, cable, green and red circuits, processing units |
| `compose.py sulfuric-acid 20 --from-plates` | 70x28, 553 entities; IN water 111/s (pipe), crude-oil 30.8/s (pipe), iron-plate 0.4/s |
| `compose.py battery 2 --from-plates` | 83x44, 965 entities; chemical plant with 2 item inputs and 1 item output |
| `compose.py concrete 5 --from-plates` | 28x54, 401 entities; assembler with water + stone-brick + iron-ore |
| `compose.py express-transport-belt 2 --from-plates` | 135x93, 2,471 entities |
| `compose.py electric-engine-unit 1 --from-plates` | 109x130, 2,125 entities |

Geometry (composite-local tiles, y down; `E` external inputs, `L` lanes, `R = 4`; `spacing` and `gap` are searched, see below). Modules sit on BOTH sides of the bus (`--one-sided` to disable): each module goes to the side whose x cursor is further west, and is never placed west of the push columns of its producers. South modules are mirrored vertically (`module.mirror`: rows flipped, N<->S directions, ports on the top edge); a module with `no_mirror` set (chemical plant and refinery cells) always goes north.

| Region | Columns | Rows |
|---|---|---|
| Link row (only where links exist) | between the two ports | `by+1` north, `bys-1` south |
| External input risers | from `x_start` (5 with roboports), one column per external lane, skipping roboport bands and never putting two pipe risers side by side, northbound | bottom row up to `row(j)`, N->E curve |
| North modules | x cursor, `gap` apart, bottom-aligned on `by = max(north height)-1`. North modules may sit over the riser wall — risers only occupy rows below the bus — as long as none of their chains runs down a column where a lane *above* them rises, or beside one (a lane ducking under the chain needs a free tile on each side). South modules share rows with the risers, so they start east of the wall; sides are dealt on progress from their own start, not on absolute column | `0..by` |
| North routing band (`R = k_max + 2`) | belt port k jogs on row `B0-2-k` (south: `spare+2+k`); row `B0-1` holds the branch curves of lane-0 pulls. `band_rows()` sizes it from the widest port group actually on that side, so a side of 2-port modules gets 3 rows, not the 5 a 4-port template needs | `by+1 .. by+R` |
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
| pull (input k) | If this is the last consumer of the lane (no pull, merge, or export east of it), the lane itself turns toward the module at `bc`. Otherwise a splitter on the lane at `bc-1` (north module: rows `j-1`, `j`, branch exits into `(bc, j-1)`; south module: rows `j`, `j+1`, branch into `(bc, j+1)`). Then straight to jog row `k` of that side's band, across to the port column, into the port. Placement is a candidate search in a grid transaction, rolled back on any tile collision: `bc, bc+1, ..., bc+spacing-1` first, then west one column at a time down to the port column (a whole-lane pull stops at the lane's last merge or pull, which it may not cut off). The jog row runs from the chosen column back to the port column and ducks under anything already there with an underground pair — in practice the module's own push chain, which a nominal column east of it always has to cross |
| push (lane starts here) | port belt to the row beside the lane; curve into `row(j)` |
| merge, natural belt-lane (north: left, south: right) | feeder on the module-side row into the module-side input of a splitter at `(col+1)` spanning the lane row and that row; its other output is blocked, so the whole flow continues on the lane (as in `samples/bus_merge.md`) |
| merge, far belt-lane | chain passes straight through `row(j)` (the lane ducks under it), two tiles east along the far-side row, back toward the lane at `col+2` to sideload it |
| direct link | an item with one producer port and one consumer port next door on the same side skips the bus entirely: a belt (or pipe) run along the link row under the modules. See 4.4 |
| crossing | vertical chains never tunnel; horizontal jog runs and direct links do (see pull, 4.4). Each lane ducks under every run of foreign tiles in its row (crossing chains, other lanes' splitters, merge feeders): underground in on the free tile before the run, out on the free tile after. Runs separated by one free tile merge. A plain "lane continues" tile after a splitter may itself become the underground entrance. The pair uses the slowest underground tier whose span covers the run (yellow 4, fast 6, express 8, turbo 10), so a yellow lane may duck with a fast pair under a 5-6 tile run |
| search | `compose()` tries `(spacing, gap)` in `SEARCH = (3,3),(4,3),(4,4),(5,4),(6,5)`; a `PackError` (a run longer than `MAX_GAP[belt]` = 4/6/8/10, or no free tile to surface) moves to the next candidate |
| power | a chain of medium poles along each module row between consecutive modules, every 9 tiles until the next module's nearest pole is in reach; the south network is bridged to the north one by a pole path after the chains are laid; each roboport gets a pole beside it, wired to a pole in reach or connected by a pole path (vertical, then horizontal, steps never longer than the remaining distance; on lane rows a path pole keeps two free tiles on each side so the lane can duck) |
| roboports (`--roboports [SPACING]`) | first roboport at the bottom-left (tiles 0-3 x H-4..H-1), then every SPACING tiles in both directions (default 48; 50 is the logistic-area touching limit, 110x110 construction area). Column bands `[SPACING*i-1, SPACING*i+4]` (roboport, pole, one surfacing tile) are kept free of modules, chains, and drops; risers start at column 5; lanes duck under the roboports that sit in the bus band. The whole grid is shifted up by 0-11 rows so that no roboport band covers a module pole-chain row (`by`, `bys`), which those chains cross end to end; a spot still blocked (a power path got there first) is skipped with a WARNING and counted in the bus note. A module wider than `SPACING-7` cannot be placed, which is why `item=rate` specs and factory mode hand each column of a scaled-out module to the bus as its own module |

Other tile conflicts raise `ValueError`. A consumer placed west of its lane's start is rejected.

## 4.4 Direct links (`bus.py`, on by default, `--no-links` to disable)

An item carried by exactly one output port and one input port never needs a lane: it can run straight
from the producer to the consumer along the row under the modules. `solo_items()` finds those pairs —
one producer port, one consumer port, same kind, producer rate covering the consumer's, and an input
port a run from the west can actually reach past that module's other port chains (which is why the cell
generator puts a single-use ingredient on the leftmost port, 3.0). `topo_sort()` then
schedules each pair as one unit (they chain, so a whole production line comes out contiguous), and
`_layout()` puts the consumer on its producer's side when the producer is still the last module there.

| Element | Placement |
|---|---|
| link row | one extra routing row directly under the modules: `by+1` north, `bys-1` south, clear of every jog row (`B0 = by + R + 1 + link_n`). Only added on a side that has links |
| the run | producer's output port column -> east along the link row -> north into the consumer's input port column. Ducks under everything that crosses it (the other ports' chains come down at their own columns) with an underground pair, slowest tier that spans the run; a pipe link ducks with pipe-to-ground |
| lanes | a linked port is skipped by `allocate()`, so the item gets no lane, no push, no pull, and no trip down to the bus and back. A solo item's ports also claim no bus column while modules are being placed, and a consumer only has to sit one column east of its producer instead of three |
| fallback | the reordering can cost more elsewhere than the lane it saves, so when any link fires `compose.py` lays the same modules out both ways and keeps the smaller (reported in the BUS step) |

| Factory | before this pass | now | lanes | links |
|---|---|---|---|---|
| `circuits copper-cable=6 electronic-circuit=2` | 24x32 = 768, 170 entities | 21x16 = 336, 97 entities | 4 -> 3 | 1 |
| `electronic-circuit 2 --raw iron-plate --raw copper-plate` | 24x32 = 768, 170 entities | 21x16 = 336, 97 entities | 4 -> 3 | 1 |
| `plastics plastic-bar=2` | 15x13 = 195, 61 entities | 14x10 = 140, 45 entities | 3 | 0 |
| `military-science-pack 1` | 86x89 = 7,654, 1,280 entities | 62x87 = 5,394, 1,044 entities | 13 -> 10 | 3 |
| `advanced-circuit 1 --from-plates` | 92x68 = 6,256, 1,309 entities | 77x65 = 5,005, 1,122 entities | 12 -> 11 | 1 |
| `processing-unit 1 --from-plates --belt fast-transport-belt` | 198x140 = 27,720, 3,843 | 198x112 = 22,176, 3,484 | 18 -> 16 | 2 |
| `utility-science-pack 1 --raw ... --belt turbo-transport-belt` | 240x208 = 49,920, 5,842 | 219x203 = 44,457, 5,335 | 25 -> 20 | 5 |
| `utility-science-pack 1 --from-plates` | 419x182 = 76,258, 10,504 | 413x177 = 73,101, 9,932 | 35 -> 30 | 5 |
| `production-science-pack 1 --from-plates` | 291x221 = 64,311, 7,328 | 284x219 = 62,196, 6,796 | 27 -> 26 | 1 |
| `military-science-pack 10 --raw ... --roboports` | 267x308, 10,063 | 267x306, 9,945 | 27 | 0 |
| `processing-unit 10 --raw ... --belt fast-transport-belt` | 1,095x320, 57,791 | 1,097x318, 56,845 | 71 | 0 |

LIMIT: a module scaled out into columns has N producer ports and M consumer ports for the same item, so
nothing qualifies and the biggest factories are untouched. Pairing column i of the producer with column
i of the consumer would fire there, but the column counts come from belt capacity on each side
independently, so the per-column rates do not line up (`copper-cable` 14.8/s per column against
`electronic-circuit` needing 13.3/s); it needs the planner to size both sides together.

## 4.5 Nested factories (`compose.py --nested`)

    compose.py <item> <rate> --nested [--nest-min N] ...

One bus per sub-factory instead of one bus for everything. `factory_tree()` walks the recipe tree and
splits the intermediates two ways:

| Intermediate | Where it is produced |
|---|---|
| consumed by exactly one recipe | inside that recipe's own box: its own bus, its own bounding box. It never reaches the parent bus |
| consumed by several recipes | on the parent bus, as its own box or inlined beside its consumers |
| oil products (`oil_plans`) | one unit: inside the single consumer's box, else on the top bus |
| `RAW` / `--raw` | external input of whichever box needs it, passed down from the parent's lanes |

A group of fewer than `--nest-min N` modules (default 6) is inlined into its parent's bus rather than
paying for a routing band of its own; `--nest-min 99` degenerates to the flat layout.

A composite meant to be nested is composed with `bus.compose(..., nested=True)`, which does two things
a top-level composite does not need: external input risers `RISER_GAP = 3` columns apart, so the parent
can bring a pull chain up to each of them (adjacent ports leave no room for a chain, and a pipe chain
has no alternative column at all), and a medium pole at each end of the bottom edge, wired into the
box's network, so the parent's pole chain can reach it.

The TREE step prints what went where — `compose.py advanced-circuit 1 --from-plates --nested --nest-min 1`:

    [2/5] TREE    3 modules on the top bus, 2 nested boxes
            BOX                                 RATE  MODULES  SIZE
            copper-cable                        10/s       2  inline
            advanced-circuit                     1/s       3  105x80
              electronic-circuit                 2/s       1  inline
              plastic-bar                        2/s       4  63x27
                oil                             20/s       3  inline  (advanced+heavy+light)

`copper-cable` has two consumers, so it stays on the top bus; `plastic-bar` has one, so it becomes a box
inside `advanced-circuit`, and the oil it needs is inside that box in turn. The top bus carries plates,
coal, water, crude oil and copper cable — nothing else.

Measured against the flat layout (area = w x h, lanes = top bus):

| Factory | flat | nested (default `--nest-min 6`) | lanes flat -> nested |
|---|---|---|---|
| `advanced-circuit 1 --from-plates` | 93x70 = 6,510 | 114x96 = 10,944 | 12 -> 7 |
| `low-density-structure 1 --from-plates` | 103x119 = 12,257 | 127x133 = 16,891 | 12 -> 7 |
| `processing-unit 1 --from-plates --belt fast-transport-belt` | 198x140 = 27,720 | 207x117 = 24,219 | 18 -> 18 |
| `flying-robot-frame 1 --from-plates` | 183x210 = 38,430 | 217x231 = 50,127 | 21 -> 13 |
| `utility-science-pack 1 --raw ... --belt turbo-transport-belt` | 240x208 = 49,920 | 268x202 = 54,136 | 25 -> 19 |
| `military-science-pack 10 --raw iron-plate --raw copper-plate` | 206x308 = 63,448 | 302x328 = 99,056 | 27 -> 18 |
| `production-science-pack 1 --from-plates` | 291x221 = 64,311 | 332x252 = 83,664 | 27 -> 18 |
| `express-transport-belt 2 --from-plates` | 135x93 = 12,555 | does not pack | |
| `advanced-circuit 10 --raw iron-plate --raw copper-plate` | 419x154 = 64,526 | box `advanced-circuit 10/s` does not pack (packs at `--nest-min 8`: 464x188) | 26 -> 19 |
| `processing-unit 10 --raw ... --belt fast-transport-belt` | 1,095x320 = 350,400 | box `advanced-circuit 20/s` does not pack at any threshold | |

VERDICT: the decomposition does what it is meant to do — the top bus loses 30-45% of its lanes, and an
intermediate with one consumer never travels to the bus and back. It still costs area in every case but
one, because each box pays for a full routing band (`2R = 10` rows plus its own lane rows and spare row)
plus riser and drop columns, and because boxes are bottom-aligned so their bands stack. It is also more
fragile: three of the ten factories above do not pack, and `--roboports` rejects nested boxes outright
(a box is wider than `SPACING-7`). Flat stays the default.

The cheaper way to get the same effect is 4.4, direct links: same idea, one bus, no extra band.

Spec mode, verified (only `advanced-circuit-factory.*` is kept in `out/`):

| Name | Specs | Result |
|---|---|---|
| `circuits` | `copper-cable=6 electronic-circuit=2` | 3 lanes + 1 direct link, 21x16, IN copper-plate 3/s + iron-plate 2/s, OUT electronic-circuit 2/s |
| `inserters` | `inserter=1 electronic-circuit=1 iron-gear-wheel=1 copper-cable=3` | 4 lanes, 33x20, 3-input module pulling from 3 lanes |
| `nested` | `circuits.module.json iron-gear-wheel=1 inserter=1` | composite inside composite, 39x49 |
| `plastics` | `plastic-bar=2` | 14x10, IN petroleum-gas (pipe) 20/s + coal 1/s, OUT plastic-bar 2/s |
| `chips` | `sulfuric-acid=10 processing-unit=0.2` | 27x21, a chemical plant feeding an assembler by pipe: IN water 20/s (pipe), iron-plate 0.2/s, sulfur 1/s, electronic-circuit 4/s, advanced-circuit 0.4/s; OUT processing-unit 0.2/s |

All round-trip through the blueprint string with ports, wires, recipes, and the `NO-MIRROR` flag intact.

LIMITS
- Lane packing is greedy. With exact supply = demand (factory mode) and discrete column sizes, some ports can end up on a lane with less unclaimed supply than they need; each is reported as `WARNING ... short x/s`. Mitigations: `--belt fast-transport-belt` (larger lanes, fewer fragments) or a small rate margin on the top-level item.
- Port spacing (`bc = first_px + spacing*k`) walks east faster than the template port columns, so port 3 of a 4-input template lands past the module's own output column. The jog row ducks under that push chain, and the candidate search falls back west, which is what makes 4-ingredient recipes (`flying-robot-frame`, `utility-science-pack`) pack at all.
- One row of modules per bus (no vertical stacking of modules).
- Scale: hundreds of modules on one bus (e.g. red circuits at 100/s) produce kilometre-wide layouts and eventually a lane that cannot surface before its own splitter; no retry strategy covers that yet. Split such factories into several composites (plates, oil + plastic, circuits) and compose those, or use per-minute rates.
- The `(spacing, gap)` search is small; spacings above 3 cannot route 3- and 4-port templates (the third bus column would pass the module's own push column), so in practice a pack must succeed at spacing 3. If it does not, the error names the lane and columns.
- A pull splitter diverts up to half the lane into the branch; the branch backs up when the module is full, which is the intended behaviour.
- A composite composed without `nested=True` has no pole on its bottom edge, so a parent bus's pole chain may not reach its network (its poles sit above its internal bus); WARNING printed, connect in game. Boxes built by `--nested` do have those poles.
- Roboport power paths are greedy (vertical, then horizontal, with a waypoint past the riser wall for the west column); a roboport boxed in by south modules can stay unpowered — `WARNING roboport at (x, y) has no pole path` names it (1 of 42 in the 10/s roboport build). Connect it in game.
- Fluids: chemical plant, refinery, and assembling machine only (no pumps, storage tanks, pumpjacks, offshore pumps, and none of the space-age machines — `metallurgy`, `organic`, `electromagnetics`, `cryogenics` — so 28 of the 60 mixed item+fluid recipes stay external). Pipe throughput is not modelled. Oil planning assumes advanced processing with full cracking (no basic processing, coal liquefaction, or heavy-oil consumers beyond direct demand).
- A fluid cell holds at most 2 item belts per side (inserter reach 1, long-handed reach 2), so at most 4 item ports; `foundry`, `foundation`, and the overgrowth soils need 5 and stay external.
- `--nested` costs area (4.5) and does not survive `--roboports` (a box is wider than `SPACING-7`); the two largest factories do not pack with it.
- Chemical plant and refinery cells cannot be mirrored (`no_mirror`), so they all land on the north side; a long factory with many of them packs less evenly than one with only assembler cells. Fixing this needs the 2.0 per-entity mirror flag, which is not written here.
