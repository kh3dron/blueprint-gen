Factorio recipe tools

- [x] 01: recipe calculator
  - [x] for a given item, calculate the rates of all intermediate parts

- [x] 02: visualize blueprints

- [x] 03: compile designs into blueprints
  - works for small, simple prints

- [x] 04: bus module (`03_blueprint_objects/bus.py`, `compose.py`; spec in `03_blueprint_objects/README.md`)
  - [x] a new intermediate method / type called "bus";

the BUS is an organizational method for transporting types of resources in and out of the base.

- [x] bus: push, bus: merge, bus: lanes
- [x] needs to be able to skip over / under lanes

another thing: we can now generate "objects" which themselves are comprised of objects and BUSses. we should be able to stitch together any number of objects

- [x] `compose.py <name> item=rate ... | x.module.json ...` -> one Module (object + sub-bus); composites nest (`out/inserters-nested`)
- [x] `compose.py <item> <rate>` -> whole subfactory from raw materials via the 01 calculator (`out/military-science-pack-factory`: 9 modules, 13 lanes, inputs iron-ore/copper-ore/coal/stone)
- [ ] pack lanes tighter (sample tunnels adjacent lanes under splitters; current bus uses 3 rows per lane)
- [ ] power reach into nested composites (gap pole cannot reach a sub-composite's poles)

- [ ] get game sprites
- [ ] get game fact tables
