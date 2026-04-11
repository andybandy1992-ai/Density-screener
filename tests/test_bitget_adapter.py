from __future__ import annotations

from datetime import datetime, timezone
import unittest

from density_screener.exchanges.base import OrderBookState


class BitgetAdapterTests(unittest.TestCase):
    def test_snapshot_shape_maps_into_order_book_state(self) -> None:
        payload = {
            "data": [
                {
                    "asks": [["100.2", "3.0"], ["100.3", "4.0"]],
                    "bids": [["100.1", "2.0"], ["100.0", "5.0"]],
                    "ts": "1746698732562",
                }
            ],
            "arg": {
                "instType": "SPOT",
                "instId": "BTCUSDT",
                "channel": "books15",
            },
        }
        state = OrderBookState(exchange="bitget_spot", symbol="BTCUSDT", market_type="spot", tick_size=0.1)
        data = payload["data"][0]
        state.replace(
            [(float(price), float(size)) for price, size in data["bids"]],
            [(float(price), float(size)) for price, size in data["asks"]],
        )
        snapshot = state.to_snapshot(datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc))

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.best_bid, 100.1)
        self.assertEqual(snapshot.best_ask, 100.2)
        self.assertEqual(snapshot.bids[0].notional, 200.2)


if __name__ == "__main__":
    unittest.main()
