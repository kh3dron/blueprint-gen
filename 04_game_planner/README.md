# 04_game_planner

Your game as Python objects in a notebook: modules you size and upgrade, a factory that adds them up,
and the next move. Open `game.ipynb`; `../.venv/bin/python plan.py` is the terminal shortcut.

There is no jupyter in `.venv` — `pip install jupyterlab` (or open the notebook from an environment
that has one, pointed at this directory).

## 1.0 Files

| File | Role |
|---|---|
| `game.ipynb` | the notebook: a state cell you keep editing, then status, next move, throughput, upgrades, blueprints |
| `factory.py` | `Rate`, `Module`, `Factory`, and the `module` namespace |
| `planner.py` | the milestone ladder and the next move |
| `tech.py` | technology tree from `data/base/prototypes/technology.lua`: researched, available, unlocked recipes, tiers |
| `plan.py` | CLI over a saved game: `status`, `next [--apply]`, `ladder`, `upgrades` |

## 2.0 The objects (`factory.py`)

```python
from factory import Factory, module

f  = Factory(name='my-game')
f.research('steam-power', 'electronics', 'automation-science-pack', 'automation')
f.have('iron-ore', 120)                 # per minute, from miners
f.add(module.iron_plate(120), module.gear(30), module.red_science(10))
```

Rates are **per minute** unless you pass a string (`module.iron_plate("2/s")`). Every rate that comes
back is a `Rate` — a float of items per second that prints both ways: `900/min = 15/s`.

`module.<anything>` builds a module for that item: `module.iron_gear_wheel(30)`, or the short names
`red_science`, `green_science`, `blue_science`, `purple_science`, `yellow_science`, `green_circuit`,
`red_circuit`, `blue_circuit`, `gear`, `cable`. Tab-completion lists every item.

| Module | |
|---|---|
| `throughput()` | what the hardware can do: the lesser of `capacity()` (machines) and `port_limit()` (belts) |
| `output()` | what it contributes to the factory: the rate you asked for, or `throughput()` if the hardware cannot reach it |
| `headroom()` | the difference. Raise `want` or `rebuild()` to use it |
| `limited_by()` | `machines` or `belts (transport-belt)` |
| `inputs()` | item -> Rate drawn at the rate it runs |
| `upgrade('fast-transport-belt', 'assembling-machine-3')` | same machines, same ground, better tier. A machine that cannot craft the recipe is refused |
| `rebuild(want=None)` | re-size to a rate with the tiers it has now |
| `blueprint(path=None)` | the vanilla blueprint string at the current tiers |

A module is fixed hardware — as many machines as its rate needed, in as many columns as the belts of
the day required — so upgrading changes what it does without rebuilding anything:

```python
g = module.gear(900)
g.throughput()                       # 900/min = 15/s   limited by machines
g.upgrade('assembling-machine-3')
g.throughput()                       # 900/min = 15/s   now limited by belts
g.upgrade('fast-transport-belt')
g.throughput()                       # 1500/min = 25/s
g.rebuild()                          # 900/min from 6 machines in 1 column instead of 10 in 2
```

| Factory | |
|---|---|
| `add(*modules)`, `have(item, rate)`, `research(*techs)`, `target(item, rate)`, `remove(m)` | build the state up; each returns the factory so calls chain |
| `production()`, `consumption()`, `net()` | item -> Rate |
| `status()`, `table()`, `ladder()`, `upgrades()` | reports that print themselves in a cell |
| `next()`, `apply(move)` | the next move, and taking it |
| `save(path=None)`, `Factory.load(path)` | JSON, for a fresh kernel |

## 3.0 Where the next move comes from (`planner.py`)

1. **Goal.** `LADDER`: automation, logistic, military and chemical science at 10/min, then all six
   packs at 100/min. The first rung the factory does not make at its target rate is the goal;
   `f.target(item, rate)` overrides one.
2. **Research.** If the goal's recipe is locked, or one on the way to it is, or no machine is
   researched to build it in, the move is the next researchable technology toward it. Trigger
   technologies are reported as the thing to do (`craft 50 iron-plate`). A technology whose packs are
   not in production is `BLOCKED` — unless the pack it costs is the pack it would let you build, which
   is the opening bootstrap, and then it says to hand-craft them into a lab once.
3. **Demand.** Otherwise the recipe tree of every rung up to the goal is expanded — earlier rungs keep
   consuming while you build the next — and compared with the factory. An item is short when it is
   produced more slowly than the goal needs it, or than the modules already draw.
4. **Pick.** The largest shortfall whose own ingredients are not short, so producers come before
   consumers. Already in the factory is a `scale`, new is a `build`, unmakeable is a `supply`.
5. **Upgrades.** `f.upgrades()` compares each module's tier against the best researched and adds up
   what upgrading in place would buy — and says so when a module is machine-limited and would gain
   nothing from a belt.

From an empty factory the first moves are the real opening: research steam-power (craft 50 iron
plate), electronics (craft 10 copper plate), automation-science-pack (craft a lab), supply iron ore,
build iron plate, research automation — 10 red science and nothing makes it, so hand-craft them once —
build gears, supply copper ore, build copper plate, build red science. Then green, military, and oil.

## 4.0 Limits

- The factory is what you tell it. Nothing reads the game.
- A module contributes the rate you asked for, not its capacity, so the arithmetic is what you
  designed; `headroom()` is the slack. There is no flow solve: nothing throttles a module because
  something upstream is short — that shows up as a shortfall instead.
- Only items and research. No power, mining throughput, roboport coverage or mall.
- Smelting prints use an electric furnace: the cell templates are built around 3x3 machines and a
  stone or steel furnace is 2x2. The move says so, and the rates hold either way.
- Blueprints are single-recipe modules with ports, not a bus. For a whole stage in one print use
  `03_blueprint_objects/compose.py <item> <rate>`.
- `LADDER` stops at 100/min of the six packs; no rocket goal yet.
