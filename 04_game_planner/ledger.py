"""The notebook: an append-only markdown table that is the whole state of the game.

    | #  | date       | move     | what                    | rate    | note                        |
    |----|------------|----------|-------------------------|---------|-----------------------------|
    | 1  | 2026-08-23 | research | electronics             |         |                             |
    | 2  | 2026-08-23 | build    | electronic-circuit      | 2/s     | out/plan/electronic-circuit |

Every line is one move you made. Five kinds:

    research <tech>                 that technology is now researched
    build    <item> <rate>          a factory producing <item> at <rate> (its ingredients are consumed)
    have     <item> <rate>          <rate> of <item> arrives from outside the ledger: ore, hand-built
                                    smelting, a chest you keep filling. Nothing is consumed for it
    scale    <item> <rate>          more of an existing build; identical to `build` in the arithmetic
    target   <item> <rate>          overrides the milestone ladder for that item (rate in /s or /m)

Rates are `12/s` or `600/m`. Edit the file by hand whenever the ledger drifts from the game; the
planner only ever reads it and appends to it.
"""
import datetime
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
NOTEBOOK = os.path.join(HERE, "notebook.md")
MOVES = ("research", "build", "scale", "have", "target")
HEADER = """# Factory notebook

The state of the game, one move per line. `plan.py next` reads this and tells you what to do next;
`plan.py accept` appends its answer here. See ledger.py for the grammar.

| # | date | move | what | rate | note |
|---|------|------|------|------|------|
"""


def parse_rate(s):
    s = (s or "").strip()
    if not s:
        return 0.0
    m = re.match(r"^([0-9.]+)\s*/?\s*(s|m|spm)?$", s, re.I)
    if not m:
        raise ValueError(f"rate {s!r}: want 12/s or 600/m")
    v = float(m[1])
    return v / 60 if (m[2] or "s").lower() in ("m", "spm") else v


def fmt_rate(v):
    return f"{v:.3g}/s" if v >= 0.5 else f"{v * 60:.3g}/m"


class Line:
    def __init__(self, n, date, move, what, rate, note):
        self.n, self.date, self.move, self.what, self.note = n, date, move, what, note
        self.rate_txt = rate
        self.rate = parse_rate(rate)

    def row(self):
        return f"| {self.n} | {self.date} | {self.move} | {self.what} | {self.rate_txt} | {self.note} |"

    def __repr__(self):
        return f"<{self.move} {self.what} {self.rate_txt}>"


def read(path=NOTEBOOK):
    """[Line] in file order. Rows that are not a move (the header, separators, prose) are skipped."""
    if not os.path.exists(path):
        return []
    out = []
    for raw in open(path):
        if not raw.strip().startswith("|"):
            continue
        cells = [c.strip() for c in raw.strip().strip("|").split("|")]
        if len(cells) < 4 or cells[2] not in MOVES:
            continue
        cells += [""] * (6 - len(cells))
        out.append(Line(cells[0], cells[1], cells[2], cells[3], cells[4], cells[5]))
    return out


def append(move, what, rate="", note="", path=NOTEBOOK):
    """Add one move to the notebook and return the Line."""
    lines = read(path)
    n = str(max([int(x.n) for x in lines if x.n.isdigit()] + [0]) + 1)
    ln = Line(n, datetime.date.today().isoformat(), move, what, rate, note)
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(HEADER)
    with open(path, "a") as f:
        f.write(ln.row() + "\n")
    return ln


def state(lines, rt, by_product):
    """What the ledger adds up to.

    researched  {technology}
    made        item -> items/s produced by `build` / `scale` / `have` lines
    used        item -> items/s consumed by the recipes behind those builds
    net         item -> made - used
    targets     item -> items/s asked for by `target` lines
    builds      item -> items/s built here (excludes `have`), for scale-vs-build decisions
    """
    researched, made, used, targets, builds = set(), {}, {}, {}, {}
    for ln in lines:
        if ln.move == "research":
            researched.add(ln.what)
        elif ln.move == "target":
            targets[ln.what] = ln.rate
        elif ln.move == "have":
            made[ln.what] = made.get(ln.what, 0.0) + ln.rate
        elif ln.move in ("build", "scale"):
            made[ln.what] = made.get(ln.what, 0.0) + ln.rate
            builds[ln.what] = builds.get(ln.what, 0.0) + ln.rate
            recipe = (by_product.get(ln.what) or [None])[0]
            if recipe is None:
                continue
            crafts = ln.rate / rt.net_output(recipe, ln.what)
            for ing in recipe["ingredients"]:
                if ing["name"] != ln.what:
                    used[ing["name"]] = used.get(ing["name"], 0.0) + crafts * ing["amount"]
    net = {it: made.get(it, 0.0) - used.get(it, 0.0) for it in set(made) | set(used)}
    return {"researched": researched, "made": made, "used": used, "net": net,
            "targets": targets, "builds": builds}
