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

Machine count `n = ceil(crafts/s * time / speed)`; machine = category default (`assembling-machine-2`, `electric-furnace`) or `--machine`. Port capacities (yellow belt): N=1 [15], N=2 [7.5, 7.5], N=3 [15, 7.5, 7.5], N=4 [7.5 x4], output 7.5; over capacity adds a WARNING note.

## 4.0 Bus and composition (`bus.py`, `compose.py`)

    compose.py <name> <spec>... [--belt NAME] [--export ITEM]... [-o DIR] [--no-render]
    compose.py <item> <rate>  [--raw ITEM]... [--belt NAME] [-o DIR] [--no-render]

`<spec>` = `path.module.json` or `item=rate`. Modules are topologically ordered (producers west of consumers). Items consumed but not produced = external inputs; produced but not consumed (or `--export`) = outputs.

Factory mode (second form): the recipe tree of `<item>` is walked with `01_recipe_generatpr/recipe.py` (same recipe choice rules: recipe named after the item, else non-recycling recipe with fewest outputs), rates are summed per intermediate, and one module is generated per intermediate at its total. External inputs = `RAW` resources (ores, coal, stone, crude-oil, water, ...), `--raw` items, and anything the templates cannot build (fluid ingredient/result, >4 ingredients, category without a 3x3 machine, e.g. plastic-bar, sulfur, processing-unit); each is printed with its reason. Output name `<item>-factory`.

| Command | Result |
|---|---|
| `compose.py military-science-pack 1` | 9 modules (iron-plate 5.75/s, copper-plate, steel-plate, stone-brick, firearm-magazine, piercing-rounds-magazine, grenade, stone-wall, military-science-pack), 13 lanes, 90x83, 1,398 entities; IN iron-ore 5.75/s, copper-ore 0.5/s, coal 5/s, stone 10/s; OUT 1/s |
| `compose.py military-science-pack 10` | same modules scaled, 90x411, 5,592 entities; 5 lanes over yellow-belt capacity (WARNINGs) |
| `compose.py electronic-circuit 2 --raw iron-plate --raw copper-plate` | plates fed from outside instead of smelted |

Geometry (composite-local tiles, y down; `E` external inputs, `L` lanes, `R = 4`, `GAP = 2`):

| Region | Columns | Rows |
|---|---|---|
| External input risers | `0..E-1`, lane j at column j, northbound | bottom row up to `belt(j)`, N->E curve |
| Modules | from `E+GAP`, `GAP` apart, bottom-aligned on `by = max(height)-1` | `0..by` |
| Routing band | | `by+1 .. by+R` |
| Bus | | lane j: `s_a = B0+3j`, `s_b = B0+3j+1`, `belt = B0+3j+2`; `B0 = by+R+1` |
| Export drops | `x_max+3+(L-1-j)`, deeper lanes further west, southbound | `belt(j)` to bottom row |

Lane order: external inputs (order of first use), then produced items (production order). Non-exported lanes end at their last consumer.

| Operation | Mechanism |
|---|---|
| pull (input k of a module at x0) | `bc = x0+2k`. If this is the last consumer of the lane (nothing east of `bc`: no pull, merge, or export), `belt(j)` itself turns north at `bc` and the whole lane is consumed. Otherwise a splitter on `belt(j)` at `bc-1`; the branch exits east into `(bc, s_b)` and turns north. Then up the routing band, jog on row `B0-1-k` to the port column, feed the port from behind |
| push (lane starts here) | port belt south to `s_b(j)`; S->E curve at `belt(j)` |
| merge (lane exists) | same descent, then east into the upper input of a splitter sitting on the lane; its upper output tile is left empty so the whole flow continues on the lane (full merge, as in `samples/bus_merge.md`) |
| crossing | a vertical chain tunnels (underground in on the tile before the belt row, out on the tile after) only where the crossed lane has a belt at that column; elsewhere it is a plain belt. Any depth |
| power | medium pole in each inter-module gap on row `by`, wired to each neighbour's nearest pole within 9 tiles |

Tile conflicts raise `ValueError` (grid occupancy is checked for every placement). A consumer placed west of its lane's start is rejected. Lane rate above belt capacity (15/30/45/60 per belt) prints a WARNING.

Verified objects in `out/`:

| Name | Specs | Result |
|---|---|---|
| `circuits` | `copper-cable=6 electronic-circuit=2` | 4 lanes, 23x25, IN copper-plate 3/s + iron-plate 2/s, OUT electronic-circuit 2/s |
| `inserters` | `inserter=1 electronic-circuit=1 iron-gear-wheel=1 copper-cable=3` | 6 lanes, 42x27, 3-input module pulling from 3 lanes |
| `inserters-nested` | `out/circuits.module.json iron-gear-wheel=1 inserter=1` | composite inside composite, 49x44 |

All round-trip through the blueprint string with ports, wires, and recipes intact.

LIMITS
- Port spacing assumes template port columns satisfy `px_k <= 2k+2` (true for the four samples).
- One row of modules per bus (no vertical stacking of modules).
- 3 rows per lane; the reference sample packs tighter by tunnelling adjacent lanes under splitters.
- A pull splitter diverts up to half the lane into the branch; the branch backs up when the module is full, which is the intended behaviour.
- The gap pole cannot reach a nested composite's poles (they sit above its internal bus); WARNING printed, connect in game.
- No fluids; belts only.
