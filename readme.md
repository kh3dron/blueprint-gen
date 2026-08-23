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
  
  - [ ] better use of both sides of a lane
  - [ ] flip components horizontally to match
  - [x] liquids & oil: fluid cells generated from prototype fluid boxes (`fluidcells.py`: chemical plant, refinery), pipe lanes on the bus (tees, pipe-to-ground crossings), oil planner (advanced processing + full cracking). `compose.py advanced-circuit 1` -> red circuits from ore, crude oil and water (105x75)
