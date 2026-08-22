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

  - [x] pack lanes tighter: one row per lane; vertical chains run straight and every lane ducks (underground) under foreign tiles in its row, runs limited by the belt's underground span; pull columns placed by candidate search with rollback, `(spacing, gap)` searched (military 1/s: 90x83 -> 106x58; 10/s: 295x234 -> 335x173)
  - [ ] power reach into nested composites (gap pole cannot reach a sub-composite's poles)
  - [ ] better use of both sides of a lane
  - [ ] flip components horizontally to match
