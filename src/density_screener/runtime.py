from __future__ import annotations

from dataclasses import dataclass

from density_screener.detector import DensityDetector
from density_screener.models import DensitySignal, OrderBookSnapshot, VolumeReference
from density_screener.notifiers import TelegramNotifier, format_signal


@dataclass(slots=True)
class RuntimeStats:
    snapshots_processed: int = 0
    signals_emitted: int = 0


class ScreenerRuntime:
    def __init__(self, detector: DensityDetector, notifier: TelegramNotifier | None = None) -> None:
        self._detector = detector
        self._notifier = notifier
        self.stats = RuntimeStats()

    async def handle_snapshot(
        self,
        snapshot: OrderBookSnapshot,
        volume_reference: VolumeReference,
    ) -> list[DensitySignal]:
        self.stats.snapshots_processed += 1
        signals = self._detector.process(snapshot, volume_reference)
        self.stats.signals_emitted += len(signals)
        if self._notifier is not None:
            for signal in signals:
                await self._notifier.send(signal)
        return signals

    @staticmethod
    def render_signal(signal: DensitySignal) -> str:
        return format_signal(signal)
