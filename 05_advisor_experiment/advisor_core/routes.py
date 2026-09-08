"""Turn native-engine approach receipts into read-only walking/mining instructions."""

from copy import deepcopy
import math

from .game_import import digest, sequence
from .model import integer, number
from .survey import MINERALS, distance, inside, position, survey_data


def validate_route(document):
    if not isinstance(document, dict) or document.get("route_schema_version") != 1:
        raise ValueError("unsupported route schema")
    if document.get("exporter") != {
        "name": "blueprint-gen-observer",
        "version": "0.3.0",
    }:
        raise ValueError("route requires observer 0.3.0")
    version = document.get("factorio_version")
    if (
        not isinstance(version, str)
        or not version.startswith("2.1.")
        or document.get("active_mods")
        != {"base": version, "blueprint-gen-observer": "0.3.0"}
    ):
        raise ValueError("route requires matching Factorio 2.1 base and observer only")
    if document.get("surface_name") != "nauvis":
        raise ValueError("route requires Nauvis")
    if document.get("source") not in (
        "factorio-native-pathfinder",
        "factorio-current-reach-check",
    ):
        raise ValueError("route has no supported engine source")
    for field in (
        "sequence",
        "requested_tick",
        "completed_tick",
        "generation",
        "generation_at_completion",
        "surface_index",
        "force_index",
    ):
        integer(document.get(field), field)
    if not 0 <= document["completed_tick"] - document["requested_tick"] <= 600:
        raise ValueError("invalid route request interval")
    start = position(document.get("start"), "route.start")
    actor = document.get("actor")
    if (
        not isinstance(actor, dict)
        or actor.get("prototype") != "character"
        or not isinstance(actor.get("id"), str)
        or not actor["id"]
    ):
        raise ValueError("route requires character identity")
    reach = number(
        actor.get("resource_reach_distance"), "resource_reach_distance", positive=True
    )
    if not 0.5 < reach <= 32 or actor.get("clearance_margin") != 0.25:
        raise ValueError("unsupported reach or path clearance margin")
    path_mask = document.get("pathfinder_collision_mask", {})
    if (
        not isinstance(path_mask, dict)
        or not isinstance(path_mask.get("layers"), dict)
        or path_mask["layers"].get("water_tile") is not True
        or path_mask.get("consider_tile_transitions") is not False
    ):
        raise ValueError("pathfinder mask must explicitly block water")
    radius = number(document.get("goal_radius"), "goal_radius", positive=True)
    if not math.isclose(radius, reach - 0.5, abs_tol=1e-8):
        raise ValueError("goal radius does not preserve the mining reach margin")
    target = document.get("target")
    if (
        not isinstance(target, dict)
        or target.get("item") not in MINERALS
        or target.get("prototype") != target["item"]
    ):
        raise ValueError("unsupported mineral target")
    position(target.get("position"), "target.position")
    integer(target.get("quantity"), "target.quantity", positive=True)
    integer(target.get("amount"), "target.amount", positive=True)
    if (
        target["quantity"] > min(1000, target["amount"])
        or distance(start, target["position"]) > 64 + 1e-8
    ):
        raise ValueError("target exceeds quantity, stock, or distance bounds")
    expected = {
        "can_open_gates": False,
        "allow_destroy_friendly_entities": False,
        "allow_paths_through_own_entities": False,
        "cache": False,
        "max_path_length": 256,
        "max_waypoints": 2048,
    }
    if document.get("constraints") != expected:
        raise ValueError("unsupported movement constraints")
    status = document.get("status")
    if status not in ("ready", "invalidated", "retry", "no_path"):
        raise ValueError("unsupported route status")
    reasons = sequence(document.get("reasons"), "route.reasons")
    if any(not isinstance(r, str) or not r for r in reasons):
        raise ValueError("route reasons must be nonempty strings")
    path = sequence(document.get("path"), "route.path")
    if status != "ready":
        if path or not reasons:
            raise ValueError(
                "an unusable route must explain why and contain no walking path"
            )
        return document
    if reasons or document["generation"] != document["generation_at_completion"]:
        raise ValueError("ready route has invalidation evidence")
    expected_validation = (
        {"method": "current-reach", "clear": True}
        if document["source"] == "factorio-current-reach-check"
        else {
            "method": "swept-character-box",
            "max_segment_length": 0.125,
            "clear": True,
        }
    )
    if document.get("path_validation") != expected_validation:
        raise ValueError("ready route lacks the independent collision/reach check")
    if not 1 <= len(path) <= 2048:
        raise ValueError("ready route requires a bounded path")
    for point in path:
        if (
            not isinstance(point, dict)
            or point.get("needs_destroy_to_reach") is not False
        ):
            raise ValueError("path requires destruction or lacks collision evidence")
        position(point.get("position"), "waypoint.position")
    if distance(path[0]["position"], start) > 0.001:
        raise ValueError("path does not start at the observed character position")
    if distance(path[-1]["position"], target["position"]) > radius + 0.001:
        raise ValueError("path endpoint is outside mining reach")
    if (
        sum(distance(a["position"], b["position"]) for a, b in zip(path, path[1:]))
        > 256 + 1e-8
    ):
        raise ValueError("path exceeds the movement budget")
    if document["source"] == "factorio-current-reach-check" and len(path) != 1:
        raise ValueError("an already-in-reach result cannot invent a walking path")
    return document


def compile_route(document, *, current_tick=None):
    d = validate_route(document)
    result = {
        "receipt_sha256": digest(d),
        "sequence": d["sequence"],
        "character_id": d["actor"]["id"],
        "based_on_tick": d["completed_tick"],
        "generation": d["generation"],
        "changes_game": False,
        "target": deepcopy(d["target"]),
        "waypoints": [],
        "instructions": [],
    }
    if current_tick is not None:
        integer(current_tick, "current_tick")
        if current_tick < d["completed_tick"]:
            raise ValueError("current tick precedes the route receipt")
        if current_tick - d["completed_tick"] > 600:
            return {
                **result,
                "kind": "observe",
                "reasons": [
                    "route is more than 10 simulated seconds old; request it again"
                ],
            }
    if d["status"] != "ready":
        return {
            **result,
            "kind": "retry" if d["status"] == "retry" else "observe",
            "reasons": list(d["reasons"]),
        }
    # Only remove exactly collinear points traversed in the same direction. No corner cutting.
    waypoints = []
    for point in d["path"]:
        p = deepcopy(point["position"])
        if waypoints and distance(waypoints[-1], p) <= 1e-10:
            continue
        while len(waypoints) >= 2:
            a, b = waypoints[-2:]
            ux, uy, vx, vy = (
                b["x"] - a["x"],
                b["y"] - a["y"],
                p["x"] - b["x"],
                p["y"] - b["y"],
            )
            if abs(ux * vy - uy * vx) > 1e-10 or ux * vx + uy * vy <= 0:
                break
            waypoints.pop()
        waypoints.append(p)
    target = d["target"]
    for p in waypoints[1:]:
        result["instructions"].append(f"Walk to ({p['x']:g}, {p['y']:g}).")
    end = waypoints[-1]
    result["instructions"].append(
        f"Stand at ({end['x']:g}, {end['y']:g}) and hand-mine {target['quantity']:g} additional {target['item']} at ({target['position']['x']:g}, {target['position']['y']:g})."
    )
    result.update(
        kind="walk_then_mine",
        waypoints=waypoints,
        stand_position=end,
        planned_distance_tiles=sum(
            distance(a, b) for a, b in zip(waypoints, waypoints[1:])
        ),
        preconditions=[
            "Use the same character, starting position, and unchanged world; request again after edits or movement.",
            "Keep inventory room, follow the turns, and confirm the target is within mining reach before mining.",
        ],
        completion_check=f"Observe {target['quantity']:g} additional {target['item']} in inventory and matching resource depletion; this receipt is not execution evidence.",
        limits=[
            "Native walking paths use 0.25-tile extra clearance and independent swept-character-box collision checks. Conservative checks can reject narrow routes; moving entities and enemies can still interfere.",
            "Mining reach uses the observed character radius minus 0.5 tile. The engine harness separately tests actual walking and mining.",
            "This CLI cannot see the current game tick or edits unless new observations are supplied.",
        ],
    )
    return result


def map_plan(document, capture):
    plan = compile_route(document)
    if plan["kind"] != "walk_then_mine":
        raise ValueError("cannot map an unusable route")
    data = survey_data(capture)
    scope = capture["scope"]
    if (
        capture["active_mods"] != document["active_mods"]
        or capture["generation"] != document["generation"]
        or any(
            scope.get(k) != document[k]
            for k in ("surface_index", "force_index", "map_seed")
        )
        or not 0 <= document["requested_tick"] - capture["tick"] <= 600
    ):
        raise ValueError(
            "survey and route do not describe the same recent world configuration"
        )
    if any(
        not inside(p, data["area"])
        for p in plan["waypoints"] + [plan["target"]["position"]]
    ):
        raise ValueError(
            "route leaves the supplied survey; use a wider survey for the map"
        )
    return {
        "steps": [plan["target"]],
        "route": plan["waypoints"],
        "stand_position": plan["stand_position"],
    }
