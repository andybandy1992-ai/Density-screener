from __future__ import annotations

from datetime import datetime, timezone
import unittest

from density_screener.exchanges.base import OrderBookState


class AsterAdapterTests(unittest.TestCase):
    def test_order_book_snapshot_from_depth20_shape(self) -> None:
        payload = {
            "b": [["72736.7", "0.043"], ["72733.7", "3.711"]],
            "a": [["72736.8", "0.791"], ["72738.7", "0.004"]],
        }
        state = OrderBookState(exchange="aster", symbol="BTCUSDT", market_type="futures", tick_size=0.1)
        state.replace(
            [(float(price), float(size)) for price, size in payload["b"]],
            [(float(price), float(size)) for price, size in payload["a"]],
        )
        snapshot = state.to_snapshot(datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc))

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.best_bid, 72736.7)
        self.assertEqual(snapshot.best_ask, 72736.8)
        self.assertGreater(snapshot.bids[1].notional, 200000)
