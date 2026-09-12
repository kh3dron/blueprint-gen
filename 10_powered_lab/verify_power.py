"""Verify the finite construction/research job without assigning continuous output."""
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "08_live_executor"))
from run_session import observed_snapshot, completion


def verify(final, actions, refusals, design, events, *, snapshot=observed_snapshot):
    state = final["state"]
    if state["inventory"] != {"burner-mining-drill": 1, "small-electric-pole": 1}:
        raise ValueError("final stock does not conserve the finite bill")
    if state["crafted"] != {"iron-plate": 91, "copper-plate": 26, "lab": 1} or state["science_produced"] != 10:
        raise ValueError("production counters do not match the finite jobs")
    if "automation" not in state["researched"] or state["automation_progress"] != 1:
        raise ValueError("automation research was not observed complete")
    placements, built_events = state["cursor_placements"], state["player_build_events"]
    if len(placements) != 7 or len(built_events) != 7 or len({p["id"] for p in placements}) != 7:
        raise ValueError("expected seven unique native cursor builds")
    if Counter(p["name"] for p in placements) != Counter(design["bill"]) + Counter({"stone-furnace": 1}):
        raise ValueError("native placement bill differs from declaration")
    for placement in placements:
        expected = dict(placement["before"])
        expected[placement["name"]] -= 1
        if not expected[placement["name"]]:
            del expected[placement["name"]]
        if expected != placement["after"]:
            raise ValueError("cursor placement did not debit exactly one item")
        matching = [e for e in built_events if e["id"] == placement["id"]]
        if len(matching) != 1 or any(matching[0][k] != placement[k] for k in ("name", "position", "player_index", "tick")):
            raise ValueError("missing or mismatched native player build event")
    deployed = {e["address"]: e for e in state["power_entities"]}
    if set(deployed) != {p["address"] for p in design["placements"]}:
        raise ValueError("power deployment differs from declaration")
    for spec in design["placements"]:
        if any(deployed[spec["address"]][k] != spec[k] for k in ("name", "position", "direction")):
            raise ValueError("power placement drift")
    lab, engine, pole = (deployed["power."+name] for name in ("lab", "engine", "pole"))
    if not lab.get("network_id") or len({e.get("network_id") for e in (lab, engine, pole)}) != 1 or lab["energy_j"] <= 0:
        raise ValueError("lab and steam engine do not share a live network")
    if not 59 <= pole["lab_load_kw_5s"] <= 61 or not 59 <= pole["generation_kw_5s"] <= 61:
        raise ValueError("last five seconds do not establish the lab's measured 60 kW load and generation")
    if not 6_000_000 <= pole["lab_consumed_j"] <= 6_010_000 or abs(pole["generated_j"]-pole["lab_consumed_j"]) > 1:
        raise ValueError("electric energy totals do not account for the lab research")
    if lab["science"] not in ({}, []):
        raise ValueError("research did not consume all delivered science")
    if set(r["reason"] for r in refusals) != {"out_of_reach", "missing_item", "cursor_build_blocked"}:
        raise ValueError("missing cursor refusal checks")
    refused = {r["request_id"]: r for r in refusals}
    mined, smelted, queued = Counter(), Counter(), Counter()
    research = []
    repeat = []
    for action in actions:
        req, out = action["request"], action["outcome"]
        if req["id"] in refused:
            r = refused[req["id"]]
            if out["status"] != "failed" or r["reason"] not in out["error"] or not r["unchanged"] or r["before"] != r["after"]:
                raise ValueError("refused placement changed state or failed for a different reason")
            continue
        if out["status"] != "done":
            raise ValueError("unexplained failed action")
        value = out["value"]
        if req["op"] == "mine":
            if value["gained"] != value["depleted"] or value["gained"] <= 0:
                raise ValueError("mining gain does not match deposit depletion")
            mined[value["item"]] += value["gained"]
        elif req["op"] == "smelt":
            if value["station_id"] != state["built"][0]["id"]:
                raise ValueError("smelting changed furnace")
            smelted.update(value["outputs"])
        elif req["op"] == "handcraft":
            queued[value["recipe"]] += value["crafts"]
        elif req["op"] == "research_lab":
            research.append(out)
        elif req["op"] == "place_power" and not value["added"]:
            repeat.append(value)
    if mined != {"coal": 16, "iron-ore": 91, "copper-ore": 26, "stone": 5} or smelted != {"iron-plate": 91, "copper-plate": 26}:
        raise ValueError("mining and smelting do not conserve the finite jobs")
    if state["paid_furnaces"] != 1 or len(state["built"]) != 1 or state["built"][0]["crafts"] != 117:
        raise ValueError("expected 117 crafts in one paid furnace")
    if len(repeat) != 1 or repeat[0]["id"] != lab["id"]:
        raise ValueError("missing idempotent lab deployment")
    if len(research) != 1 or research[0]["value"] != {"technology": "automation", "observed": True, "science_consumed": 10, "research_ticks": 6000}:
        raise ValueError("missing native timed research receipt")
    if research[0]["finished_tick"] - research[0]["started_tick"] < 6000:
        raise ValueError("research skipped simulation time")
    actual_queues, actual_outputs = Counter(), Counter()
    for event in events:
        matching = [a for a in actions if a["request"]["op"] == "handcraft" and a["request"]["args"]["recipe"] == event["recipe"]
                    and a["outcome"]["started_tick"] < event["tick"] <= a["outcome"]["finished_tick"]]
        if len(matching) != 1 or event["player_index"] != placements[0]["player_index"]:
            raise ValueError("craft event is not attributable to a player job")
        actual_queues[event["recipe"]] += 1
        actual_outputs[event["item"]] += event["count"]
    expected_outputs = Counter()
    for recipe, count in queued.items():
        for product in final["capture"]["resolved_rules"]["recipes"][recipe]["outputs"]:
            expected_outputs[product["name"]] += product["amount"] * count
    if actual_queues != queued or actual_outputs != expected_outputs:
        raise ValueError("native crafting events differ from runtime recipe accounting")
    transfers = final["transfers"]
    for transfer in transfers:
        if transfer["count"] != transfer["removed"] or transfer["count"] != transfer["inserted"]:
            raise ValueError("transfer did not conserve inventory")
    if sum(t["count"] for t in transfers if t["item"] == "coal") != 16 or sum(t["count"] for t in transfers if t["item"] == "automation-science-pack") != 10:
        raise ValueError("fuel/science transfers differ from funded jobs")
    imported, rules = snapshot(final["capture"], state)
    if completion(imported, rules)["complete"]:
        raise ValueError("finite handcrafting was incorrectly credited as sustained science")
    return {"active_mods": state["active_mods"], "mined": dict(mined), "smelted": dict(smelted),
            "final_inventory": state["inventory"], "native_cursor_builds": len(placements),
            "native_player_craft_events": len(events), "furnace_crafts": 117, "science_handcrafted": 10,
            "science_consumed": 10, "research_ticks": 6000, "automation_researched": True,
            "lab_load_kw_5s": pole["lab_load_kw_5s"], "generation_kw_5s": pole["generation_kw_5s"],
            "generated_j": pole["generated_j"], "lab_consumed_j": pole["lab_consumed_j"],
            "power_network_id": lab["network_id"], "repeat_lab_retained": True,
            "refusals": sorted(r["reason"] for r in refusals), "command_count": len(actions),
            "simulation_ticks": state["tick"], "goal_complete": False,
            "next_work": "continuous fuel, automated mining, material routing and science assembly"}


def verify_directory(directory, *, snapshot=observed_snapshot):
    directory = Path(directory)
    def read(name):
        return json.loads((directory / name).read_text())
    events = [json.loads(s) for s in (directory / "user-data/script-output/player-crafts.jsonl").read_text().splitlines()]
    return verify(read("final-observation.json"), read("actions.json"), read("refusals.json"), read("power-design.json"), events, snapshot=snapshot)
