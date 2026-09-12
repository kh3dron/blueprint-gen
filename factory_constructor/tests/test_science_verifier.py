"""Counterexamples to automatic service claims, without running Factorio."""
from collections import Counter
from copy import deepcopy
import unittest

from factory_constructor.verify_science import (
    ITEM, all_entities, check_sample, check_window, native_edges,
    recipe_rules, required_rates, stable_service, stabilized, verify, verify_payload,
)


def evidence(output_chest="wooden-chest", warmup_windows=1):
    recipes = {}
    for name, ingredients, seconds in (
        ("iron-plate", {"iron-ore": 1}, 3.2),
        ("copper-plate", {"copper-ore": 1}, 3.2),
        ("iron-gear-wheel", {"iron-plate": 2}, .5),
        (ITEM, {"iron-gear-wheel": 1, "copper-plate": 1}, 5),
    ):
        recipes[name] = {"seconds": seconds, "inputs": [{"name": k, "amount": v} for k, v in ingredients.items()],
                         "outputs": [{"name": name, "amount": 1}]}
    capture = {"resolved_rules": {"recipes": recipes, "fuel_kj": {"coal": 4000}}}
    groups = {"science": [], "iron": [], "feed": [], "coal": [], "power": []}
    entity_map = {}

    def add(group, address, name, **extra):
        row = dict(address=address, id=address, name=name, position={"x": len(entity_map), "y": 0},
                   direction=0, active=True, energy_j=0, **extra)
        if name in {"stone-furnace", "burner-mining-drill", "burner-inserter", "boiler"}:
            row.update(fuel={"coal": 5}, burning_j=3_000_000)
        if name in {"inserter", "assembling-machine-1", "small-electric-pole", "steam-engine"}:
            row["network_id"] = 1
        if name in {"stone-furnace", "assembling-machine-1"}:
            row.update(products=0, progress=0, input={}, output={})
        groups[group].append(row)
        entity_map[address] = row
        return row

    def inserter(group, address, pickup, drop, burner=False):
        return add(group, address, "burner-inserter" if burner else "inserter", pickup_target=pickup, drop_target=drop)

    add("coal", "coal.drill", "burner-mining-drill", mining_target="coal", drop_target="coal.belt")
    add("coal", "coal.belt", "transport-belt", lanes=[{}, {}], outputs=[])
    add("coal", "coal.chest", "wooden-chest", contents={"coal": 100})
    inserter("coal", "coal.refuel", "coal.belt", "coal.drill", True)
    inserter("coal", "coal.export", "coal.belt", "coal.chest", True)
    add("power", "power.boiler", "boiler")
    add("power", "power.engine", "steam-engine")
    add("power", "power.pole", "small-electric-pole")
    inserter("feed", "feed.boiler", "coal.chest", "power.boiler", True)
    add("iron", "iron.drill", "burner-mining-drill", mining_target="iron-ore", drop_target="iron.furnace")
    add("iron", "iron.furnace", "stone-furnace", recipe="iron-plate")
    add("iron", "iron.chest", "wooden-chest", contents={"iron-plate": 200})
    inserter("iron", "iron.output", "iron.furnace", "iron.chest")
    for machine in ("drill", "furnace"):
        inserter("iron", "iron." + machine + "-fuel", "coal.chest", "iron." + machine, True)
    add("science", "science.copper.drill", "burner-mining-drill", mining_target="copper-ore", drop_target="science.copper.furnace")
    add("science", "science.copper.furnace", "stone-furnace", recipe="copper-plate")
    add("science", "science.copper.chest", "wooden-chest", contents={"copper-plate": 200})
    inserter("science", "science.copper.output", "science.copper.furnace", "science.copper.chest")
    for machine in ("drill", "furnace"):
        inserter("science", "science.copper." + machine + "-fuel", "coal.chest", "science.copper." + machine, True)
    add("science", "science.gears", "assembling-machine-1", recipe="iron-gear-wheel")
    add("science", "science.gears.chest", "wooden-chest", contents={"iron-gear-wheel": 50})
    inserter("science", "science.gears.input", "iron.chest", "science.gears")
    inserter("science", "science.gears.output", "science.gears", "science.gears.chest")
    for i in range(2):
        address = f"science.assembler.{i}"
        add("science", address, "assembling-machine-1", recipe=ITEM)
        inserter("science", address + ".gears", "science.gears.chest", address)
        inserter("science", address + ".copper", "science.copper.chest", address)
        add("science", f"science.output.{i}", output_chest, contents={})
        inserter("science", address + ".output", address, f"science.output.{i}")
    specs = [{k: deepcopy(e[k]) for k in ("address", "name", "position", "direction", "recipe") if k in e and (k != "recipe" or e["name"] == "assembling-machine-1")}
             for e in groups["science"]]
    design = {"placements": specs, "connections": [{"from": a, "to": b, "kind": "material"} for a, b in native_edges(entity_map)],
              "measurement": {"warmup_ticks": 3600 * warmup_windows}, "output": {"item": ITEM, "minimum_per_min": 10,
                                                                         "addresses": ["science.output.0", "science.output.1"]}}

    def deposits(item, minute, rate):
        return {"deposit_remaining": 1000 - minute * rate,
                "deposits": [{"id": item + ":0:0", "name": item, "position": {"x": 0, "y": 0}, "amount": 1000 - minute * rate}]}

    def sample(minute):
        sample_groups = deepcopy(groups)
        coal = dict(entities=sample_groups["coal"], **deposits("coal", minute, 30))
        iron = dict(entities=sample_groups["iron"], feed={"coal": coal, "entities": sample_groups["feed"], "power_entities": sample_groups["power"]},
                    **deposits("iron-ore", minute, 30))
        result = dict(tick=minute * 3600, entities=sample_groups["science"], iron=iron, player_inventory={},
                      player_position={"x": 0, "y": 0},
                      meters={}, production={}, electric_networks={}, electric_consumed_j=minute * 9_000_000,
                      electric_generated_j=minute * 9_000_000, steam_reserve_j=12_000_000,
                      electric_buffer_j=100_000, coal_fuel_value_j=4_000_000, **deposits("copper-ore", minute, 15))
        actual = all_entities(result)
        for address, row in actual.items():
            if "fuel" in row:
                result["meters"][address] = dict(delivered=minute, started=minute, coal=5, burning_j=3_000_000)
        for recipe, rate in (("iron-plate", 30), ("copper-plate", 15), ("iron-gear-wheel", 12)):
            next(e for e in actual.values() if e.get("recipe") == recipe)["products"] = rate * minute
        for i in range(2):
            actual[f"science.assembler.{i}"]["products"] = 6 * minute
            actual[f"science.output.{i}"]["contents"] = {ITEM: 6 * minute}
        actual["iron.chest"]["contents"]["iron-plate"] += 6 * minute
        actual["science.copper.chest"]["contents"]["copper-plate"] += 3 * minute
        actual["coal.chest"]["contents"]["coal"] += (30 - len(result["meters"])) * minute
        for item, production, consumption in (("iron-ore", 30, 30), ("iron-plate", 30, 24), ("copper-ore", 15, 15),
                                              ("copper-plate", 15, 12), ("iron-gear-wheel", 12, 12), (ITEM, 12, 0),
                                              ("coal", 30, len(result["meters"]))):
            result["production"][item] = {"produced": production * minute, "consumed": consumption * minute}
        result["electric_networks"] = {"1": {"consumed_j": {"assembling-machine-1": minute * 9_000_000},
                                            "generated_j": {"steam-engine": minute * 9_000_000},
                                            "total_consumed_j": minute * 9_000_000, "total_generated_j": minute * 9_000_000}}
        return result

    samples = [sample(i) for i in range(warmup_windows + 6)]
    baseline = deepcopy(samples[0])
    baseline["entities"] = []
    opening = {"capture": capture, "state": {"revision": 100, "tick": 0, "iron": deepcopy(samples[0]["iron"]),
        "inventory": dict(Counter(p["name"] for p in specs)), "cursor_placements": [], "player_build_events": [],
        "tree_events": [], "built": [{"id": "old-smelter"}], "active_mods": {"base": "2.1.17"},
        "character_id": "actor", "surface_index": 1, "force_index": 1, "map_seed": 42}}
    final = {"capture": deepcopy(capture), "transfers": [], "state": dict(science=samples[-1], inventory={},
        cursor_placements=[], player_build_events=[], tree_events=[], active_mods={"base": "2.1.17"},
        character_id="actor", surface_index=1, force_index=1, map_seed=42)}
    actions = []

    def action(op, args, value, start=0, finish=0):
        actions.append({"request": {"revision": 100 + len(actions), "op": op, "args": args},
                        "outcome": {"status": "done", "value": value, "started_tick": start, "finished_tick": finish}})

    action("begin_science", {}, baseline)
    inventory = Counter(opening["state"]["inventory"])
    for spec in specs:
        placement = dict(spec, id=spec["address"], tick=0, player_index=1, before=dict(+inventory))
        inventory[spec["name"]] -= 1
        placement["after"] = dict(+inventory)
        final["state"]["cursor_placements"].append(placement)
        final["state"]["player_build_events"].append({k: placement[k] for k in ("id", "tick", "name", "position", "player_index")})
        action("place_science", {"spec": spec}, {"id": spec["address"], "address": spec["address"], "added": True})
    windows = []
    for before, after in zip(samples, samples[1:]):
        window = dict(before=before, after=after, idle_ticks=3600, player_idle=True,
                      inventory_before={}, inventory_after={}, position_before={"x": 0, "y": 0}, position_after={"x": 0, "y": 0})
        windows.append(window)
        action("wait_science", {"ticks": 3600}, window, before["tick"], after["tick"])
    return dict(final=final, opening=opening, design=design,
                previous_deployment={"entities": {e["address"]: {k: e[k] for k in ("id", "name", "position", "direction")}
                                                   for e in groups["iron"]}},
                actions=actions, windows=windows[warmup_windows:], baseline=baseline, events=[])


class ScienceVerifierTest(unittest.TestCase):
    def setUp(self):
        self.payload = evidence()
        self.before, self.after = deepcopy(self.payload["windows"][0]["before"]), deepcopy(self.payload["windows"][0]["after"])
        self.rules = recipe_rules(self.payload["final"]["capture"])

    def check_window(self):
        return check_window(self.before, self.after, self.rules, 10, self.payload["design"]["output"]["addresses"])

    def test_five_native_minutes_and_paid_additions(self):
        report = verify_payload(self.payload)
        self.assertTrue(report["automatic_science_observed"])
        self.assertEqual(report["science_per_minute"], [12] * 5)
        self.assertEqual(report["produced"]["iron-plate"], 150)
        self.assertEqual(report["consumed"]["iron-plate"], 120)
        self.assertGreater(report["coal_buffer_gain"], 0)
        self.assertEqual(report["native_cursor_builds_added"], len(self.payload["design"]["placements"]))
        self.assertTrue(report["goal_complete"])

    def test_paid_iron_chests_collect_the_same_science_service(self):
        payload = evidence(output_chest="iron-chest")
        self.assertEqual(payload["opening"]["state"]["inventory"]["iron-chest"], 2)
        report = verify_payload(payload)
        self.assertEqual(report["science_per_minute"], [12] * 5)
        self.assertEqual(report["output_service"]["entities"], ["science.output.0", "science.output.1"])
        self.assertEqual(report["native_cursor_builds_added"], len(payload["design"]["placements"]))

    def test_recipe_ratios_come_from_runtime(self):
        self.assertEqual(required_rates(self.rules, 10)["iron-plate"], 20)
        self.rules["iron-gear-wheel"]["inputs"]["iron-plate"] = 3
        self.assertEqual(required_rates(self.rules, 10)["iron-plate"], 30)
        with self.assertRaisesRegex(ValueError, "consumption differs"):
            self.check_window()

    def test_global_copper_production_requires_native_depletion(self):
        self.after["production"]["copper-ore"]["produced"] += 1
        with self.assertRaisesRegex(ValueError, "deposit depletion"):
            self.check_window()

    def test_science_counter_requires_native_machine_products(self):
        self.after["production"][ITEM]["produced"] += 1
        with self.assertRaisesRegex(ValueError, "native machine production"):
            self.check_window()

    def test_native_iron_stock_decline_cannot_fake_automatic_service(self):
        # Every native count and stock balances, but old iron pays for science.
        self.after["production"]["iron-ore"]["produced"] -= 15
        self.after["production"]["iron-ore"]["consumed"] -= 15
        self.after["production"]["iron-plate"]["produced"] -= 15
        self.after["iron"]["deposit_remaining"] += 15
        self.after["iron"]["deposits"][0]["amount"] += 15
        all_entities(self.after)["iron.furnace"]["products"] -= 15
        all_entities(self.after)["iron.chest"]["contents"]["iron-plate"] -= 15
        with self.assertRaisesRegex(ValueError, "finite stock decline"):
            self.check_window()

    def test_target_rate_iron_is_insufficient_when_actual_science_consumes_more(self):
        waits = [a["outcome"]["value"] for a in self.payload["actions"] if a["request"]["op"] == "wait_science"]
        samples = [waits[0]["before"], *[w["after"] for w in waits]]
        for sample in samples:
            reduction = sample["tick"] // 3600 * 10
            sample["production"]["iron-ore"]["produced"] -= reduction
            sample["production"]["iron-ore"]["consumed"] -= reduction
            sample["production"]["iron-plate"]["produced"] -= reduction
            sample["iron"]["deposit_remaining"] += reduction
            sample["iron"]["deposits"][0]["amount"] += reduction
            all_entities(sample)["iron.furnace"]["products"] -= reduction
            all_entities(sample)["iron.chest"]["contents"]["iron-plate"] -= reduction
        with self.assertRaisesRegex(ValueError, "finite stock decline cannot fund"):
            verify(**self.payload)

    def test_one_inflight_science_start_can_straddle_a_minute(self):
        boundary = self.payload["windows"][0]["after"]
        rows = all_entities(boundary)
        rows["science.assembler.0"]["progress"] = .5
        rows["science.gears.chest"]["contents"]["iron-gear-wheel"] -= 1
        rows["science.copper.chest"]["contents"]["copper-plate"] -= 1
        boundary["production"]["iron-gear-wheel"]["consumed"] += 1
        boundary["production"]["copper-plate"]["consumed"] += 1
        self.assertEqual(verify(**self.payload)["science_per_minute"], [12] * 5)

    def test_product_buffers_must_be_collected(self):
        rows = all_entities(self.after)
        for i in range(2):
            rows[f"science.output.{i}"]["contents"][ITEM] -= 3
            rows[f"science.assembler.{i}"]["output"][ITEM] = 3
        with self.assertRaisesRegex(ValueError, "collection rate"):
            self.check_window()

    def test_belt_and_held_items_are_part_of_balance(self):
        all_entities(self.after)["science.copper.output"]["held"] = {"name": "copper-plate", "count": 1}
        with self.assertRaisesRegex(ValueError, "material inventories"):
            self.check_window()

    def test_work_in_progress_accounts_for_already_consumed_ingredients(self):
        rows = all_entities(self.after)
        rows["science.assembler.0"]["progress"] = .5
        rows["science.gears.chest"]["contents"]["iron-gear-wheel"] -= 1
        rows["science.copper.chest"]["contents"]["copper-plate"] -= 1
        self.after["production"]["iron-gear-wheel"]["consumed"] += 1
        self.after["production"]["copper-plate"]["consumed"] += 1
        # Supply one new gear for the new in-flight science craft as well.
        rows["science.gears"]["products"] += 1
        rows["science.gears.chest"]["contents"]["iron-gear-wheel"] += 1
        self.after["production"]["iron-gear-wheel"]["produced"] += 1
        self.after["production"]["iron-plate"]["consumed"] += 2
        rows["iron.chest"]["contents"]["iron-plate"] -= 2
        self.check_window()

    def test_every_burner_meter_and_loose_coal_stock_must_balance(self):
        self.after["meters"]["science.copper.drill"]["delivered"] += 1
        with self.assertRaisesRegex(ValueError, "delivery does not conserve"):
            self.check_window()
        self.after["meters"]["science.copper.drill"]["delivered"] -= 1
        all_entities(self.after)["coal.chest"]["contents"]["coal"] -= 1
        with self.assertRaisesRegex(ValueError, "connected coal stocks"):
            self.check_window()

    def test_power_generation_and_assembler_consumption_are_required(self):
        self.after["electric_consumed_j"] = self.before["electric_consumed_j"]
        with self.assertRaisesRegex(ValueError, "electric consumption"):
            self.check_window()

    def test_finite_initial_steam_cannot_explain_the_run(self):
        self.payload["windows"][0]["before"]["steam_reserve_j"] = 100_000_000
        with self.assertRaisesRegex(ValueError, "finite initial steam"):
            verify(**self.payload)

    def test_connected_routes_and_retained_ids_are_required(self):
        retained = all_entities({"entities": [], "iron": self.payload["opening"]["state"]["iron"]})
        all_entities(self.after)["science.copper.drill-fuel"]["pickup_target"] = "absent"
        with self.assertRaisesRegex(ValueError, "route is disconnected"):
            check_sample(self.after, self.payload["design"], retained)
        self.after = deepcopy(self.payload["windows"][0]["after"])
        all_entities(self.after)["iron.furnace"]["id"] = "replacement"
        with self.assertRaisesRegex(ValueError, "retained entity configuration"):
            check_sample(self.after, self.payload["design"], retained)

    def test_legacy_coal_target_identity_resolves_only_through_native_deposits(self):
        retained = all_entities({"entities": [], "iron": self.payload["opening"]["state"]["iron"]})
        drill = all_entities(self.after)["coal.drill"]
        drill["mining_target"] = self.after["iron"]["feed"]["coal"]["deposits"][0]["id"]
        check_sample(self.after, self.payload["design"], retained)
        drill["mining_target"] = "coal:999:999"
        with self.assertRaisesRegex(ValueError, "no native coal extraction"):
            check_sample(self.after, self.payload["design"], retained)

    def test_empty_declared_connection_list_cannot_hide_starved_burner(self):
        retained = all_entities({"entities": [], "iron": self.payload["opening"]["state"]["iron"]})
        self.payload["design"]["connections"] = []
        all_entities(self.after)["science.copper.drill-fuel"]["pickup_target"] = "absent"
        with self.assertRaisesRegex(ValueError, "burner disconnected"):
            check_sample(self.after, self.payload["design"], retained)

    def test_no_missing_minutes_or_player_actions(self):
        self.payload["windows"][0]["idle_ticks"] -= 1
        with self.assertRaisesRegex(ValueError, "skipped game time"):
            verify(**self.payload)
        self.payload = evidence()
        self.payload["final"]["transfers"].append(dict(tick=7201, item="iron-plate", count=10, removed=10, inserted=10))
        with self.assertRaisesRegex(ValueError, "native player action"):
            verify(**self.payload)

    def test_free_builds_or_free_final_inventory_are_rejected(self):
        self.payload["final"]["state"]["player_build_events"].pop()
        with self.assertRaisesRegex(ValueError, "native build event"):
            verify(**self.payload)
        self.payload = evidence()
        self.payload["final"]["state"]["inventory"]["iron-plate"] = 1
        with self.assertRaisesRegex(ValueError, "does not conserve science procurement"):
            verify(**self.payload)

    def test_science_samples_must_match_last_observation(self):
        self.payload["final"]["state"]["science"] = deepcopy(self.payload["final"]["state"]["science"])
        self.payload["final"]["state"]["science"]["tick"] += 1
        with self.assertRaisesRegex(ValueError, "final science observation"):
            verify(**self.payload)


class ScienceStabilizationTest(unittest.TestCase):
    def setUp(self):
        self.payload = evidence(warmup_windows=5)
        self.payload["design"]["measurement"].pop("warmup_ticks")
        self.payload["design"]["measurement"]["stabilization"] = {
            "minimum_windows": 5, "maximum_windows": 30, "stable_windows": 3,
        }
        self.rules = recipe_rules(self.payload["final"]["capture"])
        self.waits = [a["outcome"]["value"] for a in self.payload["actions"] if a["request"]["op"] == "wait_science"]
        self.warmup = self.waits[:5]
        self.samples = [self.waits[0]["before"], *[w["after"] for w in self.waits]]

    def assess(self, windows=None):
        return stable_service(self.warmup if windows is None else windows, self.payload["design"], self.rules)

    def test_assess_trailing_three_minutes_then_measure_five_fresh_minutes(self):
        result = self.assess()
        self.assertTrue(result["observed_complete"])
        self.assertEqual(result["assessed_windows"], 3)
        self.assertEqual(result["measurement_ticks"], [7200, 18000])
        self.assertTrue(stabilized(self.warmup, self.payload["design"], self.rules))
        verified = verify(**self.payload)
        self.assertEqual(verified["startup_seconds"], 300)
        self.assertEqual(verified["science_per_minute"], [12] * 5)
        self.assertEqual(verified["output_service"]["measurement_ticks"], [18000, 36000])

    def test_too_few_native_stability_windows_are_pending(self):
        result = self.assess(self.warmup[:2])
        self.assertFalse(result["observed_complete"])
        self.assertIn("3 contiguous", result["reasons"][0])

    def test_actual_startup_must_respect_both_declared_bounds(self):
        policy = self.payload["design"]["measurement"]["stabilization"]
        policy["minimum_windows"] = 6
        with self.assertRaisesRegex(ValueError, "stabilization budget"):
            verify(**self.payload)
        policy.update(minimum_windows=3, maximum_windows=4)
        with self.assertRaisesRegex(ValueError, "stabilization budget"):
            verify(**self.payload)

    def test_impossible_or_fractional_policy_is_invalid(self):
        policy = self.payload["design"]["measurement"]["stabilization"]
        policy["stable_windows"] = 6
        with self.assertRaisesRegex(ValueError, "window limits"):
            self.assess()
        policy["stable_windows"] = 2.5
        with self.assertRaisesRegex(ValueError, "whole minute"):
            self.assess()

    def test_stock_funded_startup_is_pending_even_if_later_measurement_is_good(self):
        for sample in self.samples:
            reduction = min(sample["tick"] // 3600, 5) * 10
            sample["production"]["iron-ore"]["produced"] -= reduction
            sample["production"]["iron-ore"]["consumed"] -= reduction
            sample["production"]["iron-plate"]["produced"] -= reduction
            sample["iron"]["deposit_remaining"] += reduction
            sample["iron"]["deposits"][0]["amount"] += reduction
            all_entities(sample)["iron.furnace"]["products"] -= reduction
            all_entities(sample)["iron.chest"]["contents"]["iron-plate"] -= reduction
        result = self.assess()
        self.assertFalse(result["observed_complete"])
        self.assertTrue(any("iron-plate finite stock decline" in r for r in result["reasons"]))
        with self.assertRaisesRegex(ValueError, "did not stabilize"):
            verify(**self.payload)

    def test_zero_native_copper_during_startup_is_pending_when_balanced(self):
        for sample in self.samples:
            reduction = sample["tick"] // 3600 * 15
            sample["production"]["copper-ore"]["produced"] -= reduction
            sample["production"]["copper-ore"]["consumed"] -= reduction
            sample["production"]["copper-plate"]["produced"] -= reduction
            sample["deposit_remaining"] += reduction
            sample["deposits"][0]["amount"] += reduction
            all_entities(sample)["science.copper.furnace"]["products"] -= reduction
            all_entities(sample)["science.copper.chest"]["contents"]["copper-plate"] -= reduction
        result = self.assess()
        self.assertFalse(result["observed_complete"])
        self.assertTrue(any("new copper-ore output" in r for r in result["reasons"]))
        with self.assertRaisesRegex(ValueError, "deposit depletion"):
            check_window(self.warmup[0]["before"], self.warmup[0]["after"], self.rules, 10,
                         self.payload["design"]["output"]["addresses"])

    def test_declining_coal_and_burning_energy_are_pending(self):
        for sample in self.samples:
            reduction = sample["tick"] // 3600 * 20
            sample["production"]["coal"]["produced"] -= reduction
            coal = sample["iron"]["feed"]["coal"]
            coal["deposit_remaining"] += reduction
            coal["deposits"][0]["amount"] += reduction
            all_entities(sample)["coal.chest"]["contents"]["coal"] -= reduction
        result = self.assess()
        self.assertFalse(result["observed_complete"])
        self.assertIn("connected coal item buffers are still declining", result["reasons"])
        self.assertIn("connected fuel energy reserves are still declining", result["reasons"])

    def test_recipe_wip_boundary_does_not_require_a_longer_startup(self):
        boundary = self.warmup[3]["after"]
        rows = all_entities(boundary)
        rows["science.assembler.0"]["progress"] = .5
        rows["science.gears.chest"]["contents"]["iron-gear-wheel"] -= 1
        rows["science.copper.chest"]["contents"]["copper-plate"] -= 1
        boundary["production"]["iron-gear-wheel"]["consumed"] += 1
        boundary["production"]["copper-plate"]["consumed"] += 1
        self.assertTrue(self.assess()["observed_complete"])

    def test_corrupt_accounting_and_disconnections_are_errors_not_pending(self):
        self.warmup[-1]["after"]["production"]["copper-ore"]["produced"] += 1
        with self.assertRaisesRegex(ValueError, "deposit depletion"):
            self.assess()
        self.warmup[-1]["after"]["production"]["copper-ore"]["produced"] -= 1
        all_entities(self.warmup[-1]["after"])["science.copper.drill-fuel"]["pickup_target"] = "absent"
        with self.assertRaisesRegex(ValueError, "route is disconnected"):
            self.assess()

    def test_skipped_or_intervened_startup_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "not contiguous"):
            self.assess([self.warmup[0], self.warmup[2], self.warmup[4]])
        self.warmup[-1]["player_idle"] = False
        with self.assertRaisesRegex(ValueError, "player intervened"):
            self.assess()


if __name__ == "__main__":
    unittest.main()
