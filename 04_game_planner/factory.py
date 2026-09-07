"""Your game as Python objects: modules you can size, upgrade and ask for throughput, in a Factory
that knows what it all adds up to.

    from factory import Factory, module

    f  = Factory().research("automation", "logistics-2").have("iron-ore", 120)
    rs = module.red_science(10)          # 10 per minute
    f.add(rs)

    rs.throughput()                      # 10/min = 0.167/s
    rs.upgrade("fast-transport-belt")
    rs.throughput()                      # what the same machines push once the belts keep up

Rates are per MINUTE by default, because that is how science and most planning is talked about; pass a
string for anything else (`module.iron_plate("2/s")`). Every rate that comes back is a `Rate`, which is
a float of items per second that prints as both.

A module is a fixed piece of factory: as many machines as its requested rate needed, split into as many
columns as the belts of the day required. `throughput()` is what that hardware can actually do now —
the lesser of what the machines can craft and what the belts on its ports can carry — so upgrading a
belt or a machine tier changes it without rebuilding anything.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "03_blueprint_objects"))
import fluidcells                                  # noqa: E402
import make as mk                                  # noqa: E402
import templates                                   # noqa: E402
from tech import Tech, TIERS                       # noqa: E402

_RT = None
_RECIPES = None
_BY_PRODUCT = None
_TECH = None

# machines the cell generators can actually place: the templates are built around 3x3 machines, so a
# stone or steel furnace (2x2) has no cell and smelting prints always use the electric furnace
SUPPORTED = set(mk.MACHINE_SPEED) | set(fluidcells.MACHINES)

# which tier family a recipe's machines come from; anything else is a fluid machine
FAMILY = {"crafting": "assembler", "advanced-crafting": "assembler", "basic-crafting": "assembler",
          "crafting-with-fluid": "assembler", "smelting": "furnace"}

ALIASES = {"red_science": "automation-science-pack", "green_science": "logistic-science-pack",
           "black_science": "military-science-pack", "military_science": "military-science-pack",
           "blue_science": "chemical-science-pack", "chemical_science": "chemical-science-pack",
           "purple_science": "production-science-pack", "production_science": "production-science-pack",
           "yellow_science": "utility-science-pack", "utility_science": "utility-science-pack",
           "green_circuit": "electronic-circuit", "red_circuit": "advanced-circuit",
           "blue_circuit": "processing-unit", "gear": "iron-gear-wheel", "cable": "copper-cable"}


def data():
    """(recipe tool, recipes, by_product, Tech), loaded once."""
    global _RT, _RECIPES, _BY_PRODUCT, _TECH
    if _RT is None:
        _RT = mk.load_recipe_tool()
        _RECIPES = _RT.load_recipes()
        _BY_PRODUCT = _RT.build_index(_RECIPES)
        _TECH = Tech(_RECIPES)
    return _RT, _RECIPES, _BY_PRODUCT, _TECH


class Text(str):
    """A block of text that shows itself as-is in a notebook cell instead of as a quoted string."""

    def __repr__(self):
        return str(self)


class Rate(float):
    """Items per second, printed per minute as well because that is how factories are talked about."""

    def __repr__(self):
        return f"{self * 60:.4g}/min = {float(self):.4g}/s"

    __str__ = __repr__

    @property
    def per_min(self):
        return float(self) * 60


def rate(v, default="m"):
    """A number (per minute by default) or a string like `2/s`, `120/m` -> Rate (items per second)."""
    if isinstance(v, str):
        s = v.strip().rstrip("s" if v.strip().endswith("/s") else "")
        if v.strip().endswith("/s"):
            return Rate(float(v.strip()[:-2]))
        if v.strip().endswith(("/m", "/min", "spm")):
            return Rate(float(s.rstrip("/minp")) / 60)
        return Rate(float(v) / 60 if default == "m" else float(v))
    return Rate(float(v) / 60 if default == "m" else float(v))


def supported_tier(family, best=None):
    """The best machine of `family` the generators can place, at or below `best`."""
    names = [t for t in TIERS[family] if t in SUPPORTED]
    if best in TIERS[family]:
        names = [t for t in names if TIERS[family].index(t) <= TIERS[family].index(best)] or names[:1]
    return names[-1] if names else None


def is_fluid(recipe):
    return any(i["type"] == "fluid" for i in recipe["ingredients"] + recipe["results"])


class Module:
    """One built thing: a recipe, the machines that run it, and the belts on its ports."""

    def __init__(self, item, want=1.0, belt="transport-belt", machine=None, recipe=None, columns=None,
                 machines=None):
        rt, _, by_product, _ = data()
        if item not in by_product:
            raise ValueError(f"nothing produces {item!r}")
        self.item = item
        self.recipe = recipe or by_product[item][0]
        self.want = rate(want)
        self.belt = belt
        self.machine = machine or self._default_machine()
        self.machines, self.columns = 0, 1
        self._size()
        if machines:                              # restoring a saved module: keep its hardware
            self.machines, self.columns = machines, columns or self.columns

    # ---- sizing -------------------------------------------------------------------------
    def _default_machine(self):
        cats = self.recipe.get("categories") or ["crafting"]
        if is_fluid(self.recipe):
            return fluidcells.machine_for(self.recipe)
        return mk.CATEGORY_MACHINE.get(next((c for c in cats if c in mk.CATEGORY_MACHINE), ""),
                                       "assembling-machine-2")

    def _plan(self, want=None):
        """The generator's plan for this module at `want` (default: what it was asked for)."""
        rt, _, _, _ = data()
        want = self.want if want is None else want
        if is_fluid(self.recipe):
            crafts = want / rt.net_output(self.recipe, self.item)
            return fluidcells.plan(self.recipe, crafts, rt, belt=self.belt, machine=self.machine)
        return templates.plan(self.item, float(want), self.recipe, rt, machine=self.machine, belt=self.belt)

    def _size(self):
        pl = self._plan()
        self.machines, self.columns = pl["n"], pl["c_min"]

    def rebuild(self, want=None):
        """Re-size to `want` (default: the rate it was asked for) with the tiers it has now."""
        if want is not None:
            self.want = rate(want)
        self._size()
        return self

    # ---- what it can do -----------------------------------------------------------------
    @property
    def speed(self):
        if self.machine in fluidcells.MACHINES:
            return fluidcells.MACHINES[self.machine]["speed"]
        rt, _, _, _ = data()
        return rt.MACHINES_BY_NAME[self.machine]

    def capacity(self):
        """What the machines could craft with unlimited belts."""
        rt, _, _, _ = data()
        per_craft = rt.net_output(self.recipe, self.item)
        return Rate(self.machines * self.speed / self.recipe.get("energy_required", 0.5) * per_craft)

    def port_limit(self):
        """What the belts on the ports can carry, as output of this item."""
        rt, _, _, _ = data()
        per_craft = rt.net_output(self.recipe, self.item)
        items = [i for i in self.recipe["ingredients"] if i["type"] == "item"]
        if is_fluid(self.recipe):
            scale = fluidcells.BELT_IN_CAP[self.belt] / 15.0
            caps = [15.0 * scale] * len(items)
            out_cap = 7.5 * scale if any(r["type"] == "item" for r in self.recipe["results"]) else 1e9
        else:
            scale = templates.BELT_SCALE[self.belt]
            caps = [c * scale for c in templates.INPUT_CAPACITY[len(items)]]
            out_cap = templates.OUTPUT_CAPACITY * scale
        lim = self.columns * out_cap
        for ing, cap in zip(items, caps):
            if ing["amount"]:
                lim = min(lim, self.columns * cap * per_craft / ing["amount"])
        return Rate(lim)

    def throughput(self):
        """What this module's hardware can do: the lesser of its machines and its belts."""
        return Rate(min(self.capacity(), self.port_limit()))

    def output(self):
        """What it contributes to the factory: the rate it was asked for, or its throughput if the
        hardware cannot reach that. The difference is headroom - raise `want` or `rebuild()` to use it."""
        return Rate(min(float(self.want), float(self.throughput())))

    def headroom(self):
        return Rate(max(0.0, float(self.throughput()) - float(self.output())))

    def limited_by(self):
        return "machines" if self.capacity() <= self.port_limit() else f"belts ({self.belt})"

    def inputs(self):
        """item -> Rate drawn at the rate this module is asked to run."""
        rt, _, _, _ = data()
        crafts = self.output() / rt.net_output(self.recipe, self.item)
        return {i["name"]: Rate(crafts * i["amount"]) for i in self.recipe["ingredients"]
                if i["name"] != self.item}

    # ---- changing it --------------------------------------------------------------------
    @property
    def family(self):
        """assembler, furnace, or None for a machine tied to its recipe (chemical plant, refinery)."""
        cats = self.recipe.get("categories") or ["crafting"]
        return next((FAMILY[c] for c in cats if c in FAMILY), None)

    def upgrade(self, *tiers):
        """Swap in a better belt or machine, keeping the same machines and columns: the same ground,
        running faster. A machine that cannot run this recipe is refused. `rebuild()` afterwards to
        shrink it back to the rate you asked for."""
        for t in tiers:
            if t in TIERS["belt"]:
                self.belt = t
                continue
            if is_fluid(self.recipe):
                m = fluidcells.machine_for(self.recipe, t)
                if m != t:
                    raise ValueError(f"{t!r} cannot craft {self.recipe['name']} "
                                     f"({', '.join(self.recipe.get('categories') or [])})")
                self.machine = m
                continue
            if self.family and t in TIERS[self.family]:
                if t not in SUPPORTED:
                    raise ValueError(f"{t!r} has no cell: the templates are built around 3x3 machines. "
                                     f"Use {supported_tier(self.family)} in the print and place {t} by hand")
                self.machine = t
                continue
            raise ValueError(f"{t!r} is not a belt, and not a {self.family or 'machine'} that can craft "
                             f"{self.recipe['name']}")
        return self

    def blueprint(self, path=None):
        """The vanilla blueprint string for this module as it stands; writes it to `path` if given."""
        pl = self._plan()
        cols = (fluidcells.build_from_plan if is_fluid(self.recipe) else templates.build_from_plan)(
            pl, columns=self.columns)
        m = templates.combine(cols, f"{self.item} {self.throughput().per_min:.4g}/min")
        self.size = (m.width, m.height)
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
            with open(path, "w") as f:
                f.write(m.to_string() + "\n")
        return m.to_string()

    # ---- looks --------------------------------------------------------------------------
    def to_json(self):
        return {"item": self.item, "want": float(self.want), "belt": self.belt, "machine": self.machine,
                "machines": self.machines, "columns": self.columns}

    @classmethod
    def from_json(cls, d):
        return cls(d["item"], f"{d['want']}/s", belt=d["belt"], machine=d["machine"],
                   machines=d["machines"], columns=d["columns"])

    def __repr__(self):
        return (f"<{self.item}: {self.output().per_min:.4g}/min of {self.throughput().per_min:.4g}/min "
                f"possible, "
                f"{self.machines}x {self.machine} in {self.columns} column"
                f"{'s' * (self.columns != 1)}, {self.belt}, limited by {self.limited_by()}>")

    def _repr_html_(self):
        rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in [
            ("item", self.item), ("running at", f"{self.output().per_min:.4g}/min"),
            ("throughput", f"{self.throughput().per_min:.4g}/min"),
            ("headroom", f"{self.headroom().per_min:.4g}/min"),
            ("machines", f"{self.machines} x {self.machine}"), ("columns", self.columns),
            ("belt", self.belt), ("limited by", self.limited_by()),
            ("inputs", ", ".join(f"{k} {v.per_min:.4g}/min" for k, v in self.inputs().items()))])
        return f"<table><tbody>{rows}</tbody></table>"


class _Modules:
    """`module.red_science(10)`, `module.iron_gear_wheel(120)`, `module.processing_unit("1/s")`."""

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        item = ALIASES.get(name, name.replace("_", "-"))

        def build(want=1.0, **kw):
            return Module(item, want, **kw)

        build.__name__ = name
        build.__doc__ = f"A module producing {item}. Rate is per minute unless you pass a string."
        return build

    def __dir__(self):
        _, _, by_product, _ = data()
        return sorted(list(ALIASES) + [i.replace("-", "_") for i in by_product])


module = _Modules()


class Factory:
    """Everything you have: modules, outside supply, research."""

    def __init__(self, researched=(), name="factory"):
        self.name = name
        self.modules = []
        self.supply = {}
        self.researched = set(researched)
        self.targets = {}

    # ---- building it up -----------------------------------------------------------------
    def add(self, *modules):
        """Put modules in the factory. Returns the factory, so calls chain."""
        self.modules.extend(modules)
        return self

    def have(self, item, r=1.0):
        """Something arrives from outside: ore from miners, hand-built smelting, an import."""
        self.supply[item] = Rate(self.supply.get(item, 0.0) + rate(r))
        return self

    def research(self, *techs):
        self.researched.update(techs)
        return self

    def target(self, item, r):
        """Ask for a rate the milestone ladder does not: `f.target("processing-unit", 60)`."""
        self.targets[item] = rate(r)
        return self

    def remove(self, m):
        self.modules.remove(m)
        return self

    # ---- what it adds up to -------------------------------------------------------------
    def production(self):
        out = {k: Rate(v) for k, v in self.supply.items()}
        for m in self.modules:
            out[m.item] = Rate(out.get(m.item, 0.0) + m.output())
        return out

    def consumption(self):
        out = {}
        for m in self.modules:
            for k, v in m.inputs().items():
                out[k] = Rate(out.get(k, 0.0) + v)
        return out

    def net(self):
        made, used = self.production(), self.consumption()
        return {k: Rate(made.get(k, 0.0) - used.get(k, 0.0)) for k in set(made) | set(used)}

    def tiers(self):
        _, _, _, tech = data()
        return tech.tiers(self.researched)

    def state(self):
        """The planner's view: the same shape the CLI used to read out of a markdown ledger."""
        made, used = self.production(), self.consumption()
        builds = {}
        for m in self.modules:
            builds[m.item] = builds.get(m.item, 0.0) + float(m.output())
        return {"researched": self.researched, "made": {k: float(v) for k, v in made.items()},
                "used": {k: float(v) for k, v in used.items()},
                "net": {k: float(v) for k, v in self.net().items()},
                "targets": {k: float(v) for k, v in self.targets.items()}, "builds": builds,
                "belt": self.tiers().get("belt") or "transport-belt"}

    # ---- planning -----------------------------------------------------------------------
    def next(self):
        """The next move. `f.apply(f.next())` to take it."""
        import planner
        return planner.next_move(self)

    def apply(self, move=None):
        """Take a move: add the module it suggests, or mark the research done."""
        import planner
        return planner.apply(self, move or self.next())

    def ladder(self):
        import planner
        return planner.ladder_table(self)

    def upgrades(self):
        import planner
        return planner.upgrades(self)

    # ---- looks and storage --------------------------------------------------------------
    def status(self):
        import planner
        return planner.status(self)

    def table(self):
        """One row per item: made, used, net."""
        made, used, net = self.production(), self.consumption(), self.net()
        rows = sorted(net, key=lambda i: -abs(net[i]))
        out = [f"{'ITEM':<28}{'MADE':>12}{'USED':>12}{'NET':>12}   per minute"]
        for it in rows:
            out.append(f"{it:<28}{made.get(it, 0.0).per_min if it in made else 0:>12.4g}"
                       f"{used.get(it, 0.0).per_min if it in used else 0:>12.4g}{net[it].per_min:>12.4g}")
        return Text("\n".join(out))

    def save(self, path=None):
        path = path or os.path.join(HERE, f"{self.name}.json")
        with open(path, "w") as f:
            json.dump({"name": self.name, "researched": sorted(self.researched),
                       "supply": {k: float(v) for k, v in self.supply.items()},
                       "targets": {k: float(v) for k, v in self.targets.items()},
                       "modules": [m.to_json() for m in self.modules]}, f, indent=1)
        return path

    @classmethod
    def load(cls, path=None, name="factory"):
        path = path or os.path.join(HERE, f"{name}.json")
        with open(path) as f:
            d = json.load(f)
        g = cls(d.get("researched", ()), d.get("name", name))
        g.supply = {k: Rate(v) for k, v in d.get("supply", {}).items()}
        g.targets = {k: Rate(v) for k, v in d.get("targets", {}).items()}
        g.modules = [Module.from_json(m) for m in d.get("modules", [])]
        return g

    def __repr__(self):
        t = self.tiers()
        return (f"<Factory {self.name}: {len(self.modules)} modules, {len(self.supply)} supplied, "
                f"{len(self.researched)} researched, {t.get('assembler')}/{t.get('belt')}>")

    def _repr_html_(self):
        rows = "".join(f"<tr><td>{m.item}</td><td>{m.output().per_min:.4g} of "
                       f"{m.throughput().per_min:.4g}/min</td>"
                       f"<td>{m.machines} x {m.machine}</td><td>{m.belt}</td>"
                       f"<td>{m.limited_by()}</td></tr>" for m in self.modules)
        return ("<table><thead><tr><th>item</th><th>throughput</th><th>machines</th><th>belt</th>"
                f"<th>limited by</th></tr></thead><tbody>{rows}</tbody></table>")
