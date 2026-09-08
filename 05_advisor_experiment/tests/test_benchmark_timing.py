"""Wall time must not be confused with the unthrottled engine update loop."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from run_observer_smoke import benchmark_metrics


class TimingTest(unittest.TestCase):
    def test_engine_update_speed_uses_simulated_seconds_and_milliseconds(self):
        measured = benchmark_metrics("Performed 1805 updates in 545.944 ms\navg: 0.302 ms", 1805)
        self.assertAlmostEqual(measured["simulated_seconds"], 1805 / 60)
        self.assertEqual(measured["update_seconds"], 0.545944)
        self.assertAlmostEqual(measured["update_speed_vs_realtime"], 55.10333, places=5)
        self.assertNotIn("total_speed_vs_realtime", measured)

    def test_incomplete_mismatched_or_repeated_benchmarks_cannot_report_speed(self):
        for log in ("", "Performed 99 updates in 10 ms", "Performed 100 updates in 0 ms",
                    "Performed 100 updates in 10 ms\nPerformed 100 updates in 11 ms"):
            with self.subTest(log=log), self.assertRaises(RuntimeError):
                benchmark_metrics(log, 100)


if __name__ == "__main__":
    unittest.main()
