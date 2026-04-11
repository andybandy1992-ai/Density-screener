from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import unittest

from density_screener.health import HealthMonitor


class HealthMonitorTests(unittest.TestCase):
    def test_format_report_contains_system_and_exchange_status(self) -> None:
        monitor = HealthMonitor(
            telegram_enabled=True,
            control_bot_enabled=True,
            control_user_ids=("417736336",),
            control_state_path=Path("/tmp/runtime_controls.json"),
        )
        monitor.register_exchange("bitget_spot", "spot")
        monitor.mark_snapshot(
            "bitget_spot",
            market_type="spot",
            snapshot_time=datetime(2026, 4, 11, 12, 0, 0, tzinfo=timezone.utc),
            signals_emitted=2,
        )
        monitor.register_exchange("bybit_spot", "spot")
        monitor.mark_failure("bybit_spot", "bootstrap failed", market_type="spot")

        report = monitor.format_report(now=datetime(2026, 4, 11, 12, 0, 10, tzinfo=timezone.utc))

        self.assertIn("Density Screener Health", report)
        self.assertIn("Telegram alerts: enabled", report)
        self.assertIn("bitget_spot: RUNNING", report)
        self.assertIn("bybit_spot: FAILED", report)


if __name__ == "__main__":
    unittest.main()
