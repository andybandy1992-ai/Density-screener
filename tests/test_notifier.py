from __future__ import annotations

from datetime import datetime, timezone
import unittest

from density_screener.models import DensitySignal
from density_screener.notifiers import TelegramNotifier, format_signal
from density_screener.settings import TelegramConfig


def make_signal() -> DensitySignal:
    return DensitySignal(
        exchange="bybit_spot",
        symbol="BTCUSDT",
        market_type="spot",
        side="bid",
        price=104321.12,
        quantity=1.1,
        notional=114753.232,
        ratio_to_average=6.42,
        resting_seconds=7.0,
        average_candle_notional=17874.33,
        detected_at=datetime(2026, 4, 11, 12, 0, 0, tzinfo=timezone.utc),
        metadata={"mid_price": 105000.0},
    )


class NotifierTests(unittest.TestCase):
    def test_formatter_contains_required_fields(self) -> None:
        text = format_signal(make_signal())

        self.assertIn("BTCUSDT", text)
        self.assertIn("Exchange:", text)
        self.assertIn("Instrument:", text)
        self.assertIn("Price:", text)
        self.assertIn("Limit size:", text)
        self.assertIn("Limit notional:", text)
        self.assertIn("Distance from current:", text)
        self.assertIn("Lifetime:", text)

    def test_build_message_uses_bot_api_shape(self) -> None:
        notifier = TelegramNotifier(
            TelegramConfig(enabled=True, bot_token="token123", chat_id="-100555")
        )

        message = notifier.build_message(make_signal())

        self.assertTrue(message.url.endswith("/bottoken123/sendMessage"))
        self.assertEqual(message.payload["chat_id"], "-100555")
        self.assertIn("BTCUSDT", message.payload["text"])

    def test_build_text_message_uses_same_transport(self) -> None:
        notifier = TelegramNotifier(
            TelegramConfig(enabled=True, bot_token="token123", chat_id="-100555")
        )

        message = notifier.build_text_message("hello")

        self.assertTrue(message.url.endswith("/bottoken123/sendMessage"))
        self.assertEqual(message.payload["text"], "hello")


if __name__ == "__main__":
    unittest.main()
