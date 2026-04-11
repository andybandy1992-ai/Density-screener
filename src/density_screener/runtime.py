from __future__ import annotations

from dataclasses import dataclass

from density_screener.detector import DensityDetector
from density_screener.health import HealthMonitor
from density_screener.models import DensitySignal, OrderBookSnapshot, VolumeReference
from density_screener.notifiers import TelegramNotifier, format_signal
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
    ) -> None:
        self._detector = detector
        self._notifier = notifier
        self._controls = controls
        self._health = health
        self._exchange_name = exchange_name
        self.stats = RuntimeStats()

    async def handle_snapshot(
        self,
        snapshot: OrderBookSnapshot,
        volume_reference: VolumeReference,
    ) -> list[DensitySignal]:
        if self._controls is not None and self._controls.matches_blacklist(snapshot.symbol):
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
                await self._notifier.send(signal)
        return signals

    @staticmethod
    def render_signal(signal: DensitySignal) -> str:
        return format_signal(signal)
