from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from density_screener.blacklist import (
    BlacklistMatcher,
    merge_matchers,
    normalize_blacklist_term,
)
from density_screener.models import MarketType
from density_screener.settings import DetectionConfig


@dataclass(slots=True, frozen=True)
class RuntimeControlSnapshot:
    spot_min_notional_usd: float
    futures_min_notional_usd: float
    spot_volume_multiplier: float
    futures_volume_multiplier: float
    exchange_min_notional_usd: dict[str, float]
    blacklist_terms: tuple[str, ...]
    dynamic_blacklist: BlacklistMatcher
    combined_blacklist: BlacklistMatcher


class RuntimeControlStore:
    def __init__(
        self,
        path: str | Path,
        defaults: DetectionConfig,
        base_blacklist: BlacklistMatcher,
    ) -> None:
        self._path = Path(path)
        self._defaults = defaults
        self._base_blacklist = base_blacklist
        self._snapshot = self._load()

    @property
    def path(self) -> Path:
        return self._path

    def snapshot(self) -> RuntimeControlSnapshot:
        return self._snapshot

    def min_notional_for(self, market_type: MarketType) -> float:
        if market_type == "spot":
            return self._snapshot.spot_min_notional_usd
        return self._snapshot.futures_min_notional_usd

    def min_notional_for_exchange(self, exchange: str, market_type: MarketType) -> float:
        normalized_exchange = self._normalize_exchange(exchange)
        if normalized_exchange in self._snapshot.exchange_min_notional_usd:
            return self._snapshot.exchange_min_notional_usd[normalized_exchange]
        return self.min_notional_for(market_type)

    def volume_multiplier_for(self, market_type: MarketType) -> float:
        if market_type == "spot":
            return self._snapshot.spot_volume_multiplier
        return self._snapshot.futures_volume_multiplier

    def exchange_min_notional(self, exchange: str) -> float | None:
        return self._snapshot.exchange_min_notional_usd.get(self._normalize_exchange(exchange))

    def matches_blacklist(self, symbol: str) -> bool:
        return self._snapshot.combined_blacklist.matches(symbol)

    def combined_blacklist(self) -> BlacklistMatcher:
        return self._snapshot.combined_blacklist

    def set_min_notional(self, market_type: MarketType, value: float) -> RuntimeControlSnapshot:
        payload = self._to_payload()
        normalized_value = max(0.0, float(value))
        if market_type == "spot":
            payload["spot_min_notional_usd"] = normalized_value
        else:
            payload["futures_min_notional_usd"] = normalized_value
        return self._replace(payload)

    def adjust_min_notional(self, market_type: MarketType, delta: float) -> RuntimeControlSnapshot:
        return self.set_min_notional(market_type, self.min_notional_for(market_type) + delta)

    def set_exchange_min_notional(self, exchange: str, value: float) -> RuntimeControlSnapshot:
        payload = self._to_payload()
        payload["exchange_min_notional_usd"][self._normalize_exchange(exchange)] = max(0.0, float(value))
        return self._replace(payload)

    def adjust_exchange_min_notional(self, exchange: str, delta: float) -> RuntimeControlSnapshot:
        current = self.exchange_min_notional(exchange) or 0.0
        return self.set_exchange_min_notional(exchange, current + delta)

    def clear_exchange_min_notional(self, exchange: str) -> RuntimeControlSnapshot:
        payload = self._to_payload()
        removed = payload["exchange_min_notional_usd"].pop(self._normalize_exchange(exchange), None)
        if removed is None:
            raise ValueError("Exchange override is not set.")
        return self._replace(payload)

    def set_volume_multiplier(self, market_type: MarketType, value: float) -> RuntimeControlSnapshot:
        payload = self._to_payload()
        normalized_value = max(0.0, float(value))
        if market_type == "spot":
            payload["spot_volume_multiplier"] = normalized_value
        else:
            payload["futures_volume_multiplier"] = normalized_value
        return self._replace(payload)

    def adjust_volume_multiplier(self, market_type: MarketType, delta: float) -> RuntimeControlSnapshot:
        return self.set_volume_multiplier(market_type, self.volume_multiplier_for(market_type) + delta)

    def add_blacklist_term(self, raw_term: str) -> RuntimeControlSnapshot:
        normalized_term = normalize_blacklist_term(raw_term)
        if normalized_term is None:
            raise ValueError("Unsupported blacklist rule.")
        payload = self._to_payload()
        current_terms = {term.upper(): term for term in payload["blacklist_terms"]}
        if normalized_term.upper() in current_terms:
            raise ValueError("Rule already exists in the bot-managed blacklist.")
        payload["blacklist_terms"].append(normalized_term)
        payload["blacklist_terms"].sort()
        return self._replace(payload)

    def remove_blacklist_term(self, raw_term: str) -> RuntimeControlSnapshot:
        normalized_term = normalize_blacklist_term(raw_term)
        if normalized_term is None:
            raise ValueError("Unsupported blacklist rule.")
        payload = self._to_payload()
        updated_terms = [term for term in payload["blacklist_terms"] if term.upper() != normalized_term.upper()]
        if len(updated_terms) == len(payload["blacklist_terms"]):
            raise ValueError("Rule was not found in the bot-managed blacklist.")
        payload["blacklist_terms"] = updated_terms
        return self._replace(payload)

    def _load(self) -> RuntimeControlSnapshot:
        payload = {
            "spot_min_notional_usd": float(self._defaults.spot_min_notional_usd),
            "futures_min_notional_usd": float(self._defaults.futures_min_notional_usd),
            "spot_volume_multiplier": float(self._defaults.volume_multiplier),
            "futures_volume_multiplier": float(self._defaults.volume_multiplier),
            "exchange_min_notional_usd": {},
            "blacklist_terms": [],
        }
        if self._path.exists():
            try:
                loaded = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                loaded = {}
            payload["spot_min_notional_usd"] = float(
                loaded.get("spot_min_notional_usd", payload["spot_min_notional_usd"])
            )
            payload["futures_min_notional_usd"] = float(
                loaded.get("futures_min_notional_usd", payload["futures_min_notional_usd"])
            )
            payload["spot_volume_multiplier"] = float(
                loaded.get("spot_volume_multiplier", payload["spot_volume_multiplier"])
            )
            payload["futures_volume_multiplier"] = float(
                loaded.get("futures_volume_multiplier", payload["futures_volume_multiplier"])
            )
            raw_exchange_overrides = loaded.get("exchange_min_notional_usd", {})
            if isinstance(raw_exchange_overrides, dict):
                payload["exchange_min_notional_usd"] = {
                    self._normalize_exchange(exchange): max(0.0, float(value))
                    for exchange, value in raw_exchange_overrides.items()
                    if str(exchange).strip()
                }
            payload["blacklist_terms"] = [
                normalized
                for item in self._split_raw_blacklist_terms(loaded.get("blacklist_terms", []))
                if (normalized := normalize_blacklist_term(item)) is not None
            ]
        return self._build_snapshot(payload)

    def _replace(self, payload: dict[str, float | list[str] | dict[str, float]]) -> RuntimeControlSnapshot:
        snapshot = self._build_snapshot(payload)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(
                {
                    "spot_min_notional_usd": snapshot.spot_min_notional_usd,
                    "futures_min_notional_usd": snapshot.futures_min_notional_usd,
                    "spot_volume_multiplier": snapshot.spot_volume_multiplier,
                    "futures_volume_multiplier": snapshot.futures_volume_multiplier,
                    "exchange_min_notional_usd": snapshot.exchange_min_notional_usd,
                    "blacklist_terms": list(snapshot.blacklist_terms),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        self._snapshot = snapshot
        return snapshot

    def _build_snapshot(self, payload: dict[str, float | list[str] | dict[str, float]]) -> RuntimeControlSnapshot:
        blacklist_terms = tuple(str(term) for term in payload["blacklist_terms"])
        dynamic_blacklist = BlacklistMatcher.load(inline_terms=blacklist_terms)
        exchange_min_notional_usd = {
            self._normalize_exchange(exchange): float(value)
            for exchange, value in dict(payload["exchange_min_notional_usd"]).items()
        }
        return RuntimeControlSnapshot(
            spot_min_notional_usd=float(payload["spot_min_notional_usd"]),
            futures_min_notional_usd=float(payload["futures_min_notional_usd"]),
            spot_volume_multiplier=float(payload["spot_volume_multiplier"]),
            futures_volume_multiplier=float(payload["futures_volume_multiplier"]),
            exchange_min_notional_usd=dict(sorted(exchange_min_notional_usd.items())),
            blacklist_terms=blacklist_terms,
            dynamic_blacklist=dynamic_blacklist,
            combined_blacklist=merge_matchers(self._base_blacklist, dynamic_blacklist),
        )

    def _to_payload(self) -> dict[str, float | list[str] | dict[str, float]]:
        snapshot = self._snapshot
        return {
            "spot_min_notional_usd": float(snapshot.spot_min_notional_usd),
            "futures_min_notional_usd": float(snapshot.futures_min_notional_usd),
            "spot_volume_multiplier": float(snapshot.spot_volume_multiplier),
            "futures_volume_multiplier": float(snapshot.futures_volume_multiplier),
            "exchange_min_notional_usd": dict(snapshot.exchange_min_notional_usd),
            "blacklist_terms": list(snapshot.blacklist_terms),
        }

    @staticmethod
    def _split_raw_blacklist_terms(raw_terms: object) -> list[str]:
        if not isinstance(raw_terms, list):
            return []
        terms: list[str] = []
        for item in raw_terms:
            for line in str(item).replace("\r", "\n").splitlines():
                terms.extend(part.strip() for part in line.split(",") if part.strip())
        return terms

    @staticmethod
    def _normalize_exchange(exchange: str) -> str:
        return exchange.strip().lower()
