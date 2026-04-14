from __future__ import annotations

from contextlib import suppress
import os
from pathlib import Path
import unittest
from uuid import uuid4

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
        state_dir = Path(__file__).resolve().parent.parent / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        state_path = state_dir / f"runtime_controls_test_{os.getpid()}_{uuid4().hex}.json"
        try:
            store = RuntimeControlStore(
                state_path,
                make_detection_config(),
                BlacklistMatcher.load(inline_terms=["symbol:AAAUSDT"]),
            )

            self.assertEqual(store.min_notional_for("spot"), 50_000.0)
            self.assertEqual(store.volume_multiplier_for("spot"), 5.0)
            self.assertTrue(store.matches_blacklist("AAAUSDT"))

            store.set_min_notional("spot", 75_000.0)
            store.set_exchange_min_notional("bitget_spot", 90_000.0)
            store.set_volume_multiplier("futures", 7.5)
            store.add_blacklist_term("BTC")

            reloaded = RuntimeControlStore(
                state_path,
                make_detection_config(),
                BlacklistMatcher.load(inline_terms=["symbol:AAAUSDT"]),
            )

            self.assertEqual(reloaded.min_notional_for("spot"), 75_000.0)
            self.assertEqual(reloaded.min_notional_for_exchange("bitget_spot", "spot"), 90_000.0)
            self.assertEqual(reloaded.volume_multiplier_for("futures"), 7.5)
            self.assertTrue(reloaded.matches_blacklist("BTCUSDT"))
            self.assertEqual(reloaded.snapshot().blacklist_terms, ("BTC",))
        finally:
            if state_path.exists():
                with suppress(PermissionError):
                    state_path.unlink()

    def test_remove_blacklist_term_raises_when_missing(self) -> None:
        state_dir = Path(__file__).resolve().parent.parent / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        state_path = state_dir / f"runtime_controls_test_missing_{os.getpid()}_{uuid4().hex}.json"
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

    def test_legacy_comma_separated_blacklist_entries_are_split_on_load(self) -> None:
        state_dir = Path(__file__).resolve().parent.parent / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        state_path = state_dir / f"runtime_controls_test_legacy_{os.getpid()}_{uuid4().hex}.json"
        try:
            state_path.write_text(
                (
                    "{\n"
                    '  "spot_min_notional_usd": 50000,\n'
                    '  "futures_min_notional_usd": 100000,\n'
                    '  "spot_volume_multiplier": 4.5,\n'
                    '  "futures_volume_multiplier": 6.0,\n'
                    '  "exchange_min_notional_usd": {"lighter": 70000},\n'
                    '  "blacklist_terms": ["BTC, ETH", "symbol:SOLUSDT"]\n'
                    "}\n"
                ),
                encoding="utf-8",
            )

            store = RuntimeControlStore(
                state_path,
                make_detection_config(),
                BlacklistMatcher.load(),
            )

            self.assertEqual(store.snapshot().blacklist_terms, ("BTC", "ETH", "symbol:SOLUSDT"))
            self.assertEqual(store.volume_multiplier_for("spot"), 4.5)
            self.assertEqual(store.volume_multiplier_for("futures"), 6.0)
            self.assertEqual(store.min_notional_for_exchange("lighter", "futures"), 70_000.0)
            self.assertTrue(store.matches_blacklist("BTCUSDT"))
            self.assertTrue(store.matches_blacklist("ETHUSDT"))
            self.assertTrue(store.matches_blacklist("SOLUSDT"))
        finally:
            if state_path.exists():
                with suppress(PermissionError):
                    state_path.unlink()


if __name__ == "__main__":
    unittest.main()
