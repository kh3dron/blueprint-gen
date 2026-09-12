"""Passive acceleration keeps the original measurement and restores action speed."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_feed import idle_window


class IdleWindowTest(unittest.TestCase):
    def driver(self):
        client=Mock()
        client.call.return_value={"speed":10}
        return SimpleNamespace(session=SimpleNamespace(client=client),action=Mock())

    def test_faster_wait_keeps_all_ticks_and_returns_complete_evidence(self):
        driver=self.driver()
        driver.action.return_value={"outcome":{"idle_ticks":3600,"receipt":"complete"}}
        self.assertEqual(idle_window(driver,"measure",40),driver.action.return_value)
        driver.action.assert_called_once_with("wait_feed",{"ticks":3600},"measure")
        self.assertEqual([call.args[0] for call in driver.session.client.call.call_args_list],
            [{"op":"status"},{"op":"speed","speed":40},{"op":"speed","speed":10}])

    def test_failed_measurement_still_restores_action_speed_and_raises(self):
        driver=self.driver()
        driver.action.side_effect=RuntimeError("player intervened")
        with self.assertRaisesRegex(RuntimeError,"player intervened"):
            idle_window(driver,"measure",40)
        self.assertEqual(driver.session.client.call.call_args.args[0],{"op":"speed","speed":10})
