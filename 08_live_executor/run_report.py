"""Small model-facing reports backed by complete local evidence."""
import json
from pathlib import Path


def report(root, *, status, wall_seconds, start_tick=None, start_action=0, error=None):
    root = Path(root)
    def read(name, default=None):
        path = root / name
        return json.loads(path.read_text()) if path.exists() else default
    actions = read("actions.json", [])
    final = read("feed-final-observation.json") or read("latest-observation.json") or {}
    state = final.get("state", {})
    verification = read("feed-verification.json")
    result = {"status": status, "wall_seconds": round(wall_seconds, 3),
              "new_actions": len(actions)-start_action, "tick": state.get("tick"),
              "simulated_seconds": (state["tick"]-start_tick)/60 if start_tick is not None and "tick" in state else None,
              "artifact_directory": str(root.resolve())}
    if verification and status == "passed":
        result["checks"] = {k:verification[k] for k in (
            "automatic_boiler_fuel_observed", "lab_kw_by_minute", "coal_delivered_to_boiler_during_measurement",
            "coal_buffer_gain", "researched", "goal_complete")}
    if error is not None:
        result["error"] = str(error)
        failure = read("last-failure.json")
        failure_error = (failure.get("error") or failure.get("outcome", {}).get("error")) if failure else None
        if failure and failure.get("outcome", {}).get("status") == "running":
            failure_error = "wall-time deadline exceeded"
        # Expected refusal checks leave a receipt too. Do not blame one for a
        # later verifier, startup or checkpoint error.
        result["failed_action"] = failure if failure_error and str(failure_error) in str(error) else None
        result["recent_actions"] = [{"id":a["request"]["id"], "label":a["request"]["label"],
                                     "status":a["outcome"]["status"]} for a in actions[-3:]]
        result["last_observed"] = {k:state.get(k) for k in ("tick", "revision", "position", "inventory", "researched")}
    files = [p for p in root.rglob("*") if p.is_file()]
    result["output_bytes"] = sum(p.stat().st_size for p in files)
    result["png_frames"] = sum(p.suffix==".png" for p in files)
    (root / "run-summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
