from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Iterable


BASE_ASSET_KEYS = ("baseAsset", "baseCurrency", "baseCoin")
QUOTE_SUFFIXES = tuple(
    sorted(
        {
            "USDTM",
            "USDCM",
            "USDTM",
            "PERP",
            "USDT",
            "USDC",
            "FDUSD",
            "BUSD",
            "USD",
            "BTC",
            "ETH",
            "EUR",
            "TRY",
            "BRL",
            "JPY",
            "GBP",
            "CHF",
        },
        key=len,
        reverse=True,
    )
)


@dataclass(slots=True, frozen=True)
class BlacklistMatcher:
    exact_symbols: frozenset[str]
    base_assets: frozenset[str]
    patterns: tuple[str, ...]
    entries_count: int = 0
    source_path: str = ""

    @classmethod
    def load(
        cls,
        *,
        inline_terms: Iterable[str] = (),
        file_path: Path | None = None,
    ) -> BlacklistMatcher:
        exact_symbols: set[str] = set()
        base_assets: set[str] = set()
        patterns: list[str] = []
        entries_count = 0

        for term in inline_terms:
            entries_count += cls._consume_term(term, exact_symbols, base_assets, patterns)

        resolved_source = ""
        if file_path is not None and file_path.exists():
            resolved_source = str(file_path)
            for line in file_path.read_text(encoding="utf-8").splitlines():
                entries_count += cls._consume_term(line, exact_symbols, base_assets, patterns)

        return cls(
            exact_symbols=frozenset(exact_symbols),
            base_assets=frozenset(base_assets),
            patterns=tuple(patterns),
            entries_count=entries_count,
            source_path=resolved_source,
        )

    def matches(self, symbol: str, metadata: dict[str, Any] | None = None) -> bool:
        normalized_symbol = _normalize_value(symbol)
        if not normalized_symbol:
            return False
        if normalized_symbol in self.exact_symbols:
            return True

        base_asset = _extract_base_asset(symbol, metadata)
        if base_asset and base_asset in self.base_assets:
            return True

        return any(fnmatch(normalized_symbol, pattern) for pattern in self.patterns)

    @staticmethod
    def _consume_term(
        raw_term: str,
        exact_symbols: set[str],
        base_assets: set[str],
        patterns: list[str],
    ) -> int:
        stripped = raw_term.strip()
        if not stripped or stripped.startswith("#"):
            return 0

        if ":" in stripped:
            prefix, value = stripped.split(":", 1)
            normalized_value = _normalize_value(value)
            if not normalized_value:
                return 0
            prefix = prefix.strip().lower()
            if prefix in {"coin", "base"}:
                base_assets.add(normalized_value)
                return 1
            if prefix == "symbol":
                exact_symbols.add(normalized_value)
                return 1
            if prefix == "pattern":
                patterns.append(normalized_value)
                return 1

        normalized = _normalize_value(stripped)
        if not normalized:
            return 0
        if "*" in normalized or "?" in normalized:
            patterns.append(normalized)
            return 1

        # Bare entries are treated as both an exact symbol and a base asset.
        # This lets "BTC" block all BTC markets, while "BTCUSDT" still works as an exact market rule.
        exact_symbols.add(normalized)
        base_assets.add(normalized)
        return 1


def ensure_blacklist_matcher(value: BlacklistMatcher | Iterable[str]) -> BlacklistMatcher:
    if isinstance(value, BlacklistMatcher):
        return value
    return BlacklistMatcher.load(inline_terms=value)


def merge_matchers(*matchers: BlacklistMatcher) -> BlacklistMatcher:
    exact_symbols: set[str] = set()
    base_assets: set[str] = set()
    patterns: list[str] = []
    entries_count = 0
    source_paths: list[str] = []

    for matcher in matchers:
        exact_symbols.update(matcher.exact_symbols)
        base_assets.update(matcher.base_assets)
        patterns.extend(matcher.patterns)
        entries_count += matcher.entries_count
        if matcher.source_path:
            source_paths.append(matcher.source_path)

    return BlacklistMatcher(
        exact_symbols=frozenset(exact_symbols),
        base_assets=frozenset(base_assets),
        patterns=tuple(patterns),
        entries_count=entries_count,
        source_path=",".join(source_paths),
    )


def normalize_blacklist_term(raw_term: str) -> str | None:
    stripped = raw_term.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if ":" in stripped:
        prefix, value = stripped.split(":", 1)
        normalized_value = _normalize_value(value)
        if not normalized_value:
            return None
        normalized_prefix = prefix.strip().lower()
        if normalized_prefix not in {"coin", "base", "symbol", "pattern"}:
            return None
        return f"{normalized_prefix}:{normalized_value}"
    normalized = _normalize_value(stripped)
    if not normalized:
        return None
    return normalized


def _normalize_value(value: str) -> str:
    return value.strip().upper()


def _extract_base_asset(symbol: str, metadata: dict[str, Any] | None) -> str:
    if metadata:
        for key in BASE_ASSET_KEYS:
            raw_value = metadata.get(key)
            if raw_value:
                return _normalize_value(str(raw_value))

    normalized_symbol = _normalize_value(symbol)
    if "/" in normalized_symbol:
        return normalized_symbol.split("/", 1)[0]
    if "-" in normalized_symbol:
        return normalized_symbol.split("-", 1)[0]
    for suffix in QUOTE_SUFFIXES:
        if normalized_symbol.endswith(suffix) and len(normalized_symbol) > len(suffix):
            return normalized_symbol[: -len(suffix)]
    return normalized_symbol
