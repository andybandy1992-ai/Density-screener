from __future__ import annotations

from datetime import datetime, timezone
import unittest

from density_screener.exchanges.base import OrderBookState
from density_screener.exchanges.hyperliquid import HyperliquidAdapter


class HyperliquidAdapterTests(unittest.TestCase):
    def test_order_book_snapshot_from_l2book_shape(self) -> None:
        payload = {
            "coin": "BTC",
            "levels": [
                [{"px": "72736.0", "sz": "3.03441", "n": 14}],
                [{"px": "72737.0", "sz": "1.12", "n": 9}],
            ],
        }
        state = OrderBookState(exchange="hyperliquid", symbol="BTC", market_type="futures", tick_size=None)
        state.replace(
            [(float(level["px"]), float(level["sz"])) for level in payload["levels"][0]],
            [(float(level["px"]), float(level["sz"])) for level in payload["levels"][1]],
        )
        snapshot = state.to_snapshot(datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc))

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.best_bid, 72736.0)
        self.assertEqual(snapshot.best_ask, 72737.0)
        self.assertGreater(snapshot.bids[0].notional, 200000)

    def test_volume_reference_from_candles_uses_notional(self) -> None:
        reference = HyperliquidAdapter._volume_reference_from_candles(
            [
                {"v": "10", "c": "2000"},
                {"v": "6", "c": "2500"},
            ],
            interval="5m",
            rolling_candle_count=14,
        )

        self.assertEqual(reference.avg_candle_notional, 17500.0)
        self.assertEqual(reference.candle_count, 2)

    def test_l2book_levels_are_aggregated_into_narrow_price_buckets(self) -> None:
        levels = [
            (2315.80, 600.0),
            (2315.90, 700.0),
            (2316.25, 10.0),
        ]

        aggregated = HyperliquidAdapter._aggregate_levels(
            levels,
            side="ask",
            mid_price=2315.0,
        )

        self.assertLess(len(aggregated), len(levels))
        self.assertAlmostEqual(aggregated[0][0], 2315.5)
        self.assertGreater(aggregated[0][0] * aggregated[0][1], 3_000_000)
