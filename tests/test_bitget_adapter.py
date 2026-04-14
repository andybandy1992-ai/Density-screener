from __future__ import annotations

from datetime import datetime, timezone
import unittest

from density_screener.exchanges.base import ExchangeInstrument, OrderBookState
from density_screener.exchanges.bitget_spot import BitgetSpotAdapter
from density_screener.models import VolumeReference
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


class BitgetBootstrapTests(unittest.IsolatedAsyncioTestCase):
    async def test_bootstrap_skips_timed_out_symbol_and_keeps_rest(self) -> None:
        adapter = BitgetSpotAdapter(make_config(), bootstrap_retry_attempts=1)
        instruments = [
            ExchangeInstrument("bitget_spot", "OKUSDT", "spot", 0.1),
            ExchangeInstrument("bitget_spot", "BADUSDT", "spot", 0.1),
        ]

        async def fake_bootstrap(instrument, *, session=None):
            if instrument.symbol == "BADUSDT":
                raise TimeoutError()
            return VolumeReference(avg_candle_notional=12_345.0, candle_count=14, interval="5m")

        adapter.bootstrap_volume_reference = fake_bootstrap  # type: ignore[method-assign]

        references = await adapter._bootstrap_all_volumes(instruments)

        self.assertIn("OKUSDT", references)
        self.assertNotIn("BADUSDT", references)


if __name__ == "__main__":
    unittest.main()
