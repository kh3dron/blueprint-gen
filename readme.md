Factorio recipe tools

- [x] 01: recipe calculator
  - [x] for a given item, calculate the rates of all intermediate parts

- [x] 02: visualize blueprints

- [ ] compile designs into blueprints

- [ ] get game sprites
- [ ] get game fact tables
- [ ] DFS solver

Now we're going to enhance the funcionality of a basic blueprint, by treating them as objects with inputs and outputs.

Ideas for implementation:

- something akin to structure blocks in minecraft: every blueprint should have INPUT and OUTPUT points. in early blueprints, these will all be along the bottom edge of the builds; the first input being at the bottom left corner and the first output being on the bottom right corner. we may need to create modded versions of belts, to represent "belt with iron plate on left side", which might be an input in a gear blueprint; the assemblers will be assemblers with that recipe set, and the output belts may be "belt with iron gear on right side".

the end state here will be be meing able to request a blueprint that creates an object

## 4.0 Blueprint objects (03_blueprint_objects)

    cd 03_blueprint_objects && ../.venv/bin/python make.py <item> <rate> [--recipe NAME] [--machine NAME] [-o DIR] [--no-render]

Writes `out/<item>.module.json`, `out/<item>.txt` (vanilla blueprint string, importable), `out/<item>.png` (via 02 renderer with port markers).

### 4.1 Model (`module.py`)

- `Port`: `io` (in/out), `kind` (belt/pipe), `item`, `lane` (left/right/both), `x`,`y` (tile, module-local, (0,0) top-left), `direction` (0 N, 4 E, 8 S, 12 W, flow direction at the tile), `rate` (items/s). One port = one lane of one tile; two ports may share a tile.
- `Module`: `name`, `width`, `height`, `entities`, `tiles`, `inputs`, `outputs`, `notes`. Ports are listed left to right along the bottom edge; first input at bottom-left, first output at bottom-right.
- `Port.compatible(other)`: OUT feeds IN iff same kind, item, lane.
- `Module.to_string()`: vanilla blueprint; the `description` carries `SIZE WxH` and one `PORT IN|OUT kind item lane (x,y) DIR rate/s` line per port, so `Module.from_string()` recovers ports after a trip through the game. `Module.check()` validates port placement and entity overlap.
- No modded entities. A "belt with iron plate on the left lane" is a vanilla belt entity plus a `Port` record; the renderer draws the port (green IN / orange OUT frame, item icon on the lane half, tag).

### 4.2 Generator (`make.py`)

Recipe and machine data from `01_recipe_generatpr/recipe.py` (imported). Machine count `n = ceil(crafts/s * time / speed)`.

`--layout template` (default, `templates.py`): cells from `03_samples/<N>_to_1.md`, N = ingredient count (1-4).

- Template anatomy: inputs enter the bottom row northbound (left to right = ingredient order); bends under the machine merge them onto lanes (N=2: in1 -> left lane, in2 -> right lane of the pickup belt; N=3,4: second belt column reached by a long-handed inserter); output exits the bottom-right southbound on the far lane (= left lane of a southbound belt).
- Scaling: the machine's 3 rows + the pole row form a 4-row cell. Cells 1..n-1 are stacked above the template: straight belts in every column that carries a belt in the template's top row, non-belt entities of the machine rows copied at the same offsets, pole copied, consecutive poles joined by copper wire.
- Machine: the sample's `assembling-machine-1` is replaced by the category default (`assembling-machine-2` for crafting, `electric-furnace` for smelting) or `--machine`; all are 3x3. `--belt` swaps the belt tier (geometry unchanged, capacities scaled).
- Port capacities (yellow): N=1 [15], N=2 [7.5, 7.5], N=3 [15, 7.5, 7.5], N=4 [7.5 x4]; output 7.5. Exceeding prints a WARNING line into the module notes; the module is still generated.
- IN ports are `lane=both` (the bends accept a full belt); OUT is `left`. `Port.compatible` treats `both` as accepting any lane, so `copper-cable OUT -> electronic-circuit IN` is compatible.

Verified: `copper-cable 3` (1_to_1, 2x AM2), `electronic-circuit 2` (2_to_1, 2x AM2), `engine-unit 0.2` (3_to_1, 4 cells stacked), `assembling-machine-2 0.1` (4_to_1); all round-trip through the blueprint string with ports, wires, and recipes intact.

`--layout row`: the earlier horizontal layouts. Belt tier = smallest whose lane capacity covers the largest lane rate (7.5 / 15 / 22.5 / 30 per lane); error above turbo.

| Ingredients | Size | Rows | Ports |
|---|---|---|---|
| 1 item | 3n x 5 | machines 0-2; inserter, pole, inserter 3; belt east 4 | IN ingredient left lane (0,4) E; OUT product right lane (3n-1,4) E |
| 2 items | 3n x 6 | machines 0-2; long-handed, pole, inserter 3; output belt east 4 turning south at column 3n-1; input belt east 5, ends at column 3n-3 | IN ing1 left, IN ing2 right at (0,5) E; OUT product right lane (3n-1,5) S |

Machines: `assembling-machine-2` for crafting categories, `electric-furnace` for smelting (no recipe field). Inserter `direction` = pickup side (8 = from belt below, 0 = from machine above). Output inserters drop on the far lane = right lane of an eastbound belt.

LIMITS: no fluids, max 2 ingredients, no module composition yet, long-handed inserter throughput (1.2 items/s) is not checked against the ingredient rate, pole coverage assumes small poles every 3 tiles in row 3.

Verified: `iron-gear-wheel 5` (4 AM2, fast belt), `electronic-circuit 2` (2 AM2), `iron-plate 10` (16 electric furnaces, 48x5); round-trip string -> Module preserves ports and size; `engine-unit` (3 ingredients), `plastic-bar` (chemistry), `copper-cable 40` (lane cap) exit with a message.

NOTE: every generated OUT port is on the right lane (inserters drop on the far lane), while the 1-ingredient layout takes its IN on the left lane so the same belt can carry both. `iron-plate OUT (right)` -> `iron-gear-wheel IN (left)` is therefore reported incompatible. Composing modules needs a lane-swap step (sideload or lane-swap adapter module); not built yet.
