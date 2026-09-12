"""Backchain rates, select a registered construction method, and lower it to a program."""
from copy import deepcopy

from .program import ProgramBuilder, digest
from .legacy import requirements


def observation_binding(observation):
    state = observation["state"]
    return {"state_sha256": digest(state), "capture_sha256": digest(observation["capture"]),
            **{k: state[k] for k in ("tick", "revision", "character_id", "surface_index", "force_index", "map_seed", "active_mods")}}


def compile_goal(goal, observation, snapshot, rules, methods, *, deployment=None):
    desired = deepcopy(snapshot)
    desired.document["goals_per_min"] = {goal.item: goal.per_minute}
    crafts, raw = requirements(desired, rules)
    rates = {"crafts_per_minute": {k: v * 60 for k, v in crafts.items()},
             "raw_per_minute": {k: v * 60 for k, v in raw.items()}}
    builder = ProgramBuilder(goal, observation_binding(observation), rates)
    matches = [m for m in methods if m.output == goal.item]
    if not matches:
        builder.document["blockers"].append("no executable construction method for " + goal.item)
        builder.document["unimplemented_recipes"] = [k for k in crafts if not any(m.output in rules.recipes[k]["outputs"] for m in methods)]
    elif len(matches) > 1:
        builder.document["blockers"].append("multiple applicable methods require a selection policy")
    else:
        try:
            matches[0].lower(goal, observation, snapshot, rules, builder, deployment=deployment)
        except ValueError as error:
            builder.document["blockers"].append(str(error))
    return builder.finish()
