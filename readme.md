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
  - [x] liquids, liquid + solid recipes (processing units)
  - [x] 4-ingredient recipes (science packs, robot frames)
  - [x] readable run report, `-v` for the full tables
  - [x] recursive layout: `--nested` for more internal busses  
- [x] test suite: `03_blueprint_objects/bench.py`

- [ ] better use of both sides of a lane
- [ ] flip components horizontally to match
- [ ] space-age fluid machines (foundry, biochamber, electromagnetic plant, cryogenic plant)
- [ ] mirror chemical plants / refineries onto the south side (2.0 per-entity mirror flag)

- [ ] get game state:
  - what is the best tier of assembler / inserter available
- [ ] maintain a list of what submodules are currently in use on the map (including recursively)
- [ ] when new techs are unlocked, track what upgrades can be made to past items

## GAME LOOP

- [ ] unlock more science packs
  - 10SPM red, green, black, blue
  - 100SPM red, green, black, blue, purple, yellow
- [ ] expand factory: scale out OR scale up
- [ ] instrumental production (malls)
- [ ] power: when within 20% util, double capacity

- [ ] maintain total roboport coverage
