"""A verified deployment is a baseline to refresh, never a substitute for live state."""
from copy import deepcopy

from .program import digest


SCOPE = ("active_mods", "surface_index", "force_index", "map_seed", "character_id")
CONFIG = ("name", "position", "direction")


def configuration(row):
    result={k:deepcopy(row[k]) for k in CONFIG}
    if row["name"].startswith("assembling-machine-"):
        result["recipe"]=row.get("recipe")
    return result


def placements(design):
    return design.get("retained_placements",[])+design["placements"]


def entities(state):
    rows = (state.get("iron", {}).get("entities") or []) + (state.get("science", {}).get("entities") or [])
    result = {r["address"]: {"id":r["id"],**configuration(r)} for r in rows}
    if len(result) != len(rows) or len({r["id"] for r in result.values()}) != len(result):
        raise ValueError("deployment has duplicate entity addresses or identities")
    return result


def record(program, observation, verification):
    science=program["goal"]["item"]=="automation-science-pack"
    flag="automatic_science_observed" if science else "automatic_iron_supply_observed"
    rates="science_per_minute" if science else "plates_per_minute"
    if not verification[flag] or min(verification[rates]) < program["goal"]["per_minute"]:
        raise ValueError("cannot record an unverified deployment")
    state = observation["state"]
    actual = entities(state)
    desired = {p["address"]: configuration(p) for p in placements(program["design"])}
    if {k: {f:v for f,v in e.items() if f!="id"} for k, e in actual.items()} != desired:
        raise ValueError("verified deployment does not match its design")
    value = {"schema_version": 1, "program_sha256": program["sha256"], "method": program["method"]["id"],
             "scope": {k: state[k] for k in SCOPE}, "tick": state["tick"],
             "design": deepcopy(program["design"]), "entities": actual,
             "service": deepcopy(verification["output_service"])}
    return {**value, "sha256": digest(value)}


def refresh(deployment, observation):
    if (deployment.get("schema_version") != 1 or deployment.get("sha256") != digest(
            {k: v for k, v in deployment.items() if k != "sha256"})):
        raise ValueError("deployment record changed or has an unsupported schema")
    state = observation["state"]
    if any(state[k] != deployment["scope"][k] for k in SCOPE) or state["tick"] < deployment["tick"]:
        raise ValueError("deployment belongs to a different world, actor or observation history")
    expected = deployment["entities"]
    design = {p["address"]: configuration(p) for p in placements(deployment["design"])}
    if {k: {f:v for f,v in e.items() if f!="id"} for k, e in expected.items()} != design:
        raise ValueError("deployment baseline and entity configuration disagree")
    if entities(state) != expected:
        raise ValueError("observed deployment drift: missing, replaced, added or changed entity")
    return expected


def additions(design, retained):
    desired = {p["address"]: p for p in design["placements"]}
    if len(desired) != len(design["placements"]):
        raise ValueError("duplicate desired entity address")
    for address, existing in retained.items():
        if address not in desired or any(desired[address][k] != existing[k] for k in CONFIG):
            raise ValueError("removal, relocation or reconfiguration requires a migration method")
    return [p for p in design["placements"] if p["address"] not in retained]
