from __future__ import annotations

from datetime import datetime, timezone
import gzip
import json
import unittest

from density_screener.exchanges.htx_spot import HTXSpotAdapter
from density_screener.exchanges.base import OrderBookState


class HTXAdapterTests(unittest.TestCase):
    def test_order_book_snapshot_from_step0_shape(self) -> None:
        tick = {
            "bids": [[72773.76, 0.105305], [72772.05, 0.024569]],
            "asks": [[72773.77, 0.021], [72774.01, 0.31]],
        }
        state = OrderBookState(exchange="htx", symbol="btcusdt", market_type="spot", tick_size=0.01)
        state.replace(
            [(float(price), float(size)) for price, size in tick["bids"]],
            [(float(price), float(size)) for price, size in tick["asks"]],
        )
        snapshot = state.to_snapshot(datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc))

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.best_bid, 72773.76)
        self.assertEqual(snapshot.best_ask, 72773.77)
        self.assertGreater(snapshot.asks[0].notional, 1000)

    def test_binary_decoder_returns_dict(self) -> None:
        payload = {"ping": 123456}
        encoded = gzip.compress(json.dumps(payload).encode("utf-8"))

        decoded = HTXSpotAdapter._decode_binary_message(encoded)

        self.assertEqual(decoded["ping"], 123456)

    def test_volume_reference_from_payload_returns_none_without_data(self) -> None:
        reference = HTXSpotAdapter._volume_reference_from_payload(
            {},
            interval="5m",
            rolling_candle_count=14,
        )

        self.assertIsNone(reference)

    def test_volume_reference_from_payload_uses_turnover(self) -> None:
        reference = HTXSpotAdapter._volume_reference_from_payload(
            {
                "data": [
                    {"vol": "120000"},
                    {"vol": "80000"},
                ]
            },
            interval="5m",
            rolling_candle_count=14,
        )

        self.assertIsNotNone(reference)
        assert reference is not None
        self.assertEqual(reference.avg_candle_notional, 100000.0)
        self.assertEqual(reference.candle_count, 2)
