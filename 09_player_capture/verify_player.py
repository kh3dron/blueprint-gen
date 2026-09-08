"""Independent checks of the finite opening and native player crafting receipts."""
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "08_live_executor"))
from run_session import observed_snapshot, next_step, completion


def verify(attachment, initial, final, actions, craft_events, milestones):
    joined = attachment["attachment"]
    if not attachment["attached"] or joined["cheat_mode"] or joined["before"] != joined["after"]:
        raise ValueError("player attachment changed the starting character or enabled cheats")
    start, end = initial["state"], final["state"]
    if (start["character_id"] != joined["after"]["character_id"] or end["character_id"] != start["character_id"]
            or start["inventory"] != joined["after"]["inventory"]):
        raise ValueError("opening did not retain the attached character and its inventory")
    if start["inventory"] != {"iron-plate": 8, "wood": 1, "stone-furnace": 1, "burner-mining-drill": 1}:
        raise ValueError("verification requires the standard finite starting inventory")
    if end["inventory"] != {"iron-plate": 22, "wood": 1, "burner-mining-drill": 1, "lab": 1}:
        raise ValueError("final inventory does not match the paid finite opening")
    technologies = {"steam-power", "electronics", "automation-science-pack"}
    if set(end["researched"]) != technologies or {m["technology"] for m in milestones if m["observed"]} != technologies:
        raise ValueError("the three research triggers were not observed")
    if end["crafted"] != {"iron-plate": 50, "copper-plate": 15, "lab": 1}:
        raise ValueError("force production counters do not credit the finite opening")
    if end["paid_furnaces"] != 1 or len(end["built"]) != 1 or end["built"][0]["crafts"] != 65:
        raise ValueError("expected one paid furnace and 65 crafts")
    furnace = end["built"][0]
    mined, outputs, queues = Counter(), Counter(), Counter()
    previous_tick = start["tick"]
    for action in actions:
        request, outcome = action["request"], action["outcome"]
        if (outcome["status"] != "done" or outcome["started_tick"] < previous_tick
                or outcome["finished_tick"] < outcome["started_tick"]):
            raise ValueError("failed action or inconsistent action chronology")
        previous_tick = outcome["finished_tick"]
        result = outcome["value"]
        if request["op"] == "mine":
            if result["gained"] <= 0 or result["gained"] != result["depleted"]:
                raise ValueError("mining does not conserve the finite deposits")
            mined[result["item"]] += result["gained"]
        elif request["op"] == "smelt":
            if result["station_id"] != furnace["id"]:
                raise ValueError("smelting replaced the managed furnace")
            outputs.update(result["outputs"])
        elif request["op"] == "handcraft":
            queues[result["recipe"]] += result["crafts"]
    expected_queues = {"copper-cable": 15, "electronic-circuit": 10, "iron-gear-wheel": 12, "transport-belt": 2, "lab": 1}
    if (mined != {"coal": 6, "iron-ore": 50, "copper-ore": 15} or outputs != {"iron-plate": 50, "copper-plate": 15}
            or queues != expected_queues):
        raise ValueError("action receipts do not match the finite bill")
    events, event_outputs = Counter(), Counter()
    for event in craft_events:
        matching = [a for a in actions if a["request"]["op"] == "handcraft"
                    and a["request"]["args"]["recipe"] == event["recipe"]
                    and a["outcome"]["started_tick"] < event["tick"] <= a["outcome"]["finished_tick"]]
        if event["player_index"] != joined["player_index"] or len(matching) != 1:
            raise ValueError("native craft event is not attributable to its player action")
        events[event["recipe"]] += 1
        event_outputs[event["item"]] += event["count"]
    if (events != expected_queues or event_outputs != {"copper-cable": 30, "electronic-circuit": 10,
            "iron-gear-wheel": 12, "transport-belt": 4, "lab": 1}):
        raise ValueError("native player craft events do not account for the queues and outputs")
    for transfer in final["transfers"]:
        if transfer["count"] != transfer["removed"] or transfer["count"] != transfer["inserted"]:
            raise ValueError("inventory transfer does not conserve stock")
    snapshot, rules = observed_snapshot(final["capture"], end)
    following = next_step(snapshot, rules)
    if completion(snapshot, rules)["complete"] or following["kind"] != "prepare_lab":
        raise ValueError("a crafted lab must lead to powered-lab preparation, not goal completion")
    return {"active_mods": end["active_mods"], "character_id": end["character_id"], "player_index": joined["player_index"],
            "attachment_preserved_state": True, "cheat_mode": False, "mined": dict(mined), "produced": end["crafted"],
            "final_inventory": end["inventory"], "researched": end["researched"], "furnace_id": furnace["id"],
            "furnace_position": furnace["position"], "furnace_crafts": furnace["crafts"], "paid_furnaces": 1,
            "native_player_craft_events": len(craft_events), "command_count": len(actions),
            "simulation_ticks": end["tick"]-start["tick"], "lab_research_observed": True, "goal_complete": False,
            "next_action_kind": following["kind"]}


def verify_directory(run):
    run = Path(run).resolve()
    def read(path):
        return json.loads((run / path).read_text())
    observations = sorted((run / "observations").glob("*.json"))
    events = [json.loads(line) for line in (run / "user-data/script-output/player-crafts.jsonl").read_text().splitlines()]
    return verify(read("attachment.json"), read(observations[0]), read(observations[-1]),
                  read("actions.json"), events, read("milestones.json"))
