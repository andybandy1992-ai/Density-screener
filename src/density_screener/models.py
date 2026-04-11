from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Side = Literal["bid", "ask"]
MarketType = Literal["spot", "futures"]


@dataclass(slots=True, frozen=True)
class BookLevel:
    price: float
    quantity: float
    notional: float


@dataclass(slots=True, frozen=True)
class OrderBookSnapshot:
    exchange: str
    symbol: str
    market_type: MarketType
    best_bid: float
    best_ask: float
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    timestamp: datetime
    tick_size: float | None = None

    @property
    def mid_price(self) -> float:
        return (self.best_bid + self.best_ask) / 2


@dataclass(slots=True, frozen=True)
class VolumeReference:
    avg_candle_notional: float
    candle_count: int
    interval: str


@dataclass(slots=True, frozen=True)
class DensitySignal:
    exchange: str
    symbol: str
    market_type: MarketType
    side: Side
    price: float
    quantity: float
    notional: float
    ratio_to_average: float
    resting_seconds: float
    average_candle_notional: float
    detected_at: datetime
    reason: str = "density_detected"
    metadata: dict[str, float | str] = field(default_factory=dict)


@dataclass(slots=True)
class CandidateState:
    first_seen_at: datetime
    last_seen_at: datetime
    max_notional: float
    ratio_to_average: float
    quantity: float
