from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import unittest

from density_screener.detector import DensityDetector
from density_screener.models import BookLevel, OrderBookSnapshot, VolumeReference
from density_screener.runtime import ScreenerRuntime
from density_screener.settings import DetectionConfig


def make_config() -> DetectionConfig:
    return DetectionConfig(
        volume_multiplier=5.0,
        rolling_candle_count=14,
        candle_interval="5m",
        spot_min_notional_usd=50_000.0,
        futures_min_notional_usd=100_000.0,
        price_window_pct=5.0,
        min_lifetime_seconds=5.0,
        same_price_cooldown_seconds=60.0,
        symmetry_notional_tolerance_pct=20.0,
        symmetry_distance_tolerance_pct=15.0,
        suppress_top_ticks=0,
    )


def make_snapshot(now: datetime) -> OrderBookSnapshot:
    return OrderBookSnapshot(
        exchange="bybit_spot",
        symbol="ICPUSDT",
        market_type="spot",
        best_bid=2.4590,
        best_ask=2.4600,
        bids=(BookLevel(price=2.4070, quantity=35000.0, notional=84_245.0),),
        asks=(BookLevel(price=2.5200, quantity=1000.0, notional=2_520.0),),
        timestamp=now,
        tick_size=0.0001,
    )


class _BrokenNotifier:
    async def send(self, signal) -> bool:
        raise RuntimeError("rate limited")


class RuntimeTests(unittest.TestCase):
    def test_notifier_errors_do_not_break_snapshot_handling(self) -> None:
        detector = DensityDetector(make_config())
        runtime = ScreenerRuntime(detector, notifier=_BrokenNotifier())  # type: ignore[arg-type]
        reference = VolumeReference(avg_candle_notional=10_000.0, candle_count=14, interval="5m")
        started = datetime(2026, 4, 13, 20, 0, 0, tzinfo=timezone.utc)

        for second in range(5):
            asyncio.run(runtime.handle_snapshot(make_snapshot(started.replace(second=second)), reference))

        signals = asyncio.run(runtime.handle_snapshot(make_snapshot(started.replace(second=5)), reference))

        self.assertEqual(len(signals), 1)
        self.assertEqual(runtime.stats.signals_emitted, 1)


if __name__ == "__main__":
    unittest.main()
