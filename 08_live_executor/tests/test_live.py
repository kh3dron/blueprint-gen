"""Recorded engine evidence, conservative continuation, and RCON stream framing."""
from copy import deepcopy
import json
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from session import Rcon
from run_session import verify


class LiveTest(unittest.TestCase):
    def fixture(self, name):
        return json.loads((HERE / "integration/fixtures" / f"{name}.json").read_text())

    def inputs(self):
        return (SimpleNamespace(observations=[self.fixture("initial-observation"), self.fixture("final-observation")],
                                actions=self.fixture("actions"), session=SimpleNamespace(starts=2)),
                self.fixture("milestones"), self.fixture("restart"))

    def test_paid_opening_reuses_one_furnace_across_a_real_restart(self):
        report = verify(*self.inputs())
        self.assertEqual(report["furnace_crafts"], 65)
        self.assertEqual(report["paid_furnaces"], 1)
        self.assertEqual(report["mined"], {"coal": 6, "iron-ore": 50, "copper-ore": 15})
        self.assertTrue(report["checkpoint_preserved"])
        self.assertTrue(report["duplicate_after_restart_ignored"])
        self.assertTrue(report["stale_command_rejected"])

    def test_lab_craft_is_not_silently_converted_to_research_credit(self):
        report = verify(*self.inputs())
        self.assertTrue(report["lab_handcrafted"])
        self.assertEqual(report["final_inventory"]["lab"], 1)
        self.assertEqual(report["produced"]["lab"], 0)
        self.assertFalse(report["lab_research_observed"])
        self.assertFalse(report["goal_complete"])
        self.assertEqual(report["next_action"]["kind"], "observe")
        self.assertNotIn("construction", report["next_action"])

    def test_wrong_inventory_station_or_missing_research_refuses_a_success_report(self):
        for mutation in ("inventory", "id", "position", "crafts", "research"):
            driver, milestones, restart = self.inputs()
            final = driver.observations[-1]["state"]
            if mutation == "inventory":
                final["inventory"]["iron-plate"] += 1
            elif mutation == "id":
                final["built"][0]["id"] = "replacement"
            elif mutation == "position":
                final["built"][0]["position"]["x"] += 1
            elif mutation == "crafts":
                final["built"][0]["crafts"] = 0
            else:
                final["researched"].remove("electronics")
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                verify(driver, milestones, restart)

    def test_mining_and_transfer_ledgers_must_conserve_actual_items(self):
        for kind in ("mining", "transfer", "failed"):
            driver, milestones, restart = self.inputs()
            if kind == "mining":
                next(a for a in driver.actions if a["request"]["op"] == "mine")["outcome"]["value"]["depleted"] = 0
            elif kind == "transfer":
                driver.observations[-1]["transfers"][0]["removed"] = 0
            else:
                driver.actions[-1]["outcome"]["status"] = "failed"
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                verify(driver, milestones, restart)

    def test_changed_checkpoint_and_unverified_retries_are_rejected(self):
        for kind in ("checkpoint", "duplicate", "stale"):
            driver, milestones, restart = self.inputs()
            if kind == "checkpoint":
                restart["after"]["inventory"]["iron-plate"] += 1
            else:
                restart["duplicate_ignored" if kind == "duplicate" else "stale_rejected"] = False
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                verify(driver, milestones, restart)

    def test_shifted_copper_run_walked_native_paths_back_to_the_same_furnace(self):
        approaches = self.fixture("shifted-approaches")
        furnace = self.fixture("shifted-verification")["furnace_position"]
        self.assertEqual(len(approaches), 3)
        for action in approaches[1:]:
            result = action["outcome"]["value"]
            self.assertEqual(result["id"], "13")
            self.assertGreater(len(result["path"]), 2)
            self.assertFalse(any(p.get("needs_destroy_to_reach") for p in result["path"]))
            end = result["path"][-1]["position"]
            self.assertLessEqual((end["x"] - furnace["x"])**2 + (end["y"] - furnace["y"])**2, 9**2 + .001)


def packet(ident, kind, body):
    payload = struct.pack("<ii", ident, kind) + body.encode() + b"\0\0"
    return struct.pack("<i", len(payload)) + payload


class FragmentedSocket:
    def __init__(self, data):
        self.data, self.sent, self.closed = data, [], False
    def recv(self, size):
        part, self.data = self.data[:min(size, 3)], self.data[min(size, 3):]
        return part
    def sendall(self, data):
        self.sent.append(data)
    def close(self):
        self.closed = True


class RconTest(unittest.TestCase):
    def test_fragmented_auth_and_multipart_response_wait_for_command_marker(self):
        sock = FragmentedSocket(packet(1, 0, "") + packet(1, 2, "") + packet(3, 0, '{"ok":')
                                + packet(3, 0, 'true,"value":42}') + packet(4, 0, 'END_3\n'))
        with patch("session.socket.create_connection", return_value=sock):
            client = Rcon(1, "disposable")
            self.assertEqual(client.call({"op": "status"}), 42)
            client.close()
        self.assertTrue(sock.closed)
        self.assertEqual(len(sock.sent), 3)

    def test_bad_auth_closes_the_connection(self):
        sock = FragmentedSocket(packet(-1, 2, ""))
        with patch("session.socket.create_connection", return_value=sock), self.assertRaisesRegex(RuntimeError, "authentication"):
            Rcon(1, "bad")
        self.assertTrue(sock.closed)

    def test_truncated_or_oversized_packets_do_not_become_responses(self):
        for data in (b"", struct.pack("<i", 1), struct.pack("<i", 999999999)):
            client = Rcon.__new__(Rcon)
            client.socket = FragmentedSocket(data)
            with self.subTest(data=data), self.assertRaises((RuntimeError, ConnectionError)):
                client.receive()


if __name__ == "__main__":
    unittest.main()
