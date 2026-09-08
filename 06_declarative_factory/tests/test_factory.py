"""Stable revision plans, typed connections, migration boundaries, and engine evidence."""

import base64
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zlib

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from demo import build, declarations, gear_asset
from factory import (
    Asset,
    Endpoint,
    Factory,
    Group,
    Module,
    Port,
    Tile,
    blueprint,
    digest,
    plan,
)


class FactoryTest(unittest.TestCase):
    def designs(self):
        return tuple(d.compile() for d in declarations())

    def test_adding_capacity_preserves_every_old_entity(self):
        a, b = self.designs()
        delta = plan(b, a)
        self.assertEqual(delta["kind"], "additive")
        self.assertEqual(len(delta["retained"]), 28)
        self.assertEqual(len(delta["add"]), 18)
        self.assertEqual(
            delta["bill"],
            {
                "assembling-machine-1": 1,
                "inserter": 2,
                "small-electric-pole": 1,
                "transport-belt": 14,
            },
        )
        self.assertEqual(delta["remove"], [])
        self.assertEqual(delta["replace"], [])
        self.assertFalse(delta["changes_game"])

    def test_repeating_declaration_has_no_construction(self):
        _, b = self.designs()
        self.assertEqual(plan(b, b)["add"], {})
        self.assertEqual(plan(b, b)["bill"], {})

    def test_sibling_order_does_not_change_identity(self):
        first, _ = declarations()
        group = first.children[0]
        shuffled = replace(
            first, children=(replace(group, children=tuple(reversed(group.children))),)
        )
        self.assertEqual(first.compile(), shuffled.compile())

    def test_entity_order_does_not_change_identity(self):
        asset = gear_asset()
        d = asset.document()
        d["entities"].reverse()
        other = Asset.from_module_json(d, port_names=("iron", "gears"))
        a = Factory("test", (Module("gear", asset, Tile(0, 0)),)).compile()
        b = Factory("test", (Module("gear", other, Tile(0, 0)),)).compile()
        self.assertEqual(plan(b, a)["add"], {})
        self.assertEqual(plan(b, a)["replace"], [])

    def test_nested_addresses_and_parent_offsets(self):
        asset = gear_asset()
        f = Factory(
            "test",
            (
                Group(
                    "outer",
                    Tile(10, 20),
                    (Group("inner", Tile(3, 4), (Module("gear", asset, Tile(1, 2)),)),),
                ),
            ),
        )
        m = f.compile()
        self.assertEqual(m["modules"]["outer/inner/gear"]["at"], [14, 26])

    def test_duplicate_addresses_and_overlap_are_rejected(self):
        gear = Module("gear", gear_asset(), Tile(0, 0))
        for children in (
            (gear, gear),
            (gear, replace(gear, name="other", at=Tile(3, 0))),
        ):
            with self.assertRaises(ValueError):
                Factory("test", children).compile()

    def test_moving_or_removing_existing_module_is_a_blocked_migration(self):
        asset = gear_asset()
        a = Factory("test", (Module("gear", asset, Tile(0, 0)),)).compile()
        for b in (
            Factory("test", (Module("gear", asset, Tile(20, 0)),)).compile(),
            Factory("test", ()).compile(),
        ):
            delta = plan(b, a)
            self.assertEqual(delta["kind"], "blocked")
            with self.assertRaises(ValueError):
                blueprint(b, delta)

    def test_recipe_change_requires_migration(self):
        a, _ = self.designs()
        b = deepcopy(a)
        next(e for e in b["entities"].values() if "recipe" in e)["recipe"] = (
            "copper-cable"
        )
        b["sha256"] = digest({k: v for k, v in b.items() if k != "sha256"})
        self.assertEqual(plan(b, a)["kind"], "blocked")

    def test_missing_port_and_illegal_path_are_rejected(self):
        first, _ = declarations()
        link = first.links[0]
        cases = (
            replace(link, source=Endpoint("main/feeds", "missing")),
            replace(link, path=tuple(reversed(link.path))),
            replace(link, path=link.path[::2]),
            replace(link, path=link.path + link.path[-1:]),
        )
        for broken in cases:
            with self.subTest(link=broken), self.assertRaises(ValueError):
                replace(first, links=(broken,)).compile()

    def test_item_lane_and_rate_contracts_are_enforced(self):
        for alteration in ({"item": "copper-plate"}, {"lane": "left"}, {"rate": 1}):
            first, _ = declarations()
            group = first.children[0]
            feed, gear = group.children
            ports = tuple(
                replace(p, **alteration) if p.name == "socket-a" else p
                for p in feed.asset.ports
            )
            feed = replace(feed, asset=replace(feed.asset, ports=ports))
            changed = replace(first, children=(replace(group, children=(feed, gear)),))
            with self.subTest(alteration=alteration), self.assertRaises(ValueError):
                changed.compile()

    def test_a_port_cannot_be_double_allocated(self):
        _, second = declarations()
        bad = replace(second.links[1], source=second.links[0].source)
        with self.assertRaisesRegex(ValueError, "fan-out"):
            replace(second, links=(second.links[0], bad)).compile()

    def test_invalid_capacity_and_geometry_are_rejected(self):
        for rate in (0, -1, True, float("nan"), 16):
            with self.assertRaises(ValueError):
                Port("port", "in", "iron-plate", Tile(0, 0), 0, rate)
        d = gear_asset().document()
        d["entities"].append(deepcopy(d["entities"][0]))
        with self.assertRaisesRegex(ValueError, "overlap"):
            Asset.from_module_json(d)

    def test_bad_digest_and_wrong_factory_cannot_supply_baseline(self):
        a, b = self.designs()
        bad = deepcopy(a)
        bad["entities"].clear()
        with self.assertRaisesRegex(ValueError, "digest"):
            plan(b, bad)
        unrelated = Factory("different", ()).compile()
        with self.assertRaisesRegex(ValueError, "another factory"):
            plan(b, unrelated)

    def test_addition_blueprint_contains_only_new_entities(self):
        a, b = self.designs()
        delta = plan(b, a)
        encoded = blueprint(b, delta)
        payload = json.loads(zlib.decompress(base64.b64decode(encoded[1:])))
        self.assertEqual(len(payload["blueprint"]["entities"]), 18)
        self.assertEqual(
            sum(
                e["name"] == "assembling-machine-1"
                for e in payload["blueprint"]["entities"]
            ),
            1,
        )

    def test_demo_preserves_existing_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "out"
            build(path)
            self.assertTrue((path / "expansion.svg").exists())
            with self.assertRaises(FileExistsError):
                build(path)

    def test_actual_engine_observations_bind_plan_and_detect_recipe_drift(self):
        evidence = json.loads(
            (HERE / "integration/fixtures/verification.json").read_text()
        )
        a, b = self.designs()
        self.assertEqual(plan(b, a, observation=evidence["before"])["kind"], "additive")
        self.assertEqual(plan(b, a, observation=evidence["drift"])["kind"], "blocked")
        self.assertEqual(evidence["repeat_added"], 0)
        self.assertTrue(evidence["retained_ids_preserved"])
        self.assertEqual(len(evidence["gear_crafts"]), 2)
        for key, entity in evidence["before"]["entities"].items():
            self.assertEqual(evidence["after"]["entities"][key], entity)


if __name__ == "__main__":
    unittest.main()
