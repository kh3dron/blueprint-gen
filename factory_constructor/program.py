"""The execution model has no knowledge of iron, recipes, or game RPCs."""
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
from pathlib import Path


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


@dataclass(frozen=True)
class Automate:
    item: str
    per_minute: float

    def __post_init__(self):
        if not isinstance(self.item, str) or not self.item:
            raise ValueError("a production goal needs an item")
        if (isinstance(self.per_minute, bool) or not isinstance(self.per_minute, (float, int))
                or not math.isfinite(self.per_minute) or self.per_minute <= 0):
            raise ValueError("a production goal needs a positive finite rate")


class ProgramBuilder:
    def __init__(self, goal, binding, requirements):
        self.document = {"schema_version": 1, "goal": asdict(goal), "binding": binding,
                         "requirements": requirements, "nodes": [], "blockers": [],
                         "completion": "requires fresh measured output; compilation is not completion"}
        self.group("goal", None, "Automate " + goal.item, "goal-declaration")
        self.previous = None

    def group(self, ident, parent, title, source):
        self.document["nodes"].append({"id": ident, "parent": parent, "title": title,
                                       "source": source, "operation": None, "requires": []})

    def step(self, ident, parent, operation, inputs, check, source):
        self.document["nodes"].append({"id": ident, "parent": parent, "title": ident,
            "source": source, "operation": operation, "inputs": inputs, "check": check,
            "requires": [self.previous] if self.previous else []})
        self.previous = ident

    def finish(self):
        return {**self.document, "sha256": digest(self.document)}


def validate(program):
    if program.get("schema_version") != 1 or program.get("sha256") != digest(
            {k: v for k, v in program.items() if k != "sha256"}):
        raise ValueError("construction program changed or has an unsupported schema")
    Automate(**program["goal"])
    nodes = {n["id"]: n for n in program["nodes"]}
    if len(nodes) != len(program["nodes"]) or "goal" not in nodes:
        raise ValueError("construction nodes need unique identities and a goal root")
    for node in nodes.values():
        path, current = set(), node
        while current["parent"] is not None:
            if current["id"] in path or current["parent"] not in nodes:
                raise ValueError("invalid construction hierarchy")
            path.add(current["id"])
            current = nodes[current["parent"]]
            if current["operation"] is not None:
                raise ValueError("a leaf cannot own other nodes")
        if current["id"] != "goal":
            raise ValueError("every node must belong to the goal")
    leaves = {k: n for k, n in nodes.items() if n["operation"] is not None}
    pending, finished = dict(leaves), set()
    while pending:
        ready = [k for k, n in pending.items() if set(n["requires"]) <= finished]
        if not ready:
            raise ValueError("missing or cyclic construction dependency")
        for key in ready:
            finished.add(key)
            del pending[key]
    if not leaves and not program["blockers"]:
        raise ValueError("an executable program needs completion observations")
    return nodes, leaves


class Executor:
    """Interpret data using a capability port; persist a compact stack after each node.

    A command receipt alone cannot finish a node. The port must evaluate its named
    completion predicate against observations. Restarting in-flight work is not supported.
    """
    def __init__(self, program, port, destination):
        self.program, self.port, self.root = program, port, Path(destination)
        self.nodes, self.leaves = validate(program)
        if program["blockers"]:
            raise ValueError("construction program blocked: " + "; ".join(program["blockers"]))
        port.validate(program)  # All capabilities and the initial observation, before mutation.
        self.root.mkdir(parents=True, exist_ok=True)
        self.state = {"program_sha256": program["sha256"], "status": "planned", "stack": [],
                      "nodes": {k: "planned" for k in self.nodes}, "receipts": {}}

    def stack(self, ident):
        result = []
        while ident is not None:
            result.append(ident)
            ident = self.nodes[ident]["parent"]
        return list(reversed(result))

    def persist(self):
        save(self.root / "execution.json", self.state)

    def run(self):
        done = set()
        self.state["status"] = "running"
        for _ in range(len(self.leaves)):
            ident = next(k for k, n in self.leaves.items() if k not in done and set(n["requires"]) <= done)
            node = self.leaves[ident]
            self.state["stack"] = self.stack(ident)
            for ancestor in self.state["stack"]:
                self.state["nodes"][ancestor] = "running"
            self.persist()
            try:
                receipt = self.port.perform(node)
                evidence = self.port.check(node, receipt)
                if evidence.get("observed_complete") is not True:
                    raise ValueError("completion predicate was not observed: " + ident)
            except Exception as error:
                self.state["status"] = "failed"
                self.state["nodes"][ident] = "failed"
                self.state["error"] = str(error)
                self.persist()
                raise
            done.add(ident)
            self.state["nodes"][ident] = "observed-complete"
            self.state["receipts"][ident] = evidence
            for ancestor in reversed(self.stack(ident)[:-1]):
                descendants = [k for k in self.leaves if ancestor in self.stack(k)]
                if all(k in done for k in descendants):
                    self.state["nodes"][ancestor] = "observed-complete"
            self.persist()
        self.state.update(status="observed-complete", stack=[])
        self.persist()
        return self.state
