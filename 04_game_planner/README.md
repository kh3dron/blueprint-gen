# 04_game_planner

What to build next, from a notebook you keep by hand. All commands from this directory with
`../.venv/bin/python`.

## 1.0 Files

| File | Role |
|---|---|
| `notebook.md` | the whole state of the game: one move per line, append-only, hand-editable |
| `ledger.py` | the notebook's grammar, and what it adds up to (production, consumption, research) |
| `tech.py` | technology tree from `data/base/prototypes/technology.lua`: researched, available, unlocked recipes, machine and belt tiers |
| `plan.py` | CLI: `status`, `next`, `accept`, `log`, `ladder` |
| `out/plan/` | blueprints the planner generated, numbered by move (git-ignored) |

## 2.0 The notebook (`ledger.py`)

    | # | date       | move     | what               | rate  | note                                    |
    |---|------------|----------|--------------------|-------|-----------------------------------------|
    | 1 | 2026-08-23 | research | steam-power        |       |                                         |
    | 4 | 2026-08-23 | have     | iron-ore           | 20/m  |                                         |
    | 5 | 2026-08-23 | build    | iron-plate         | 20/m  | out/plan/05-iron-plate.txt [am-2 belt]  |

| Move | Meaning |
|---|---|
| `research <tech>` | that technology is researched; unlocks recipes and tiers |
| `build <item> <rate>` | a factory making `<item>` at `<rate>`. Its recipe's ingredients are consumed at the matching rate — that is the whole consumption model |
| `scale <item> <rate>` | more of an existing build; same arithmetic, different word so the report can tell them apart |
| `have <item> <rate>` | `<rate>` arrives from outside the ledger: ore from miners, hand-built smelting, a chest you keep filling. Nothing is consumed for it |
| `target <item> <rate>` | overrides the milestone ladder for that item |

Rates are `12/s` or `600/m`. The planner only reads and appends; when the ledger drifts from the game,
edit the file. `--notebook FILE` runs against another notebook, one per save game.

## 3.0 Where the next move comes from (`plan.py`)

    plan.py status                 rates, research, tiers, which milestone is in progress
    plan.py next [--accept]        the next move, with its blueprint; --accept writes it down
    plan.py accept                 write down the move `next` last printed
    plan.py log <move> <what> [rate] [note]        append a move yourself
    plan.py ladder                 the milestone ladder and how far along it you are

1. **Goal.** The ladder is `LADDER` in `plan.py`: automation, logistic, military and chemical science
   at 10/min, then all six packs at 100/min. The first rung the ledger does not build at its target
   rate is the goal. A `target` line overrides a rung.
2. **Research.** If the goal's recipe is locked, or any recipe on the way to it is, or there is no
   machine researched to build it in, the move is the next researchable technology toward it —
   prerequisites first. Trigger technologies (2.0: craft 50 iron plate, craft a lab) are reported as
   the thing to do, not as science. A technology whose packs are not in production yet comes back as
   `BLOCKED`, naming the pack to build first — unless the pack it costs is the very pack it would let
   you build, which is the opening bootstrap, and then the move says to hand-craft it into a lab once.
3. **Demand.** Otherwise the recipe tree of every ladder rung up to the goal is expanded — an earlier
   rung keeps consuming while you build the next one — and compared with the ledger. An item is short
   when it is produced more slowly than the goal needs it *or* than the builds already in the ledger
   consume it.
4. **Pick.** The move is the largest shortfall whose own ingredients are not themselves short, so
   producers always come before consumers. An item already in the ledger is a `scale`, a new one is a
   `build`, an item nothing here can make is a `supply` (mine it, then log it as `have`).
5. **Print.** A build or scale runs `03_blueprint_objects/make.py` at the researched machine and belt
   tier and keeps the result as `out/plan/<move>-<item>.txt`, so a later scale never overwrites a print
   you already placed. The tier used is recorded in the notebook line.
6. **Upgrades.** Every build records the tier it was made at, so once a better one is researched the
   report says what rebuilding would buy: `belt: 35 build(s) on transport-belt, fast-transport-belt is
   researched (2x each, no extra ground)`.

    $ ../.venv/bin/python plan.py next
    NEXT MOVE  #69
    SCALE    iron-gear-wheel 1.5/s
      why    automation-science-pack at 100/min: iron-gear-wheel short 1.5/s of 1.67/s needed
      needs  iron-plate +3/s
      print  out/plan/69-iron-gear-wheel.txt   iron-gear-wheel 1.5/s: 7x4 tiles, 12 entities
      tiers  assembling-machine-2, transport-belt, stone-furnace
      UPGRADE belt: 35 build(s) on transport-belt, fast-transport-belt is researched (2x each)

    [a]ccept -> appends to notebook.md   [s]kip   [w]hy

`w` prints the goal's whole requirement list against what the ledger makes, biggest gap first.

## 4.0 What it does from an empty notebook

The first sixty-odd moves of a fresh game, in order (`plan.py next --accept` in a loop):

     1 research steam-power                 unlocked by crafting 50 iron-plate
     2 research electronics                  unlocked by crafting 10 copper-plate
     3 research automation-science-pack      unlocked by crafting a lab
     4 supply  iron-ore 20/m                 place miners, then log it as `have`
     5 build   iron-plate 20/m
     6 research automation                   10 red science and nothing makes it: hand-craft them once
     7 build   iron-gear-wheel 10/m          now there is an assembling machine to build it in
     8 supply  copper-ore 10/m               9 build copper-plate 10/m
    10 build   automation-science-pack 10/m  first rung done
    11 research logistic-science-pack        ... belts, inserters, green circuits, green science
    ... then military: steel, walls, grenades, piercing rounds; then oil: refinery, pipes, engine
    units, sulfur, plastic, red circuits, and chemical science at move 66.

## 5.0 Limits

- The ledger is what you tell it. Nothing reads the game, so a build you place and forget to write
  down is invisible, and a `build` line assumes the factory actually runs at its rate.
- Only items and research. No power, no mining throughput or ore patch sizes, no roboport coverage,
  no mall (belts, inserters and poles for your own use are not modelled as consumers).
- One move at a time. It does not plan a whole stage, batch a shopping list, or know that two moves
  could be built as one blueprint.
- Blueprints come from `make.py`, so they are single-recipe modules with ports, not a bus. For a whole
  stage in one print, use `03_blueprint_objects/compose.py <item> <rate>` directly.
- `LADDER` stops at 100/min of the six packs; there is no rocket goal yet.
- Smelting prints use an electric furnace: the cell templates are built around 3x3 machines and a
  stone or steel furnace is 2x2. Until `advanced-material-processing-2` the move says so and you place
  furnaces by hand; the rates in the notebook stay correct either way.
- Recipe choice is the calculator's: the recipe named after the item, else the non-recycling one with
  the fewest outputs. Oil is planned as advanced processing with full cracking, as in `compose.py`.
