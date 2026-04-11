from __future__ import annotations

from pathlib import Path
import unittest

from density_screener.blacklist import BlacklistMatcher


class BlacklistMatcherTests(unittest.TestCase):
    def test_bare_entry_matches_exact_symbol_and_base_coin(self) -> None:
        matcher = BlacklistMatcher.load(inline_terms=["BTC"])

        self.assertTrue(matcher.matches("BTC"))
        self.assertTrue(matcher.matches("BTCUSDT", {"baseCoin": "BTC"}))
        self.assertTrue(matcher.matches("btcusdt", {"baseCurrency": "btc"}))

    def test_symbol_prefix_is_exact_only(self) -> None:
        matcher = BlacklistMatcher.load(inline_terms=["symbol:BTCUSDT"])

        self.assertTrue(matcher.matches("BTCUSDT"))
        self.assertFalse(matcher.matches("BTCUSDC", {"baseCoin": "BTC"}))

    def test_pattern_rule_matches_symbol_wildcards(self) -> None:
        matcher = BlacklistMatcher.load(inline_terms=["pattern:*1000*"])

        self.assertTrue(matcher.matches("1000PEPEUSDT"))
        self.assertFalse(matcher.matches("PEPEUSDT"))

    def test_file_rules_are_loaded(self) -> None:
        path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "blacklist.txt"
        )
        matcher = BlacklistMatcher.load(file_path=path)

        self.assertTrue(matcher.matches("BTCUSDT", {"baseCoin": "BTC"}))
        self.assertTrue(matcher.matches("MYTESTPAIR"))
        self.assertEqual(matcher.entries_count, 2)


if __name__ == "__main__":
    unittest.main()
