from __future__ import annotations

from pathlib import Path
import os
import unittest

from density_screener.settings import load_config


class SettingsTests(unittest.TestCase):
    def test_load_config_reads_exchange_map(self) -> None:
        path = (
            Path(__file__).resolve().parent.parent
            / "tests"
            / "fixtures"
            / "sample_app.toml"
        )
        config = load_config(path)

        self.assertTrue(config.strict_mode)
        self.assertEqual(config.control_state_file, "../state/runtime_controls.json")
        self.assertEqual(config.control_state_path.name, "runtime_controls.json")
        self.assertEqual(config.global_blacklist, ("AAAUSDT",))
        self.assertEqual(config.blacklist_file, "blacklist.txt")
        self.assertIn("bybit_spot", config.exchanges)
        self.assertEqual(config.exchanges["bybit_spot"].market_type, "spot")
        self.assertTrue(config.blacklist.matches("AAAUSDT"))
        self.assertTrue(config.blacklist.matches("BTCUSDT", {"baseCoin": "BTC"}))
        self.assertTrue(config.blacklist.matches("FOO_TEST_BAR"))

    def test_env_overrides_telegram_settings(self) -> None:
        path = (
            Path(__file__).resolve().parent.parent
            / "tests"
            / "fixtures"
            / "sample_app.toml"
        )
        old_enabled = os.environ.get("TELEGRAM_ENABLED")
        old_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        old_chat = os.environ.get("TELEGRAM_CHAT_ID")
        try:
            os.environ["TELEGRAM_ENABLED"] = "true"
            os.environ["TELEGRAM_BOT_TOKEN"] = "env-token"
            os.environ["TELEGRAM_CHAT_ID"] = "env-chat"
            config = load_config(path)
        finally:
            _restore_env("TELEGRAM_ENABLED", old_enabled)
            _restore_env("TELEGRAM_BOT_TOKEN", old_token)
            _restore_env("TELEGRAM_CHAT_ID", old_chat)

        self.assertTrue(config.telegram.enabled)
        self.assertEqual(config.telegram.bot_token, "env-token")
        self.assertEqual(config.telegram.chat_id, "env-chat")

    def test_env_overrides_detection_thresholds(self) -> None:
        path = (
            Path(__file__).resolve().parent.parent
            / "tests"
            / "fixtures"
            / "sample_app.toml"
        )
        old_spot = os.environ.get("SPOT_MIN_NOTIONAL_USD")
        old_futures = os.environ.get("FUTURES_MIN_NOTIONAL_USD")
        try:
            os.environ["SPOT_MIN_NOTIONAL_USD"] = "75000"
            os.environ["FUTURES_MIN_NOTIONAL_USD"] = "250000"
            config = load_config(path)
        finally:
            _restore_env("SPOT_MIN_NOTIONAL_USD", old_spot)
            _restore_env("FUTURES_MIN_NOTIONAL_USD", old_futures)

        self.assertEqual(config.detection.spot_min_notional_usd, 75000.0)
        self.assertEqual(config.detection.futures_min_notional_usd, 250000.0)

    def test_env_overrides_control_user_ids(self) -> None:
        path = (
            Path(__file__).resolve().parent.parent
            / "tests"
            / "fixtures"
            / "sample_app.toml"
        )
        old_control_users = os.environ.get("TELEGRAM_CONTROL_USER_IDS")
        try:
            os.environ["TELEGRAM_CONTROL_USER_IDS"] = "417736336,123456789"
            config = load_config(path)
        finally:
            _restore_env("TELEGRAM_CONTROL_USER_IDS", old_control_users)

        self.assertEqual(config.telegram.control_user_ids, ("417736336", "123456789"))


def _restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
