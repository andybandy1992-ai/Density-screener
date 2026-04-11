from __future__ import annotations

from datetime import datetime, timedelta, timezone

from density_screener.detector import DensityDetector
from density_screener.models import BookLevel, OrderBookSnapshot, VolumeReference
from density_screener.settings import DetectionConfig


def run_debug_simulation() -> list[str]:
    config = DetectionConfig(
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
    detector = DensityDetector(config)
    volume_reference = VolumeReference(avg_candle_notional=20_000.0, candle_count=14, interval="5m")
    started_at = datetime(2026, 4, 11, 12, 0, 0, tzinfo=timezone.utc)
    results: list[str] = []

    for second in range(7):
        now = started_at + timedelta(seconds=second)
        snapshot = OrderBookSnapshot(
            exchange="debug",
            symbol="BTCUSDT",
            market_type="spot",
            best_bid=100.0,
            best_ask=100.1,
            bids=(
                BookLevel(price=99.5, quantity=1200.0, notional=119_400.0),
                BookLevel(price=99.0, quantity=100.0, notional=9_900.0),
            ),
            asks=(
                BookLevel(price=100.8, quantity=100.0, notional=10_080.0),
            ),
            timestamp=now,
            tick_size=0.1,
        )
        signals = detector.process(snapshot, volume_reference, now=now)
        for signal in signals:
            results.append(
                f"{signal.symbol} {signal.side} {signal.price:.2f} "
                f"resting={signal.resting_seconds:.1f}s ratio={signal.ratio_to_average:.2f}"
            )

    return results
