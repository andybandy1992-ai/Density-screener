from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import unittest

from density_screener.health import HealthMonitor, SystemMetrics


class HealthMonitorTests(unittest.TestCase):
    def test_format_report_contains_system_and_exchange_status(self) -> None:
        monitor = HealthMonitor(
            telegram_enabled=True,
            control_bot_enabled=True,
            control_user_ids=("417736336",),
            control_state_path=Path("/tmp/runtime_controls.json"),
            system_metrics_provider=lambda: None,
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

    def test_blank_exception_is_rendered_with_class_name(self) -> None:
        monitor = HealthMonitor(
            telegram_enabled=True,
            control_bot_enabled=True,
            control_user_ids=("417736336",),
            control_state_path=Path("/tmp/runtime_controls.json"),
            system_metrics_provider=lambda: None,
        )

        monitor.mark_failure("bitget_spot", TimeoutError(), market_type="spot")
        report = monitor.format_report(now=datetime(2026, 4, 11, 12, 0, 10, tzinfo=timezone.utc))

        self.assertIn("error=TimeoutError", report)

    def test_format_report_contains_system_metrics_when_available(self) -> None:
        monitor = HealthMonitor(
            telegram_enabled=True,
            control_bot_enabled=True,
            control_user_ids=("417736336",),
            control_state_path=Path("/tmp/runtime_controls.json"),
            system_metrics_provider=lambda: SystemMetrics(
                load_average=(0.25, 0.5, 0.75),
                memory_total_bytes=1024 * 1024 * 1024,
                memory_available_bytes=512 * 1024 * 1024,
                disk_total_bytes=10 * 1024 * 1024 * 1024,
                disk_free_bytes=7 * 1024 * 1024 * 1024,
                network_rx_bytes=5 * 1024 * 1024,
                network_tx_bytes=2 * 1024 * 1024,
            ),
        )

        report = monitor.format_report(now=datetime(2026, 4, 11, 12, 0, 10, tzinfo=timezone.utc))

        self.assertIn("System:", report)
        self.assertIn("Load avg: 0.25 / 0.50 / 0.75", report)
        self.assertIn("Memory: 512.0 MB / 1.0 GB (50%)", report)
        self.assertIn("Disk /: 3.0 GB / 10.0 GB (30%)", report)
        self.assertIn("Network since boot: rx=5.0 MB tx=2.0 MB", report)


if __name__ == "__main__":
    unittest.main()
