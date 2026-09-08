Factorio recipe tools

Current research direction: [project review](RESEARCH_REVIEW.md).
New progression work lives separately in [05_advisor_experiment](05_advisor_experiment/README.md),
with [scenario results and next experiments](05_advisor_experiment/EXPERIMENTS.md).

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

- [x] 05: game planner (`04_game_planner/game.ipynb`; spec in `04_game_planner/README.md`)
  - [x] state as python objects in a notebook: `module.red_science(10)`, `f.add(...)`, re-run a cell
  - [x] told what to build in what order: `f.next()` -> one move, `f.apply(move)` takes it
  - [x] tracks total consumption and production across the factory
  - [x] tracks research: what is researched, what is available, what it unlocks
  - [x] `throughput()` = machines vs belts, `upgrade()` a tier in place, `rebuild()` to shrink
  - [x] tier upgrades (belts, assemblers, furnaces) and what upgrading in place would buy
  - [ ] power, mining throughput, roboport coverage, malls
  - [ ] rocket goal above 100/min of the six packs
  - [ ] flow solve: nothing throttles a module when something upstream is short

- [x] 06: isolated advisor foundation (`05_advisor_experiment/`)
  - [x] pinned base-game rules and validated snapshots, independent of the older tools
  - [x] supply/fuel/power-constrained flow bound, shared ingredients and coproduct accounting
  - [x] finite-inventory construction checklists and trigger/research bootstrap advice
  - [x] completion requires fresh observed production; advice never changes the snapshot
  - [x] nine reproducible snapshot scenarios and behavioral tests
  - [x] read-only game observer and capture-specific importer with resolved runtime prototypes
  - [x] headless Factorio 2.1.16 counter/import checks ([workflow](05_advisor_experiment/OBSERVER.md))
  - [x] resource/connection survey, finite hand-mining targets, and SVG maps ([workflow](05_advisor_experiment/SURVEY.md))
  - [x] native walking approaches and exact hand-mining instructions, with actual character replay ([workflow](05_advisor_experiment/ROUTES.md))
  - [x] configurable flat proving ground with rectangular finite deposits ([workflow](05_advisor_experiment/PROVING_GROUND.md))
  - [ ] automatic mining layouts, placement, material routing, and power-construction methods
  - [ ] validate the full finite-inventory opening in Factorio

- [x] 07: declarative factory prototype ([06_declarative_factory](06_declarative_factory/README.md))
  - [x] typed ports, stable nested module addresses, explicit placement reservations and connections
  - [x] additive blueprint plans, entity bills, migration refusals, and observed drift checks
  - [x] engine test: attach a second gear module, preserve 28 entities, add 18, repeat with no duplicates
  - [ ] general shared-bus taps, live deployment refresh, verified service rates and player construction steps

- [x] 08: finite opening execution ([07_bootstrap_executor](07_bootstrap_executor/README.md))
  - [x] advisor goal → runtime materials bill → surveyed targets → native walking and timed mining
  - [x] costed declarative furnace placement, checked transfers, 50 actual plates and observed steam-power unlock
  - [x] repeat placement without duplication; blocked/unpaid actions refused; relocated iron patch also passes
  - [x] empty furnace retained for the next copper-smelting bill, with no invented production
  - [x] unthrottled engine benchmarks with separate simulation, update and process timing
  - [x] separate persistent execution prototype in `08_live_executor/`
  - [ ] interactive player building, power/lab construction and sustained red science

- [x] 09: persistent execution and recordings ([08_live_executor](08_live_executor/README.md))
  - [x] paused observe/plan/act loop over local RCON, running at configurable 1×/10×/40× speed
  - [x] real save/restart after steam power, preserved furnace identity, duplicate/stale command checks
  - [x] copper smelting and native lab handcrafting from finite stock; missing lab research credit remains explicit
  - [x] reusable GIF/MP4 recorder with observed positions, factory state, current action and progress
  - [x] player-attributed crafting and native game footage in separate `09_player_capture/`
  - [ ] general driver recovery
  - [ ] [hierarchical goal/subgoal planning stack viewer](08_live_executor/TODO.md)

- [x] 10: player attachment and native recordings ([09_player_capture](09_player_capture/README.md))
  - [x] preserve the starter character/inventory; native lab crafting gets force credit and unlocks red science
  - [x] same-version headless control retains the missing-credit result
  - [x] native PNG capture and GIF/MP4 export with synchronized action/state overlays and source hashes
  - [x] player cursor placement and powered lab in separate `10_powered_lab/`
  - [ ] automated extraction/transport and sustained 10 red science/min

- [x] 11: native construction and powered research ([10_powered_lab](10_powered_lab/README.md))
  - [x] seven paid cursor builds, native build events, refusal checks and repeat lab deployment
  - [x] observed shoreline → declared power island → runtime bill → walked player construction
  - [x] ten red science packs consumed by a steam-powered lab; Automation research unlocks
  - [ ] continuous fuel, automated ore/plate/ingredient delivery and measured science assembly

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
