from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from density_screener.detector import DensityDetector
from density_screener.health import HealthMonitor
from density_screener.models import DensitySignal, OrderBookSnapshot, VolumeReference
from density_screener.telegram_notifier import TelegramNotifier, format_signal
from density_screener.runtime_controls import RuntimeControlStore


@dataclass(slots=True)
class RuntimeStats:
    snapshots_processed: int = 0
    signals_emitted: int = 0


class ScreenerRuntime:
    def __init__(
        self,
        detector: DensityDetector,
        notifier: TelegramNotifier | None = None,
        controls: RuntimeControlStore | None = None,
        health: HealthMonitor | None = None,
        exchange_name: str = "",
        snapshot_process_interval_seconds: float = 0.0,
    ) -> None:
        self._detector = detector
        self._notifier = notifier
        self._controls = controls
        self._health = health
        self._exchange_name = exchange_name
        self._snapshot_process_interval_seconds = max(0.0, snapshot_process_interval_seconds)
        self._last_processed_at: dict[tuple[str, str], datetime] = {}
        self.stats = RuntimeStats()

    async def handle_snapshot(
        self,
        snapshot: OrderBookSnapshot,
        volume_reference: VolumeReference,
    ) -> list[DensitySignal]:
        if self._controls is not None and self._controls.matches_blacklist(snapshot.symbol):
            return []
        if self._should_skip_snapshot(snapshot):
            return []
        self.stats.snapshots_processed += 1
        signals = self._detector.process(snapshot, volume_reference)
        self.stats.signals_emitted += len(signals)
        if self._health is not None:
            self._health.mark_snapshot(
                self._exchange_name or snapshot.exchange,
                market_type=snapshot.market_type,
                snapshot_time=snapshot.timestamp,
                signals_emitted=len(signals),
            )
        if self._notifier is not None:
            for signal in signals:
                try:
                    await self._notifier.send(signal)
                except Exception as error:
                    print(
                        f"[notifier] send_failed exchange={signal.exchange} symbol={signal.symbol} error={error}",
                        flush=True,
                    )
        return signals

    def should_process_snapshot(self, exchange: str, symbol: str, timestamp: datetime) -> bool:
        """Reserve a detector slot before an adapter builds an expensive snapshot."""
        return self._reserve_snapshot_slot(exchange, symbol, timestamp)

    @staticmethod
    def render_signal(signal: DensitySignal) -> str:
        return format_signal(signal)

    def _should_skip_snapshot(self, snapshot: OrderBookSnapshot) -> bool:
        key = (snapshot.exchange, snapshot.symbol)
        if self._last_processed_at.get(key) == snapshot.timestamp:
            return False
        return not self._reserve_snapshot_slot(snapshot.exchange, snapshot.symbol, snapshot.timestamp)

    def _reserve_snapshot_slot(self, exchange: str, symbol: str, timestamp: datetime) -> bool:
        if self._snapshot_process_interval_seconds <= 0:
            return True
        key = (exchange, symbol)
        last_processed_at = self._last_processed_at.get(key)
        if last_processed_at is not None:
            elapsed = (timestamp - last_processed_at).total_seconds()
            if elapsed < self._snapshot_process_interval_seconds:
                return False
        self._last_processed_at[key] = timestamp
        return True
