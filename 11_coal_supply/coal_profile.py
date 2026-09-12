"""Isolated catalog addition and tree procurement using the running engine."""
from copy import deepcopy
from functools import partial
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "10_powered_lab"))
from run_power import PlayerSession, RecordedDriver
from build_observer import build
from opening import observed_snapshot
from advisor_core.game_import import digest
from advisor_core.rules import Rules


def policy():
    document = deepcopy(Rules.load().document)
    document["id"] += "-coal-supply-v1"
    # Selection policy only: the importer replaces mechanics with runtime exports.
    document["recipes"]["burner-inserter"] = {"category": "crafting"}
    document["items"]["burner-inserter"] = "item"
    document["default_recipes"]["burner-inserter"] = "burner-inserter"
    return Rules(document, digest(document))


class CoalSession(PlayerSession):
    observer_builder = staticmethod(partial(build, policy=policy()))


class CoalDriver(RecordedDriver):
    snapshot = staticmethod(partial(observed_snapshot, policy=policy()))

    def mine(self, item, quantity):
        if item != "wood":
            return super().mine(item, quantity)
        # The current survey is centered on the player. A bounded scouting walk
        # reveals the proving ground's tree row without reading its config.
        _, _, capture = self.observe()
        trees = [e for e in capture["survey"]["obstacles"] if e["entity_type"] == "tree"]
        if not trees:
            self.action("walk_to", {"position": {"x": 0, "y": -12}}, "Scout east for harvestable trees")
            _, _, capture = self.observe()
            trees = [e for e in capture["survey"]["obstacles"] if e["entity_type"] == "tree"]
        gained = 0
        for tree in sorted(trees, key=lambda t: (t["position"]["x"], t["position"]["y"])):
            p = tree["position"]
            self.action("walk_to", {"position": {"x": p["x"], "y": p["y"]+3}}, "Walk within reach of the surveyed tree")
            result = self.action("harvest_tree", {"target": tree}, f"Select and hand-mine tree {tree['id']} for wood")
            gained += result["outcome"]["value"]["gained"]
            if gained >= quantity:
                return
        raise ValueError("not enough surveyed trees to cover the wood bill")
