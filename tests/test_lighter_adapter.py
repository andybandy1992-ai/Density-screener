from __future__ import annotations

from datetime import datetime, timezone
import unittest

from density_screener.exchanges.base import OrderBookState
from density_screener.exchanges.lighter import LighterAdapter


class LighterAdapterTests(unittest.TestCase):
    def test_order_book_snapshot_and_delta_apply_cleanly(self) -> None:
        initial = {
            "asks": [{"price": "2246.91", "size": "1.0894"}],
            "bids": [
                {"price": "2246.90", "size": "0.5000"},
                {"price": "2246.89", "size": "1.2500"},
            ],
        }
        delta = {
            "asks": [{"price": "2246.91", "size": "1.0888"}],
            "bids": [{"price": "2246.90", "size": "0.0000"}],
        }
        state = OrderBookState(exchange="lighter", symbol="ETH", market_type="futures", tick_size=0.01)
        state.replace(
            LighterAdapter._parse_side(initial["bids"]),
            LighterAdapter._parse_side(initial["asks"]),
        )
        state.apply_delta(
            LighterAdapter._parse_side(delta["bids"]),
            LighterAdapter._parse_side(delta["asks"]),
        )
        snapshot = state.to_snapshot(datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc))

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.best_bid, 2246.89)
        self.assertEqual(snapshot.best_ask, 2246.91)
        self.assertAlmostEqual(snapshot.asks[0].quantity, 1.0888)

    def test_average_notional_prefers_quote_volume_field(self) -> None:
        candles = [
            {"c": 2000.0, "v": 10.0, "V": 20500.0},
            {"c": 2010.0, "v": 9.0, "V": 18000.0},
        ]

        average = LighterAdapter._average_notional_from_candles(candles)

        self.assertEqual(average, 19250.0)

    def test_supported_spot_symbol_requires_stable_quote(self) -> None:
        self.assertTrue(LighterAdapter._is_supported_spot_symbol("ETH/USDC"))
        self.assertFalse(LighterAdapter._is_supported_spot_symbol("ETH/BTC"))


if __name__ == "__main__":
    unittest.main()
