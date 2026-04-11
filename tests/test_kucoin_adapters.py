from __future__ import annotations

from datetime import datetime, timezone
import unittest

from density_screener.exchanges.base import OrderBookState
from density_screener.exchanges.kucoin_futures import KuCoinFuturesAdapter
from density_screener.exchanges.kucoin_spot import KuCoinSpotAdapter
from density_screener.settings import DetectionConfig


def make_detection_config() -> DetectionConfig:
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


class KuCoinAdapterTests(unittest.TestCase):
    def test_topic_generation_matches_confirmed_live_shape(self) -> None:
        self.assertEqual(
            KuCoinSpotAdapter(make_detection_config())._topic_for("BTC-USDT"),
            "/spotMarket/level2Depth50:BTC-USDT",
        )
        self.assertEqual(
            KuCoinFuturesAdapter(make_detection_config())._topic_for("XBTUSDTM"),
            "/contractMarket/level2Depth50:XBTUSDTM",
        )

    def test_order_book_snapshot_from_live_like_payload(self) -> None:
        state = OrderBookState(exchange="kucoin_spot", symbol="BTC-USDT", market_type="spot", tick_size=0.1)
        bids = [("72778.4", "0.43533157"), ("72778.3", "0.00288547")]
        asks = [("72778.5", "0.21078575"), ("72778.6", "0.32471839")]
        state.replace(
            [(float(price), float(size)) for price, size in bids],
            [(float(price), float(size)) for price, size in asks],
        )
        snapshot = state.to_snapshot(datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc))

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.best_bid, 72778.4)
        self.assertEqual(snapshot.best_ask, 72778.5)
        self.assertGreater(snapshot.bids[0].notional, 30000)


if __name__ == "__main__":
    unittest.main()
