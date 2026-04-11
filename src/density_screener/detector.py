from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from density_screener.models import BookLevel, CandidateState, DensitySignal, OrderBookSnapshot, Side, VolumeReference
from density_screener.settings import DetectionConfig


CandidateKey = tuple[str, str, Side, float]


@dataclass(slots=True)
class EvaluatedLevel:
    side: Side
    level: BookLevel
    ratio_to_average: float
    threshold: float


class DensityDetector:
    def __init__(self, config: DetectionConfig) -> None:
        self._config = config
        self._candidates: dict[CandidateKey, CandidateState] = {}
        self._alerted: dict[CandidateKey, datetime] = {}

    def process(
        self,
        snapshot: OrderBookSnapshot,
        volume_reference: VolumeReference,
        now: datetime | None = None,
    ) -> list[DensitySignal]:
        current_time = now or snapshot.timestamp
        threshold = max(
            volume_reference.avg_candle_notional * self._config.volume_multiplier,
            self._config.min_notional_for(snapshot.market_type),
        )

        valid_levels = self._collect_levels(snapshot, threshold, volume_reference)
        active_keys: set[CandidateKey] = set()
        signals: list[DensitySignal] = []

        self._prune_alerts(current_time)

        for evaluated in valid_levels:
            key = self._key(snapshot.exchange, snapshot.symbol, evaluated.side, evaluated.level.price)
            active_keys.add(key)

            if key in self._alerted:
                continue

            state = self._candidates.get(key)
            if state is None:
                self._candidates[key] = CandidateState(
                    first_seen_at=current_time,
                    last_seen_at=current_time,
                    max_notional=evaluated.level.notional,
                    ratio_to_average=evaluated.ratio_to_average,
                    quantity=evaluated.level.quantity,
                )
                continue

            state.last_seen_at = current_time
            state.max_notional = max(state.max_notional, evaluated.level.notional)
            state.ratio_to_average = max(state.ratio_to_average, evaluated.ratio_to_average)
            state.quantity = evaluated.level.quantity

            resting_seconds = (current_time - state.first_seen_at).total_seconds()
            if resting_seconds < self._config.min_lifetime_seconds:
                continue

            signals.append(
                DensitySignal(
                    exchange=snapshot.exchange,
                    symbol=snapshot.symbol,
                    market_type=snapshot.market_type,
                    side=evaluated.side,
                    price=evaluated.level.price,
                    quantity=evaluated.level.quantity,
                    notional=evaluated.level.notional,
                    ratio_to_average=evaluated.ratio_to_average,
                    resting_seconds=resting_seconds,
                    average_candle_notional=volume_reference.avg_candle_notional,
                    detected_at=current_time,
                    metadata={
                        "threshold": round(evaluated.threshold, 4),
                        "mid_price": round(snapshot.mid_price, 8),
                    },
                )
            )
            self._alerted[key] = current_time
            self._candidates.pop(key, None)

        stale = [key for key in self._candidates if key not in active_keys]
        for key in stale:
            self._candidates.pop(key, None)

        return signals

    def _collect_levels(
        self,
        snapshot: OrderBookSnapshot,
        threshold: float,
        volume_reference: VolumeReference,
    ) -> list[EvaluatedLevel]:
        valid: list[EvaluatedLevel] = []
        max_distance = snapshot.mid_price * (self._config.price_window_pct / 100)
        min_tick_distance = (snapshot.tick_size or 0.0) * self._config.suppress_top_ticks

        for side, levels in (("bid", snapshot.bids), ("ask", snapshot.asks)):
            for level in levels:
                distance = abs(snapshot.mid_price - level.price)
                if distance > max_distance:
                    continue
                if distance <= min_tick_distance:
                    continue
                if level.notional < threshold:
                    continue
                if self._looks_symmetric(snapshot, side, level, threshold):
                    continue
                ratio = level.notional / max(1.0, volume_reference.avg_candle_notional)
                valid.append(
                    EvaluatedLevel(
                        side=side,
                        level=level,
                        ratio_to_average=ratio,
                        threshold=threshold,
                    )
                )
        return valid

    def _looks_symmetric(
        self,
        snapshot: OrderBookSnapshot,
        side: Side,
        level: BookLevel,
        threshold: float,
    ) -> bool:
        opposite_levels = snapshot.asks if side == "bid" else snapshot.bids
        this_distance = abs(snapshot.mid_price - level.price)
        if this_distance == 0:
            return True

        for opposite in opposite_levels:
            if opposite.notional < threshold * 0.5:
                continue
            opposite_distance = abs(snapshot.mid_price - opposite.price)
            distance_delta = abs(opposite_distance - this_distance) / this_distance
            if distance_delta > self._config.symmetry_distance_tolerance_pct / 100:
                continue
            notional_delta = abs(opposite.notional - level.notional) / max(level.notional, 1.0)
            if notional_delta <= self._config.symmetry_notional_tolerance_pct / 100:
                return True
        return False

    def _prune_alerts(self, current_time: datetime) -> None:
        cooldown = timedelta(seconds=self._config.same_price_cooldown_seconds)
        stale = [key for key, at in self._alerted.items() if current_time - at >= cooldown]
        for key in stale:
            self._alerted.pop(key, None)

    @staticmethod
    def _key(exchange: str, symbol: str, side: Side, price: float) -> CandidateKey:
        return (exchange, symbol, side, round(price, 8))
