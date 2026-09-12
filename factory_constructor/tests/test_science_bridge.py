"""Run the isolated Lua bridge checks without starting a game server."""
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
LUA = next((path for name in ("luajit", "lua", "lua5.4", "lua5.3", "lua5.2")
            if (path := shutil.which(name))), None)


@unittest.skipUnless(LUA, "Lua or LuaJIT is needed for the isolated bridge checks")
class ScienceBridgeTest(unittest.TestCase):
    def test_science_walk_uses_bounded_native_paths_and_alternate_goals(self):
        result = subprocess.run(
            [LUA, str(Path(__file__).with_name("science_walking_checks.lua")), str(ROOT)],
            cwd=ROOT, capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("bounded retry refusal", result.stdout)
        self.assertIn("Legacy path handler delegation", result.stdout)

    def test_paid_placement_fuel_observation_and_idle_invariants(self):
        result = subprocess.run(
            [LUA, str(Path(__file__).with_name("science_bridge_checks.lua")), str(ROOT)],
            cwd=ROOT, capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Paid native cursor placement", result.stdout)
        self.assertIn("Paid iron chest placement", result.stdout)
        self.assertIn("Typed deposits, unique electric networks", result.stdout)
        self.assertIn("Native initial wood exhaustion", result.stdout)


if __name__ == "__main__":
    unittest.main()
