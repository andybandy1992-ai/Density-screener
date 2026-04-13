from __future__ import annotations


EXCLUDED_SPOT_BASES = {
    "BUSD",
    "DAI",
    "FDUSD",
    "GHO",
    "PYUSD",
    "TUSD",
    "USD0",
    "USD1",
    "USDB",
    "USDC",
    "USDE",
    "USDP",
    "USDS",
    "USDT",
}


def should_skip_spot_base(base_asset: str | None) -> bool:
    if not base_asset:
        return False
    normalized = base_asset.strip().upper()
    if normalized in EXCLUDED_SPOT_BASES:
        return True
    return normalized.startswith("USD") or normalized.endswith("USD")
