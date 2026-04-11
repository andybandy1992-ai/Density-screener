from __future__ import annotations

from datetime import datetime, timezone
import unittest

from density_screener.exchanges.base import OrderBookState
from density_screener.exchanges.bybit_spot import BybitSpotAdapter
from density_screener.settings import DetectionConfig


def make_detection_config() -> DetectionConfig:
    return DetectionConfig(
        volume_multiplier=5.0,
        rolling_candle_count=14,
        candle_interval="5m",
        spot_min_notional_usd=50_000.0,
        futures_min_notional_usd=10_000.0,
        price_window_pct=5.0,
        min_lifetime_seconds=5.0,
        same_price_cooldown_seconds=60.0,
        symmetry_notional_tolerance_pct=20.0,
        symmetry_distance_tolerance_pct=15.0,
        suppress_top_ticks=0,
    )


class OrderBookStateTests(unittest.TestCase):
    def test_replace_and_delta_produce_snapshot(self) -> None:
        state = OrderBookState(exchange="bybit_spot", symbol="BTCUSDT", market_type="spot", tick_size=0.1)
        state.replace([(100.0, 5.0), (99.9, 2.0)], [(100.1, 3.0), (100.2, 7.0)])
        state.apply_delta([(100.0, 4.0), (99.8, 1.0)], [(100.2, 0.0)])
        snapshot = state.to_snapshot(datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc))

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.best_bid, 100.0)
        self.assertEqual(snapshot.best_ask, 100.1)
        self.assertEqual(snapshot.bids[0].notional, 400.0)
        self.assertEqual(len(snapshot.asks), 1)

    def test_bybit_parser_handles_snapshot_and_delta(self) -> None:
        state = OrderBookState(exchange="bybit_spot", symbol="BTCUSDT", market_type="spot", tick_size=0.1)
        states = {"BTCUSDT": state}

        BybitSpotAdapter._apply_message(
            states,
            {
                "type": "snapshot",
                "data": {
                    "s": "BTCUSDT",
                    "b": [["100.0", "5.0"]],
                    "a": [["100.1", "6.0"]],
                },
            },
        )
        BybitSpotAdapter._apply_message(
            states,
            {
                "type": "delta",
                "data": {
                    "s": "BTCUSDT",
                    "b": [["100.0", "4.0"], ["99.9", "2.0"]],
                    "a": [["100.1", "0.0"], ["100.2", "3.0"]],
                },
            },
        )

        snapshot = state.to_snapshot(datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc))
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.best_bid, 100.0)
        self.assertEqual(snapshot.best_ask, 100.2)


if __name__ == "__main__":
    unittest.main()
