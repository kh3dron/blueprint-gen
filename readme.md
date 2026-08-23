Factorio recipe tools

- [x] 01: recipe calculator
  - [x] for a given item, calculate the rates of all intermediate parts

- [x] 02: visualize blueprints

- [x] 03: compile designs into blueprints
  - works for small, simple prints

- [x] 04: bus module (`03_blueprint_objects/bus.py`, `compose.py`; spec in `03_blueprint_objects/README.md`)
  - [x] a new intermediate method / type called "bus"
  - [x] bus: push, bus: merge, bus: lanes
  - [x] needs to be able to skip over / under lanes
  - [x] can scale submodules OUT if belt lane capacity exceeded
  - [x] pack lanes tighter
  - [x] option to ignore raws: `--raw iron-place --raw copper-place`
  - [x] space for roboports: `--roboports`
  - [x] allow building on both sides of the bus: `--one-sided`
  - [x] liquids: fluid cells generated from prototype fluid boxes (`fluidcells.py`: chemical plant, refinery, assembling machine), pipe lanes on the bus (tees, pipe-to-ground crossings), oil planner (advanced processing + full cracking)
  - [x] recipes mixing solid and liquid ingredients in one cell (`crafting-with-fluid`, chemistry and oil-processing with item ports): up to 4 item belts around the fluid mains. `compose.py processing-unit 10 --raw iron-plate --raw copper-plate --roboports --belt fast-transport-belt` -> 1,410x320, 68,169 entities, 210 roboports
  - [x] 4-ingredient recipes over the bus (`flying-robot-frame`, science packs): the pull jog ducks under the module's own push chain and the column search falls back west. `compose.py utility-science-pack 1 --raw iron-plate --raw copper-plate --belt turbo-transport-belt` -> 240x208, 5,842 entities
  - [x] readable run report: `[n/m] LABEL` steps, port summary, grouped warnings, `-v` for the full tables

  - [ ] better use of both sides of a lane
  - [ ] flip components horizontally to match
  - [ ] space-age fluid machines (foundry, biochamber, electromagnetic plant, cryogenic plant)
  - [ ] mirror chemical plants / refineries onto the south side (2.0 per-entity mirror flag)
