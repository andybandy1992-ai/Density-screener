from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from density_screener.blacklist import BlacklistMatcher
from density_screener.models import BookLevel, MarketType, OrderBookSnapshot, VolumeReference


@dataclass(slots=True, frozen=True)
class ExchangeInstrument:
    exchange: str
    symbol: str
    market_type: MarketType
    tick_size: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class OrderBookState:
    def __init__(self, *, exchange: str, symbol: str, market_type: MarketType, tick_size: float | None) -> None:
        self.exchange = exchange
        self.symbol = symbol
        self.market_type = market_type
        self.tick_size = tick_size
        self._bids: dict[float, float] = {}
        self._asks: dict[float, float] = {}

    def replace(self, bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> None:
        self._bids = {price: size for price, size in bids if size > 0}
        self._asks = {price: size for price, size in asks if size > 0}

    def apply_delta(self, bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> None:
        self._apply_side(self._bids, bids)
        self._apply_side(self._asks, asks)

    def to_snapshot(self, timestamp, depth: int = 50) -> OrderBookSnapshot | None:
        if not self._bids or not self._asks:
            return None
        bid_levels = tuple(
            BookLevel(price=price, quantity=size, notional=price * size)
            for price, size in sorted(self._bids.items(), reverse=True)[:depth]
        )
        ask_levels = tuple(
            BookLevel(price=price, quantity=size, notional=price * size)
            for price, size in sorted(self._asks.items())[:depth]
        )
        return OrderBookSnapshot(
            exchange=self.exchange,
            symbol=self.symbol,
            market_type=self.market_type,
            best_bid=bid_levels[0].price,
            best_ask=ask_levels[0].price,
            bids=bid_levels,
            asks=ask_levels,
            timestamp=timestamp,
            tick_size=self.tick_size,
        )

    @staticmethod
    def _apply_side(book: dict[float, float], updates: list[tuple[float, float]]) -> None:
        for price, size in updates:
            if size <= 0:
                book.pop(price, None)
            else:
                book[price] = size


class ExchangeAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def discover_instruments(self, blacklist: BlacklistMatcher) -> list[ExchangeInstrument]:
        raise NotImplementedError

    @abstractmethod
    async def bootstrap_volume_reference(self, instrument: ExchangeInstrument) -> VolumeReference:
        raise NotImplementedError
