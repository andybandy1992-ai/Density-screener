from __future__ import annotations

import unittest

from density_screener.exchanges.spot_filters import should_skip_spot_base


class SpotFilterTests(unittest.TestCase):
    def test_stable_base_assets_are_skipped(self) -> None:
        self.assertTrue(should_skip_spot_base("USDC"))
        self.assertTrue(should_skip_spot_base("pyusd"))
        self.assertTrue(should_skip_spot_base("DAI"))
        self.assertTrue(should_skip_spot_base("USDY"))
        self.assertTrue(should_skip_spot_base("RLUSD"))

    def test_regular_assets_are_not_skipped(self) -> None:
        self.assertFalse(should_skip_spot_base("BTC"))
        self.assertFalse(should_skip_spot_base("ICP"))
        self.assertFalse(should_skip_spot_base(""))


if __name__ == "__main__":
    unittest.main()
