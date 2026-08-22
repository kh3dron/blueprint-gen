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
  - [x] narrower: modules on both sides of the bus (south side mirrored vertically, pulls/pushes mirrored, pole networks bridged; `--one-sided` to disable); module gap 2; lane ducks may use faster underground tiers for 5-10 tile runs. Width: military 1/s 106 -> 86, 10/s 368 -> 260, inserters 50 -> 40. (`--cells N` / `--tune` still available to trade width for height)
  
  - [ ] power reach into nested composites (gap pole cannot reach a sub-composite's poles)
  - [ ] better use of both sides of a lane
  - [ ] flip components horizontally to match
  - [ ] liquids & oil
