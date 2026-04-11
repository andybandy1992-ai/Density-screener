from __future__ import annotations

from contextlib import suppress
from pathlib import Path
import unittest

from density_screener.blacklist import BlacklistMatcher
from density_screener.runtime_controls import RuntimeControlStore
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


class RuntimeControlStoreTests(unittest.TestCase):
    def test_defaults_and_blacklist_persist(self) -> None:
        state_path = Path(__file__).resolve().parent.parent / "state" / "runtime_controls_test.json"
        if state_path.exists():
            with suppress(PermissionError):
                state_path.unlink()
        try:
            store = RuntimeControlStore(
                state_path,
                make_detection_config(),
                BlacklistMatcher.load(inline_terms=["symbol:AAAUSDT"]),
            )

            self.assertEqual(store.min_notional_for("spot"), 50_000.0)
            self.assertTrue(store.matches_blacklist("AAAUSDT"))

            store.set_min_notional("spot", 75_000.0)
            store.add_blacklist_term("BTC")

            reloaded = RuntimeControlStore(
                state_path,
                make_detection_config(),
                BlacklistMatcher.load(inline_terms=["symbol:AAAUSDT"]),
            )

            self.assertEqual(reloaded.min_notional_for("spot"), 75_000.0)
            self.assertTrue(reloaded.matches_blacklist("BTCUSDT"))
            self.assertEqual(reloaded.snapshot().blacklist_terms, ("BTC",))
        finally:
            if state_path.exists():
                with suppress(PermissionError):
                    state_path.unlink()

    def test_remove_blacklist_term_raises_when_missing(self) -> None:
        state_path = Path(__file__).resolve().parent.parent / "state" / "runtime_controls_test_missing.json"
        if state_path.exists():
            with suppress(PermissionError):
                state_path.unlink()
        try:
            store = RuntimeControlStore(
                state_path,
                make_detection_config(),
                BlacklistMatcher.load(),
            )

            with self.assertRaises(ValueError):
                store.remove_blacklist_term("BTC")
        finally:
            if state_path.exists():
                with suppress(PermissionError):
                    state_path.unlink()


if __name__ == "__main__":
    unittest.main()
