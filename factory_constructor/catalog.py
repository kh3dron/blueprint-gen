"""Science-owned observer catalog additions, isolated from earlier experiments."""
from copy import deepcopy
from functools import partial

# The legacy boundary initializes the numbered experiments' import paths.
from .legacy import CoalDriver, CoalSession
from coal_profile import policy as coal_policy
from build_observer import build
from opening import observed_snapshot
from advisor_core.game_import import digest
from advisor_core.rules import Rules


def policy():
    document = deepcopy(coal_policy().document)
    document["id"] += "-science-v1"
    # Reviewed selection only. Recipe ingredients, yield, duration and enabled
    # state must still come from the live engine's resolved-rules export.
    document["recipes"]["iron-chest"] = {"category": "crafting"}
    document["items"]["iron-chest"] = "item"
    document["default_recipes"]["iron-chest"] = "iron-chest"
    return Rules(document, digest(document))


class ScienceSession(CoalSession):
    observer_builder = staticmethod(partial(build, policy=policy()))


def snapshot(capture, state):
    """Read upgraded observations and retain compatibility with iron fixtures."""
    if "iron-chest" in capture["resolved_rules"]["recipes"]:
        return observed_snapshot(capture, state, policy=policy())
    return CoalDriver.snapshot(capture, state)


class ScienceDriver(CoalDriver):
    snapshot = staticmethod(snapshot)
