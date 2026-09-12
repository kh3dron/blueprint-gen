"""Check observed attribution, refusal boundaries, and multiplayer RCON framing."""
from copy import deepcopy
import json
from pathlib import Path
import struct
import shutil
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from run_player import SynchronizedRcon, RecordedDriver, configure_recording
from verify_player import verify


class ReconnectTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("luajit"), "LuaJIT is required for the controller regression")
    def test_reconnect_preserves_native_identity_and_refuses_replacement(self):
        result = subprocess.run(["luajit", str(HERE / "tests/reconnect_test.lua"),
            str(HERE / "integration/control.lua")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class RecordingModeTest(unittest.TestCase):
    def test_default_executes_actions_without_captures_or_image_waits(self):
        graphics=SimpleNamespace(wait_image=Mock())
        driver=RecordedDriver(SimpleNamespace(root=Path("unused")),graphics)
        with patch("run_player.Driver.action",return_value={"receipt":"complete"}) as action, \
                patch("run_player.capture_call") as capture:
            self.assertEqual(driver.action("walk_to",{},"walk"),{"receipt":"complete"})
            action.assert_called_once_with("walk_to",{},"walk")
            capture.assert_not_called()
            graphics.wait_image.assert_not_called()

    def test_recording_is_explicit_and_waits_for_the_native_frame(self):
        graphics=SimpleNamespace(record=True,wait_image=Mock())
        driver=RecordedDriver(SimpleNamespace(root=Path("unused")),graphics)
        with patch("run_player.Driver.action",return_value={"receipt":"complete"}), \
                patch("run_player.capture_call",return_value={"image":"native/frame.png"}) as capture:
            driver.action("walk_to",{},"walk")
            capture.assert_called_once_with(driver.session,"capture")
            graphics.wait_image.assert_called_once_with("native/frame.png")

    def test_default_disables_capture_in_a_loaded_save(self):
        session=SimpleNamespace(client=Mock())
        with patch("run_player.capture_call") as capture:
            configure_recording(session,False)
            session.client.call.assert_called_once_with({"op":"configure_trace","mode":"boundaries"})
            capture.assert_called_once_with(session,"disable")


class PlayerEvidenceTest(unittest.TestCase):
    def inputs(self):
        root = HERE / "integration/fixtures"
        def read(name):
            return json.loads((root / f"{name}.json").read_text())
        events = [json.loads(line) for line in (root / "player-crafts.jsonl").read_text().splitlines()]
        return [read("attachment"), read("initial-observation"), read("final-observation"), read("actions"), events, read("milestones")]

    def test_player_crafting_credits_lab_on_same_engine_version_as_headless_gap(self):
        report = verify(*self.inputs())
        headless = json.loads((HERE / "integration/fixtures/headless-2.1.17-verification.json").read_text())
        self.assertEqual(report["active_mods"], headless["active_mods"])
        self.assertEqual(report["mined"], headless["mined"])
        self.assertEqual(report["final_inventory"], headless["final_inventory"])
        self.assertEqual(report["produced"]["lab"], 1)
        self.assertEqual(headless["produced"]["lab"], 0)
        self.assertEqual(report["native_player_craft_events"], 40)
        self.assertTrue(report["lab_research_observed"])
        self.assertFalse(report["goal_complete"])
        self.assertEqual(report["next_action_kind"], "prepare_lab")

    def test_changed_actor_inventory_or_cheat_mode_refuses_attribution(self):
        for kind in ("identity", "inventory", "cheat"):
            args = self.inputs()
            joined = args[0]["attachment"]
            if kind == "identity":
                joined["after"]["character_id"] = "replacement"
            elif kind == "inventory":
                joined["after"]["inventory"]["lab"] = 1
            else:
                joined["cheat_mode"] = True
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                verify(*args)

    def test_missing_or_misattributed_craft_events_are_not_success(self):
        for kind in ("missing", "player", "tick", "output", "duplicate"):
            args = self.inputs()
            event = args[4][-1]
            if kind == "missing":
                args[4].pop()
            elif kind == "player":
                event["player_index"] += 1
            elif kind == "tick":
                event["tick"] = 0
            elif kind == "output":
                event["count"] = 100
            else:
                args[4].append(deepcopy(event))
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                verify(*args)

    def test_missing_research_or_broken_transfer_refuses_success(self):
        for kind in ("research", "counter", "transfer", "furnace"):
            args = self.inputs()
            final = args[2]
            if kind == "research":
                final["state"]["researched"].remove("automation-science-pack")
            elif kind == "counter":
                final["state"]["crafted"]["lab"] = 0
            elif kind == "transfer":
                final["transfers"][0]["inserted"] = 0
            else:
                final["state"]["built"][0]["id"] = "replacement"
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                verify(*args)


def packet(ident, body, kind=0):
    data = struct.pack("<ii", ident, kind) + body.encode() + b"\0\0"
    return struct.pack("<i", len(data)) + data


class Socket:
    def __init__(self, data):
        self.data, self.sent = data, []
    def recv(self, size):
        count = min(size, 3)
        value, self.data = self.data[:count], self.data[count:]
        return value
    def sendall(self, data):
        self.sent.append(data)
    def close(self):
        pass


class SynchronizedRconTest(unittest.TestCase):
    def test_empty_ack_and_multipart_lua_output_wait_for_same_command_marker(self):
        sock = Socket(packet(1, "", 2) + packet(2, "") + packet(2, '{"attached":')
                      + packet(2, 'true}\nEN') + packet(2, 'D_2\n'))
        with patch("session.socket.create_connection", return_value=sock):
            client = SynchronizedRcon(1, "disposable")
            result = client.execute('/silent-command rcon.print("response")')
        self.assertEqual(json.loads(result), {"attached": True})
        self.assertEqual(len(sock.sent), 2)  # Authentication and one command.
        self.assertIn(b"pcall(function()", sock.sent[-1])
        self.assertIn(b"rcon.print('END_2')", sock.sent[-1])

    def test_lua_failure_is_reported_after_marker_and_does_not_wait_forever(self):
        sock = Socket(packet(1, "", 2) + packet(2, "LUA_ERROR: capture player disconnected\nEND_2\n"))
        with patch("session.socket.create_connection", return_value=sock):
            client = SynchronizedRcon(1, "disposable")
            with self.assertRaisesRegex(RuntimeError, "player disconnected"):
                client.execute('/silent-command error("capture player disconnected")')


if __name__ == "__main__":
    unittest.main()
