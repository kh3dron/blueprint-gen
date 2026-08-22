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

  - [ ] pack lanes tighter (sample tunnels adjacent lanes under splitters; current bus uses 3 rows per lane)
  - [ ] power reach into nested composites (gap pole cannot reach a sub-composite's poles)

A couple improvements to the bus use:

- [x] if we're using an item as an input, we don't need to use the splitter to leave a forward lane, we can just consume the entire lane (last consumer turns the lane north; earlier consumers still split)
- [x] similarly, if there's no horizontal lane, a vertical lane does not need to use an underground belt (military factory: 292 -> 90 undergrounds, 14 -> 2 splitters)
