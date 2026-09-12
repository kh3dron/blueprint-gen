"""Independent accounting of a paid, connected, automatic science service.

Native item statistics are checked against deposits, machine counters, every
observed inventory and ingredients in unfinished crafts. Initial stock is never
accepted as evidence of a current input production rate.
"""
from collections import Counter
from math import isclose


ITEM = "automation-science-pack"
RECIPES = ("iron-plate", "copper-plate", "iron-gear-wheel", ITEM)
CONFIG = ("id", "name", "position", "direction")


def indexed(rows):
    result = {e["address"]: e for e in rows}
    if len(result) != len(rows) or len({e["id"] for e in rows}) != len(rows):
        raise ValueError("duplicate entity address or identity")
    return result


def all_entities(sample):
    """Use one canonical occurrence of each nested upstream module."""
    iron = sample["iron"]
    feed = iron["feed"]
    return indexed(sample["entities"] + iron["entities"] + feed["entities"]
                   + feed["coal"]["entities"] + feed["power_entities"])


def stock(sample, item):
    result = 0
    for entity in all_entities(sample).values():
        for key in ("input", "output", "contents", "fuel", "science"):
            result += (entity.get(key) or {}).get(item, 0)
        result += sum((lane or {}).get(item, 0) for lane in entity.get("lanes", []))
        held = entity.get("held")
        if held and held["name"] == item:
            result += held["count"]
    return result


def recipe_rules(capture):
    """Resolve only the deterministic native recipe chain this method supports."""
    rules = {}
    for name in RECIPES:
        recipe = capture["resolved_rules"]["recipes"][name]
        inputs = Counter()
        outputs = Counter()
        for destination, parts in ((inputs, recipe["inputs"]), (outputs, recipe["outputs"])):
            for part in parts:
                if part.get("type", "item") != "item" or part["amount"] <= 0:
                    raise ValueError("science requires deterministic item recipes")
                destination[part["name"]] += part["amount"]
        if set(outputs) != {name} or recipe["seconds"] <= 0:
            raise ValueError("unsupported science recipe output")
        rules[name] = {"inputs": inputs, "amount": outputs[name], "seconds": recipe["seconds"]}
    expected = {"iron-plate": {"iron-ore"}, "copper-plate": {"copper-ore"},
                "iron-gear-wheel": {"iron-plate"}, ITEM: {"copper-plate", "iron-gear-wheel"}}
    if any(set(rules[name]["inputs"]) != ingredients for name, ingredients in expected.items()):
        raise ValueError("observed recipes do not describe the supported science chain")
    return rules


def required_rates(rules, target):
    rates = {ITEM: target}
    for name in (ITEM, "iron-gear-wheel", "copper-plate", "iron-plate"):
        for ingredient, amount in rules[name]["inputs"].items():
            rates[ingredient] = rates.get(ingredient, 0) + rates[name] * amount / rules[name]["amount"]
    return rates


def pending_inputs(sample, rules):
    result = Counter()
    for address, entity in all_entities(sample).items():
        recipe = entity.get("recipe")
        if recipe in rules and entity.get("progress", 0) > 0:
            result.update(rules[recipe]["inputs"])
    return result


def native_edges(entities):
    by_id = {e["id"]: address for address, e in entities.items()}
    edges = set()
    for address, entity in entities.items():
        for target in entity.get("outputs", []):
            if target in by_id:
                edges.add((address, by_id[target]))
        if entity.get("drop_target") in by_id:
            edges.add((address, by_id[entity["drop_target"]]))
        if entity.get("pickup_target") in by_id:
            edges.add((by_id[entity["pickup_target"]], address))
    return edges


def _deposits(sample):
    result = {}
    groups = ((sample["deposits"], None), (sample["iron"]["deposits"], "iron-ore"),
              (sample["iron"]["feed"]["coal"]["deposits"], "coal"))
    for deposits, default in groups:
        for deposit in deposits:
            name = deposit.get("name", default) or deposit["id"].split(":")[0]
            if deposit["id"] in result or deposit["amount"] <= 0:
                raise ValueError("duplicate, exhausted or invalid measured deposit")
            result[deposit["id"]] = (name, deposit["position"], deposit["amount"])
    for module in (sample, sample["iron"], sample["iron"]["feed"]["coal"]):
        if module["deposit_remaining"] != sum(d["amount"] for d in module["deposits"]):
            raise ValueError("deposit total differs from native resource observations")
    totals = Counter()
    for d in sample["deposits"]:
        totals[d.get("name") or d["id"].split(":")[0]] += d["amount"]
    if "deposit_remaining_by_resource" in sample and +totals != Counter(sample["deposit_remaining_by_resource"]):
        raise ValueError("typed deposit totals differ from observations")
    return result


def check_sample(sample, design, retained, ids=None):
    entities = all_entities(sample)
    new = indexed(sample["entities"])
    specs = {p["address"]: p for p in design["placements"]}
    if len(specs) != len(design["placements"]) or new.keys() != specs.keys():
        raise ValueError("missing or unexpected science entity")
    found_ids = {address: e["id"] for address, e in entities.items()}
    if ids is not None and found_ids != ids:
        raise ValueError("entity replaced during science measurement")
    if entities.keys() != retained.keys() | new.keys():
        raise ValueError("retained entity roster changed")
    for address, expected in retained.items():
        if address not in entities or any(entities[address].get(k) != expected.get(k) for k in CONFIG):
            raise ValueError("retained entity configuration changed: " + address)
        # Preserve native upstream routes as well as the placement configuration.
        for key in ("pickup_target", "drop_target"):
            if expected.get(key) is not None and entities[address].get(key) != expected[key]:
                raise ValueError("retained material connection changed: " + address)
        if not set(expected.get("outputs", [])).issubset(entities[address].get("outputs", [])):
            raise ValueError("retained belt connection changed: " + address)
    power_networks = {str(e["network_id"]) for e in entities.values()
                      if e["name"] == "steam-engine" and e.get("network_id") is not None}
    for address, entity in entities.items():
        if address in specs:
            spec = specs[address]
            if any(entity.get(k) != spec.get(k) for k in ("name", "position", "direction")):
                raise ValueError("science entity configuration drift: " + address)
            if "recipe" in spec and entity.get("recipe") != spec["recipe"]:
                raise ValueError("science assembler recipe changed: " + address)
        if entity["name"] in {"assembling-machine-1", "inserter", "small-electric-pole"}:
            if str(entity.get("network_id")) not in power_networks:
                raise ValueError("science power disconnected: " + address)
        if entity["name"] in {"assembling-machine-1", "stone-furnace", "burner-mining-drill", "inserter", "burner-inserter"}:
            if not entity.get("active", False):
                raise ValueError("inactive science service machine: " + address)
        if entity["name"] == "stone-furnace":
            wanted = "copper-plate" if address in new else "iron-plate"
            idle_empty = not entity.get("recipe") and entity.get("progress") == 0 and not entity.get("input") and not entity.get("output")
            if entity.get("recipe") != wanted and not idle_empty:
                raise ValueError("wrong native smelting recipe")
    edges = native_edges(entities)
    for link in design.get("connections", []):
        if link.get("kind") in {"wire", "power"}:
            continue
        pair = (link["from"], link["to"])
        if pair not in edges:
            raise ValueError("declared material route is disconnected: " + " -> ".join(pair))
    burners = {address: e for address, e in entities.items() if "fuel" in e}
    if set(sample["meters"]) != set(burners):
        raise ValueError("fuel meter coverage incomplete")
    deposits = _deposits(sample)
    # The retained coal observer reports a resource identity, while the science
    # observer reports its prototype name. Resolve identities through the
    # observed native deposits; accepting a string prefix would invent a source.
    sources = {address for address, e in entities.items()
               if e["name"] == "burner-mining-drill"
               and (e.get("mining_target") == "coal"
                    or deposits.get(e.get("mining_target"), (None,))[0] == "coal")}
    if not sources:
        raise ValueError("no native coal extraction source")
    reachable = set(sources)
    pending = list(sources)
    while pending:
        source = pending.pop()
        # A smelter or assembler consumes coal; it cannot relay it through its output.
        if (entities[source]["name"] in {"stone-furnace", "assembling-machine-1", "boiler"}
                or (entities[source]["name"] == "burner-mining-drill" and source not in sources)):
            continue
        for a, b in edges:
            if a == source and b not in reachable:
                reachable.add(b)
                pending.append(b)
    if not set(burners).issubset(reachable):
        raise ValueError("burner disconnected from native coal extraction: " + ", ".join(sorted(set(burners) - reachable)))
    return found_ids


def check_window(before, after, rules, target, output_addresses, *, require_rates=True):
    """Verify one exact minute, independent of action or planner assertions."""
    a, b = all_entities(before), all_entities(after)
    old_deposits, new_deposits = _deposits(before), _deposits(after)
    if old_deposits.keys() != new_deposits.keys():
        raise ValueError("measured resource roster changed")
    depletion = Counter()
    for key, (resource, position, amount) in old_deposits.items():
        if new_deposits[key][:2] != (resource, position) or new_deposits[key][2] > amount:
            raise ValueError("measured resource changed or increased")
        depletion[resource] += amount - new_deposits[key][2]
    produced, consumed = Counter(), Counter()
    for item in (*RECIPES, "iron-ore", "copper-ore", "coal"):
        produced[item] = after["production"][item]["produced"] - before["production"][item]["produced"]
        consumed[item] = after["production"][item]["consumed"] - before["production"][item]["consumed"]
        if min(produced[item], consumed[item]) < 0:
            raise ValueError("native production statistics went backwards")
    for ore in ("iron-ore", "copper-ore", "coal"):
        if (require_rates and produced[ore] <= 0) or produced[ore] != depletion[ore]:
            raise ValueError(ore + " production does not match native deposit depletion")
    expected_consumed = Counter()
    for recipe, rule in rules.items():
        machines = [address for address, entity in b.items()
                    if entity.get("recipe") == recipe or a[address].get("recipe") == recipe
                    or (entity["name"] == "stone-furnace" and recipe == ("copper-plate" if address.startswith("science.") else "iron-plate"))]
        finished = sum(b[k]["products"] - a[k]["products"] for k in machines)
        progress = sum(int(b[k]["progress"] > 0) - int(a[k]["progress"] > 0) for k in machines)
        if finished < 0 or produced[recipe] != finished:
            raise ValueError(recipe + " output does not match native machine production")
        crafts = finished / rule["amount"] + progress
        for ingredient, amount in rule["inputs"].items():
            expected_consumed[ingredient] += crafts * amount
    for item in (*RECIPES, "iron-ore", "copper-ore"):
        if consumed[item] != expected_consumed[item]:
            raise ValueError(item + " consumption differs from recipes and work in progress")
        if produced[item] - consumed[item] != stock(after, item) - stock(before, item):
            raise ValueError(item + " native production does not conserve all material inventories")
    required = required_rates(rules, target)
    for item in ("iron-ore", "copper-ore", "iron-plate", "copper-plate", "iron-gear-wheel", ITEM):
        if require_rates and produced[item] < required[item]:
            raise ValueError(item + " finite stock decline cannot satisfy automatic supply")
    delivered = sum((b[k].get("contents") or {}).get(ITEM, 0)
                    - (a[k].get("contents") or {}).get(ITEM, 0) for k in output_addresses)
    if require_rates and delivered < target:
        raise ValueError("science collection rate below contract")
    burned = 0
    for address, meter in after["meters"].items():
        old = before["meters"][address]
        arriving = meter["delivered"] - old["delivered"]
        starts = meter["started"] - old["started"]
        delta = (b[address].get("fuel") or {}).get("coal", 0) - (a[address].get("fuel") or {}).get("coal", 0)
        if min(arriving, starts) < 0 or arriving != delta + starts:
            raise ValueError("burner fuel delivery does not conserve coal")
        if "coal" in meter and meter["coal"] != (b[address].get("fuel") or {}).get("coal", 0):
            raise ValueError("burner meter stock differs from native fuel inventory")
        if "burning_j" in meter and not isclose(meter["burning_j"], b[address].get("burning_j", 0), abs_tol=.01):
            raise ValueError("burner meter energy differs from native burner")
        if "burned_j" in meter:
            fuel_value = after["coal_fuel_value_j"]
            energy = a[address].get("burning_j", 0) + starts * fuel_value - b[address].get("burning_j", 0)
            if energy < -.01 or not isclose(meter["burned_j"] - old["burned_j"], energy, abs_tol=.1):
                raise ValueError("burner energy consumption does not conserve fuel")
        burned += starts
    if stock(after, "coal") - stock(before, "coal") != produced["coal"] - burned:
        raise ValueError("connected coal stocks do not balance extraction and every burner")
    used = after["electric_consumed_j"] - before["electric_consumed_j"]
    generated = after["electric_generated_j"] - before["electric_generated_j"]
    if min(used, generated) < 0 or (require_rates and min(used, generated) == 0):
        raise ValueError("science production had no native electric consumption or generation")
    old_networks, new_networks = before["electric_networks"], after["electric_networks"]
    if old_networks.keys() != new_networks.keys():
        raise ValueError("electric network identity changed")
    assembler_j = sum(net["consumed_j"].get("assembling-machine-1", 0) - old_networks[key]["consumed_j"].get("assembling-machine-1", 0)
                      for key, net in new_networks.items())
    if assembler_j < 0 or (require_rates and assembler_j == 0):
        raise ValueError("science assemblers consumed no native electricity")
    for sample in (before, after):
        for kind in ("consumed", "generated"):
            total = sum(net["total_" + kind + "_j"] for net in sample["electric_networks"].values())
            if not isclose(total, sample["electric_" + kind + "_j"], abs_tol=.1):
                raise ValueError("electric network totals disagree")
            for network in sample["electric_networks"].values():
                if not isclose(sum(network[kind + "_j"].values()), network["total_" + kind + "_j"], abs_tol=.1):
                    raise ValueError("electric entity statistics do not sum to network consumption")
    return {"collected": delivered, "produced": dict(produced), "consumed": dict(consumed),
            "coal_burned": burned, "electric_consumed_j": used, "electric_generated_j": generated,
            "assembler_consumed_j": assembler_j}


def stabilization_config(design):
    config = design["measurement"]["stabilization"]
    keys = ("minimum_windows", "maximum_windows", "stable_windows")
    if any(type(config.get(key)) is not int for key in keys):
        raise ValueError("stabilization limits must be whole minute counts")
    minimum, maximum, stable = (config[key] for key in keys)
    if not 1 <= stable <= minimum <= maximum:
        raise ValueError("invalid bounded stabilization window limits")
    return config


def input_deficits(first, last, rules, produced, consumed):
    reasons = []
    first_pending, last_pending = pending_inputs(first, rules), pending_inputs(last, rules)
    for item in ("iron-ore", "copper-ore", "iron-plate", "copper-plate", "iron-gear-wheel"):
        newly_pending = max(0, last_pending[item] - first_pending[item])
        if produced[item] < consumed[item] - newly_pending:
            reasons.append(item + " finite stock decline cannot fund measured science consumption")
    completed_science_crafts = produced[ITEM] / rules[ITEM]["amount"]
    for item, amount in rules[ITEM]["inputs"].items():
        if produced[item] < completed_science_crafts * amount:
            reasons.append(item + " newly produced supply does not cover completed science recipes")
    return reasons


def fuel_gains(first, last, fuel_value):
    items = stock(last, "coal") - stock(first, "coal")
    burning = sum(e.get("burning_j", 0) for e in all_entities(last).values()) - sum(e.get("burning_j", 0) for e in all_entities(first).values())
    return items, items * fuel_value + burning


def stable_service(windows, design, rules):
    """Assess the trailing native startup minutes without using them as proof.

    The caller owns the minimum/maximum startup budget. Insufficient current
    supply is a pending result; corrupted accounting, changed entities and
    disconnected routes are errors, not reasons to wait longer.
    """
    config = stabilization_config(design)
    count = config["stable_windows"]
    if len(windows) < count:
        return {"observed_complete": False, "reasons": [f"need {count} contiguous native startup minutes"]}
    recent = windows[-count:]
    first, last = recent[0]["before"], recent[-1]["after"]
    retained = all_entities({"entities": [], "iron": first["iron"]})
    ids, previous = None, None
    target = design["output"]["minimum_per_min"]
    required = required_rates(rules, target)
    produced, consumed, reasons = Counter(), Counter(), []
    for number, window in enumerate(recent, 1):
        before, after = window["before"], window["after"]
        if previous is not None and before != previous:
            raise ValueError("stabilization windows are not contiguous")
        previous = after
        if after["tick"] - before["tick"] != 3600 or window["idle_ticks"] != 3600:
            raise ValueError("stabilization window skipped game time")
        if (window["player_idle"] is not True or window["inventory_before"] != window["inventory_after"]
                or window["position_before"] != window["position_after"]
                or before["player_inventory"] != window["inventory_before"] or after["player_inventory"] != window["inventory_after"]
                or before["player_position"] != window["position_before"] or after["player_position"] != window["position_after"]):
            raise ValueError("player intervened during stabilization")
        for key in ("transfer_count", "build_count", "cursor_placement_count", "recipe_events"):
            if before.get(key) != after.get(key):
                raise ValueError("native player action during stabilization")
        for sample in (before, after):
            ids = check_sample(sample, design, retained, ids)
        measured = check_window(before, after, rules, target, design["output"]["addresses"], require_rates=False)
        produced.update(measured["produced"])
        consumed.update(measured["consumed"])
        for item in ("iron-ore", "copper-ore", "iron-plate", "copper-plate", "iron-gear-wheel", ITEM):
            if measured["produced"][item] < required[item]:
                reasons.append(f"startup minute {number}: new {item} output is below {required[item]:g}/min")
        if measured["collected"] < target:
            reasons.append(f"startup minute {number}: science collection is below {target:g}/min")
        if min(measured[key] for key in ("electric_consumed_j", "electric_generated_j", "assembler_consumed_j")) <= 0:
            reasons.append(f"startup minute {number}: native power generation and assembler consumption are required")
    reasons.extend(input_deficits(first, last, rules, produced, consumed))
    fuel_value = first["coal_fuel_value_j"]
    if any(w["after"]["coal_fuel_value_j"] != fuel_value for w in recent):
        raise ValueError("native fuel value changed during stabilization")
    coal_gain, energy_gain = fuel_gains(first, last, fuel_value)
    if coal_gain < 0:
        reasons.append("connected coal item buffers are still declining")
    if energy_gain < -.1:
        reasons.append("connected fuel energy reserves are still declining")
    return {"observed_complete": not reasons, "reasons": reasons,
            "assessed_windows": count, "measurement_ticks": [first["tick"], last["tick"]],
            "coal_buffer_gain": coal_gain, "fuel_energy_gain_j": energy_gain}


def stabilized(windows, design, rules):
    return stable_service(windows, design, rules)["observed_complete"]


def verify_payment(final, opening, design, actions, events, ids, *, reconciliation=None):
    state = final["state"]
    for key in ("cursor_placements", "player_build_events", "tree_events"):
        old = opening["state"][key]
        if state[key][:len(old)] != old:
            raise ValueError("previous native player history changed")
    placements = state["cursor_placements"][len(opening["state"]["cursor_placements"]):]
    specs = {p["address"]: p for p in design["placements"]}
    if len(placements) != len(specs) or {p["address"] for p in placements} != specs.keys():
        raise ValueError("missing or unexpected paid science placements")
    for placement in placements:
        expected = Counter(placement["before"])
        expected.subtract({placement["name"]: 1})
        matching = [e for e in state["player_build_events"] if e["id"] == placement["id"]]
        if (any(n < 0 for n in expected.values()) or +expected != Counter(placement["after"])
                or placement["id"] != ids[placement["address"]] or len(matching) != 1
                or any(matching[0][k] != placement[k] for k in ("tick", "name", "position", "player_index"))):
            raise ValueError("science placement lacks paid inventory or native build event")
    if reconciliation is not None:
        for key in ("inventory", "cursor_placements", "player_build_events"):
            if reconciliation["before"][key] != reconciliation["after"][key]:
                raise ValueError("repeat deployment changed native construction or items")
    inventory, gathered = Counter(opening["state"]["inventory"]), Counter()
    recipes = final["capture"]["resolved_rules"]["recipes"]
    paid_addresses, seeded_addresses = set(), set()
    smelted_crafts = 0
    for action in actions:
        req, out = action["request"], action["outcome"]
        if req["revision"] < opening["state"]["revision"]:
            continue
        if out["status"] != "done":
            raise ValueError("failed action in science construction ledger")
        op, args, value = req["op"], req["args"], out["value"]
        if op in ("mine", "harvest_tree"):
            if value["gained"] <= 0 or (op == "mine" and value["gained"] != value["depleted"]):
                raise ValueError("procurement gathering does not conserve native resources")
            inventory[value["item"]] += value["gained"]
            gathered[value["item"]] += value["gained"]
            if op == "harvest_tree":
                matching = [event for event in state["tree_events"]
                            if event["id"] == value["id"] and out["started_tick"] < event["tick"] <= out["finished_tick"]]
                if len(matching) != 1 or not value["removed"] or matching[0]["products"].get("wood") != value["gained"]:
                    raise ValueError("wood procurement lacks native tree mining evidence")
        elif op in ("smelt", "handcraft"):
            recipe = recipes[args["recipe"]]
            for part in recipe["inputs"]:
                inventory[part["name"]] -= part["amount"] * args["crafts"]
            for part in recipe["outputs"]:
                inventory[part["name"]] += part["amount"] * args["crafts"]
            if op == "smelt":
                inventory["coal"] -= args["coal"]
                if value["station_id"] != opening["state"]["built"][0]["id"]:
                    raise ValueError("procurement smelter identity changed")
                outputs = {part["name"]: part["amount"] * args["crafts"] for part in recipe["outputs"]}
                if value["crafts"] != args["crafts"] or value["outputs"] != outputs:
                    raise ValueError("native smelting receipt differs from observed recipe")
                smelted_crafts += args["crafts"]
            else:
                matching = [e for e in events if out["started_tick"] < e["tick"] <= out["finished_tick"]]
                outputs = Counter()
                for event in matching:
                    if event["recipe"] != args["recipe"] or event["player_index"] != placements[0]["player_index"]:
                        raise ValueError("native handcraft attribution changed")
                    outputs[event["item"]] += event["count"]
                if len(matching) != args["crafts"] or outputs != Counter({p["name"]: p["amount"] * args["crafts"] for p in recipe["outputs"]}):
                    raise ValueError("missing native handcraft outputs")
        elif op == "place_science" and value["added"]:
            address = args["spec"]["address"]
            if address in paid_addresses:
                raise ValueError("science placement charged more than once")
            placement = next(p for p in placements if p["address"] == address)
            if +inventory != Counter(placement["before"]):
                raise ValueError("science procurement inventory differs from paid placement")
            inventory[placement["name"]] -= 1
            paid_addresses.add(address)
        elif op == "seed_science":
            address = args["address"]
            if args["coal"] <= 0 or address in seeded_addresses:
                raise ValueError("invalid finite coal seed")
            seed = state["science"].get("seeds", {}).get(address)
            if (seed != value or seed["id"] != ids[address] or seed["coal"] != args["coal"]
                    or seed["before"]["coal"] != 0 or seed["after"]["coal"] != args["coal"]):
                raise ValueError("finite coal seed differs from native burner transfer")
            matching = [t for t in final["transfers"] if t["tick"] == seed["tick"] and t["item"] == "coal"
                        and t["count"] == args["coal"]]
            if not matching:
                raise ValueError("finite coal seed lacks a native item transfer")
            inventory["coal"] -= args["coal"]
            seeded_addresses.add(address)
        elif op not in {"place_science", "place_iron", "route", "approach", "walk_to", "walk_science", "preflight_power", "begin_science", "wait_science"}:
            raise ValueError("unsupported action in science ledger: " + op)
        if any(n < 0 for n in inventory.values()):
            raise ValueError("science construction spent unavailable items")
    if paid_addresses != specs.keys():
        raise ValueError("paid construction is missing its action receipt")
    if seeded_addresses != set(state["science"].get("seeds", {})):
        raise ValueError("finite coal seeds differ from player action ledger")
    if smelted_crafts:
        old = opening["state"]["built"][0]
        native = next(e for e in state["built"] if e["id"] == old["id"])
        if native["crafts"] - old["crafts"] != smelted_crafts:
            raise ValueError("procurement smelting lacks native furnace craft counts")
    if +inventory != Counter(state["inventory"]):
        raise ValueError("final player inventory does not conserve science procurement")
    if any(t["count"] != t["removed"] or t["count"] != t["inserted"] for t in final["transfers"]):
        raise ValueError("native transfer did not conserve items")
    return dict(gathered), len(placements)


def verify(final, opening, design, previous_deployment, actions, windows, baseline, events, *, reconciliation=None):
    """Accept five post-startup receipts and return an independently checked service."""
    rules = recipe_rules(final["capture"])
    target = design["output"]["minimum_per_min"]
    if target <= 0 or design["output"]["item"] != ITEM:
        raise ValueError("invalid automatic science output declaration")
    if final["capture"]["resolved_rules"] != opening["capture"]["resolved_rules"]:
        raise ValueError("native recipe or machine rules changed during construction")
    for key in ("active_mods", "character_id", "surface_index", "force_index", "map_seed"):
        if final["state"][key] != opening["state"][key]:
            raise ValueError("science evidence changed world, actor, force or runtime")
    opening_sample = {"entities": [], "iron": opening["state"]["iron"]}
    retained = all_entities(opening_sample)
    previous = previous_deployment["entities"]
    actual_iron = indexed(opening["state"]["iron"]["entities"])
    if previous.keys() != actual_iron.keys() or any(any(actual_iron[address].get(k) != expected.get(k) for k in CONFIG)
                                                  for address, expected in previous.items()):
        raise ValueError("previous iron deployment differs from opening native entities")
    actions = [a for a in actions if a["request"]["revision"] >= opening["state"]["revision"]]
    starts = [a for a in actions if a["request"]["op"] == "begin_science"]
    if len(starts) != 1 or starts[0]["outcome"]["value"] != baseline or baseline["entities"]:
        raise ValueError("science baseline is not the receipted empty new module")
    waits = [a for a in actions if a["request"]["op"] == "wait_science"]
    adaptive = "stabilization" in design["measurement"]
    if adaptive:
        config = stabilization_config(design)
        warmup_count = len(waits) - 5
        if not config["minimum_windows"] <= warmup_count <= config["maximum_windows"]:
            raise ValueError("science startup falls outside declared stabilization budget")
    else:
        warmup_count = design["measurement"]["warmup_ticks"] // 3600
        if warmup_count < 1 or design["measurement"]["warmup_ticks"] % 3600:
            raise ValueError("invalid fixed science startup duration")
    if (len(windows) != 5 or len(waits) != warmup_count + 5
            or [a["outcome"]["value"] for a in waits[warmup_count:]] != windows):
        raise ValueError("five science windows must match action receipts after declared startup")
    ids, previous_sample, measurements = None, None, []
    native_events = final["transfers"] + final["state"]["player_build_events"] + final["state"]["tree_events"] + events
    for index, action in enumerate(waits):
        window = action["outcome"]["value"]
        before, after = window["before"], window["after"]
        if previous_sample is not None and previous_sample != before:
            raise ValueError("science startup and measurement windows are not contiguous")
        previous_sample = after
        start, finish = before["tick"], after["tick"]
        if finish - start != 3600 or window["idle_ticks"] != 3600 or (action["outcome"]["started_tick"], action["outcome"]["finished_tick"]) != (start, finish):
            raise ValueError("science idle window skipped game time")
        if (window["player_idle"] is not True or window["inventory_before"] != window["inventory_after"]
                or window["position_before"] != window["position_after"] or before["player_inventory"] != after["player_inventory"]):
            raise ValueError("player intervened during science measurement")
        if (before["player_inventory"] != window["inventory_before"] or after["player_inventory"] != window["inventory_after"]
                or before["player_position"] != window["position_before"] or after["player_position"] != window["position_after"]):
            raise ValueError("player state differs from native idle-window observation")
        if any(start < event["tick"] <= finish for event in native_events):
            raise ValueError("native player action during science measurement")
        if index < warmup_count:
            if adaptive and index >= warmup_count - config["stable_windows"]:
                for sample in (before, after):
                    ids = check_sample(sample, design, retained, ids)
            continue
        for sample in (before, after):
            ids = check_sample(sample, design, retained, ids)
        measurements.append(check_window(before, after, rules, target, design["output"]["addresses"]))
    stabilization = None
    if adaptive:
        stabilization = stable_service([a["outcome"]["value"] for a in waits[:warmup_count]], design, rules)
        if not stabilization["observed_complete"]:
            raise ValueError("science service did not stabilize before measurement: " + "; ".join(stabilization["reasons"]))
    first, last = windows[0]["before"], windows[-1]["after"]
    if final["state"]["science"] != last:
        raise ValueError("final science observation differs from final measured window")
    if any(t["tick"] > waits[0]["outcome"]["started_tick"] for t in final["transfers"]):
        raise ValueError("manual transfer after science startup began")
    fuel_value = final["capture"]["resolved_rules"]["fuel_kj"]["coal"] * 1000
    fuel_gain, energy_gain = fuel_gains(first, last, fuel_value)
    if fuel_gain < 0 or energy_gain < -.1:
        raise ValueError("connected coal or burning fuel buffers drained")
    for address, entity in all_entities(last).items():
        if entity["name"] in {"burner-mining-drill", "stone-furnace", "boiler"}:
            if last["meters"][address]["delivered"] <= first["meters"][address]["delivered"]:
                raise ValueError("no new coal reached operating consumer: " + address)
    gathered, builds = verify_payment(final, opening, design, actions, events, ids, reconciliation=reconciliation)
    produced = Counter()
    consumed = Counter()
    for measurement in measurements:
        produced.update(measurement["produced"])
        consumed.update(measurement["consumed"])
    deficits = input_deficits(first, last, rules, produced, consumed)
    if deficits:
        raise ValueError(deficits[0])
    generated_j = sum(m["electric_generated_j"] for m in measurements)
    finite_power = first["steam_reserve_j"] + first["electric_buffer_j"]
    if generated_j <= finite_power:
        raise ValueError("finite initial steam and electric reserves could explain generated power")
    rates = [m["collected"] for m in measurements]
    return {"automatic_science_observed": True,
            "automatic_science_supply_observed": True, "automatic_science_production_observed": True,
            "factorio_version": final["state"]["active_mods"]["base"], "idle_seconds": 300,
            "startup_seconds": warmup_count * 60, "stabilization": stabilization,
            "science_per_minute": rates, "science_produced": produced[ITEM], "science_collected": sum(rates),
            "produced": dict(produced), "consumed": dict(consumed), "required_input_per_minute": required_rates(rules, target),
            "coal_burned": sum(m["coal_burned"] for m in measurements), "coal_buffer_gain": fuel_gain,
            "fuel_energy_gain_j": energy_gain, "electric_consumed_j": sum(m["electric_consumed_j"] for m in measurements),
            "electric_generated_j": generated_j, "initial_steam_and_electric_reserve_j": finite_power,
            "native_cursor_builds_added": builds, "additional_gathered": gathered,
            "retained_entities": {address: e["id"] for address, e in retained.items()},
            "output_service": {"item": ITEM, "minimum_per_minute": min(rates),
                "entities": [ids[k] for k in design["output"]["addresses"]], "measurement_ticks": [first["tick"], last["tick"]]},
            "goal_complete": True}


def verify_payload(payload):
    return verify(**payload)
