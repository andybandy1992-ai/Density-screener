from __future__ import annotations

import unittest

from density_screener.cli import _enabled_exchange_names, _parse_exchange_names
from density_screener.settings import ExchangeConfig


class CliHelperTests(unittest.TestCase):
    def test_parse_exchange_names_handles_csv(self) -> None:
        parsed = _parse_exchange_names("bitget_spot, lighter,kucoin_spot")

        self.assertEqual(parsed, {"bitget_spot", "lighter", "kucoin_spot"})

    def test_enabled_exchange_names_filters_disabled_and_unknown(self) -> None:
        exchanges = {
            "bitget_spot": ExchangeConfig(enabled=True, market_type="spot"),
            "lighter": ExchangeConfig(enabled=True, market_type="mixed"),
            "bybit_spot": ExchangeConfig(enabled=False, market_type="spot"),
            "custom": ExchangeConfig(enabled=True, market_type="spot"),
        }

        selected = _enabled_exchange_names(exchanges, {"bitget_spot", "lighter", "custom"})

        self.assertEqual(selected, ["bitget_spot", "lighter"])


if __name__ == "__main__":
    unittest.main()
