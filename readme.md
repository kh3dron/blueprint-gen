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

- [x] 05: game planner (`04_game_planner/plan.py`, notebook + ladder; spec in `04_game_planner/README.md`)
  - [x] told what to build in what order: `plan.py next` -> one move, with the blueprint
  - [x] tracks total consumption and production, from a hand-kept notebook of moves
  - [x] tracks research: what is researched, what is available, what it unlocks
  - [x] tracks tier upgrades (belts, assemblers, furnaces) and what rebuilding would buy
  - [x] scale out (`scale`), build new (`build`), supply (`have`), research, upgrade
  - [ ] power, mining throughput, roboport coverage, malls
  - [ ] rocket goal above 100/min of the six packs

## GAME LOOP

- States to track:
  - best tier available of: assemblers, belts
  - Power construction style
  - raw resource input rates
  - current SPM rates

- Control loop: what to solve
  - unlock more science packs
    - 10SPM red, green, black, blue
    - 100SPM red, green, black, blue, purple, yellow

- Available options
  - Construct a new module
  - Improve an existing module
    - Replace: deconstruction & reconstruction
    - Upgrade: construct an upgrade planner (building levels, quality, modules)
  - construct new power infra
    - when within 110% of max load, construct to 150%

- Candidate search for: power pole and roboport coverage
  - global var for best power poles available

- Instrumental production: bots, malls

rs = module.red_science(10)
gs = module.green)science(10)

rs.throughput() ##prints 10
rs.upgrade(fast-transport-belts)
rs.throughput() # prints 15
