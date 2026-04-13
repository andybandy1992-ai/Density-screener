from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from density_screener.detector import DensityDetector
from density_screener.models import BookLevel, OrderBookSnapshot, VolumeReference
from density_screener.settings import DetectionConfig


def make_config() -> DetectionConfig:
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


def make_snapshot(
    now: datetime,
    *,
    symbol: str = "BTCUSDT",
    bid_notional: float = 120_000.0,
    ask_notional: float = 10_000.0,
) -> OrderBookSnapshot:
    return OrderBookSnapshot(
        exchange="test",
        symbol=symbol,
        market_type="spot",
        best_bid=100.0,
        best_ask=100.1,
        bids=(
            BookLevel(price=99.5, quantity=bid_notional / 99.5, notional=bid_notional),
        ),
        asks=(
            BookLevel(price=100.8, quantity=ask_notional / 100.8, notional=ask_notional),
        ),
        timestamp=now,
        tick_size=0.1,
    )


class DensityDetectorTests(unittest.TestCase):
    def test_signal_appears_only_after_min_lifetime(self) -> None:
        detector = DensityDetector(make_config())
        ref = VolumeReference(avg_candle_notional=20_000.0, candle_count=14, interval="5m")
        started = datetime(2026, 4, 11, 12, 0, 0, tzinfo=timezone.utc)

        early_signal_count = 0
        late_signals = []
        for second in range(7):
            now = started + timedelta(seconds=second)
            snapshot = make_snapshot(now)
            signals = detector.process(snapshot, ref, now)
            if second < 5:
                early_signal_count += len(signals)
            else:
                late_signals.extend(signals)

        self.assertEqual(early_signal_count, 0)
        self.assertEqual(len(late_signals), 1)
        self.assertEqual(late_signals[0].price, 99.5)

    def test_same_price_is_not_alerted_twice_during_cooldown(self) -> None:
        detector = DensityDetector(make_config())
        ref = VolumeReference(avg_candle_notional=20_000.0, candle_count=14, interval="5m")
        started = datetime(2026, 4, 11, 12, 0, 0, tzinfo=timezone.utc)

        emitted = []
        for second in range(12):
            now = started + timedelta(seconds=second)
            snapshot = make_snapshot(now)
            emitted.extend(detector.process(snapshot, ref, now))

        self.assertEqual(len(emitted), 1)

    def test_symmetric_levels_are_filtered_out(self) -> None:
        detector = DensityDetector(make_config())
        ref = VolumeReference(avg_candle_notional=20_000.0, candle_count=14, interval="5m")
        now = datetime(2026, 4, 11, 12, 0, 0, tzinfo=timezone.utc)
        snapshot = make_snapshot(now, bid_notional=120_000.0, ask_notional=118_000.0)

        for second in range(7):
            current = now + timedelta(seconds=second)
            current_snapshot = OrderBookSnapshot(
                exchange=snapshot.exchange,
                symbol=snapshot.symbol,
                market_type=snapshot.market_type,
                best_bid=snapshot.best_bid,
                best_ask=snapshot.best_ask,
                bids=snapshot.bids,
                asks=snapshot.asks,
                timestamp=current,
                tick_size=snapshot.tick_size,
            )
            signals = detector.process(current_snapshot, ref, current)

        self.assertEqual(signals, [])

    def test_other_symbols_do_not_clear_existing_candidates(self) -> None:
        detector = DensityDetector(make_config())
        ref = VolumeReference(avg_candle_notional=20_000.0, candle_count=14, interval="5m")
        started = datetime(2026, 4, 11, 12, 0, 0, tzinfo=timezone.utc)

        for second in range(5):
            detector.process(make_snapshot(started + timedelta(seconds=second), symbol="BTCUSDT"), ref)
            detector.process(
                make_snapshot(
                    started + timedelta(seconds=second, milliseconds=500),
                    symbol="ETHUSDT",
                    bid_notional=5_000.0,
                    ask_notional=5_000.0,
                ),
                ref,
            )

        signals = detector.process(make_snapshot(started + timedelta(seconds=5), symbol="BTCUSDT"), ref)

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].symbol, "BTCUSDT")


if __name__ == "__main__":
    unittest.main()
