"""Reverify a successful run and retain compact, replayable JSON evidence."""
import argparse
import gzip
import json
from pathlib import Path

from factory_constructor.legacy import verify_iron
from factory_constructor.verify_science import verify as verify_science
from factory_constructor.program import validate


def retain(root, destination):
    read = lambda name: json.loads((root / name).read_text())
    program, execution, report = read("program.json"), read("execution.json"), read("run-summary.json")
    validate(program)
    if (report["status"] != "observed-complete" or execution["status"] != "observed-complete"
            or execution["program_sha256"] != program["sha256"]):
        raise ValueError("retain evidence only after the interpreter has completed the goal")
    opening = read("constructor-opening.json")
    inputs = {"final": read("constructor-final.json"), "opening": opening, "design": program["design"],
        "feed_design": read("feed-design.json"), "coal_design": read("coal-design.json"),
        "actions": [a for a in read("actions.json") if a["request"]["revision"] >= opening["state"]["revision"]],
        "windows": read("constructor-sample.json"), "baseline": read("constructor-baseline.json"),
        "reconciliation": read("constructor-reconciliation.json"),
        "events": [e for e in (json.loads(s) for s in (root / "user-data/script-output/player-crafts.jsonl").read_text().splitlines())
                   if e["tick"] >= opening["state"]["tick"]]}
    if program["goal"]["item"] == "automation-science-pack":
        inputs.pop("feed_design")
        inputs.pop("coal_design")
        inputs["previous_deployment"] = program["deployment"]
        checked = verify_science(**inputs)
    else:
        if program.get("deployment"):
            inputs["previous_design"] = program["deployment"]["design"]
        checked = verify_iron(**inputs, require_refusal=False)
    if checked != read("constructor-verification.json"):
        raise ValueError("retained evidence does not reproduce the live verifier result")
    evidence = {"program": program, "execution": execution, "summary": report,
                "verification": checked, "inputs": inputs}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(gzip.compress(json.dumps(evidence, separators=(",", ":")).encode(), mtime=0))
    print(json.dumps({"fixture": str(destination), "bytes": destination.stat().st_size}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    retain(args.run, args.output)
