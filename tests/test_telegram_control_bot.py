from __future__ import annotations

import unittest

from density_screener.blacklist import BlacklistMatcher
from density_screener.health import HealthMonitor
from density_screener.runtime_controls import RuntimeControlSnapshot
from density_screener.telegram_control_panel import TelegramControlBot
from density_screener.settings import TelegramConfig


class TelegramControlBotTests(unittest.TestCase):
    def test_panel_markup_contains_threshold_and_blacklist_actions(self) -> None:
        markup = TelegramControlBot.build_panel_markup()
        callback_actions = {
            button["callback_data"]
            for row in markup["inline_keyboard"]
            for button in row
        }

        self.assertIn("threshold:spot:10000", callback_actions)
        self.assertIn("threshold:futures:custom", callback_actions)
        self.assertIn("blacklist:add", callback_actions)
        self.assertIn("panel:health", callback_actions)

    def test_panel_formatter_contains_current_values(self) -> None:
        snapshot = RuntimeControlSnapshot(
            spot_min_notional_usd=50_000.0,
            futures_min_notional_usd=125_000.0,
            blacklist_terms=("BTC", "symbol:ETHUSDT"),
            dynamic_blacklist=BlacklistMatcher.load(inline_terms=["BTC", "symbol:ETHUSDT"]),
            combined_blacklist=BlacklistMatcher.load(inline_terms=["BTC", "symbol:ETHUSDT"]),
        )

        text = TelegramControlBot.format_panel(snapshot)

        self.assertIn("50,000", text)
        self.assertIn("125,000", text)
        self.assertIn("BTC", text)
        self.assertIn("/health", text)

    def test_numeric_parser_accepts_common_user_input(self) -> None:
        self.assertEqual(TelegramControlBot._parse_numeric_input("50,000"), 50000.0)
        self.assertEqual(TelegramControlBot._parse_numeric_input(" 125000 "), 125000.0)
        self.assertIsNone(TelegramControlBot._parse_numeric_input("abc"))

    def test_enabled_requires_token_and_chat(self) -> None:
        bot = TelegramControlBot(
            TelegramConfig(enabled=True, bot_token="token123", chat_id="-1001"),
            controls=type("DummyControls", (), {"snapshot": lambda self: None})(),  # type: ignore[arg-type]
        )

        self.assertTrue(bot.enabled)

    def test_authorization_prefers_control_user_ids_when_configured(self) -> None:
        bot = TelegramControlBot(
            TelegramConfig(
                enabled=True,
                bot_token="token123",
                chat_id="-1001",
                control_user_ids=("417736336",),
            ),
            controls=type("DummyControls", (), {"snapshot": lambda self: None})(),  # type: ignore[arg-type]
        )

        self.assertTrue(bot._is_authorized("417736336", 417736336))
        self.assertFalse(bot._is_authorized("-1001", 999999999))

    def test_health_report_uses_monitor_when_attached(self) -> None:
        monitor = HealthMonitor(
            telegram_enabled=True,
            control_bot_enabled=True,
            control_user_ids=("417736336",),
            control_state_path=None,
        )
        monitor.register_exchange("bitget_spot", "spot")
        monitor.mark_snapshot("bitget_spot", market_type="spot", signals_emitted=1)
        bot = TelegramControlBot(
            TelegramConfig(
                enabled=True,
                bot_token="token123",
                chat_id="-1001",
                control_user_ids=("417736336",),
            ),
            controls=type("DummyControls", (), {"snapshot": lambda self: None})(),  # type: ignore[arg-type]
            health_monitor=monitor,
        )

        report = bot._format_health_report()

        self.assertIn("Density Screener Health", report)
        self.assertIn("bitget_spot", report)


if __name__ == "__main__":
    unittest.main()
