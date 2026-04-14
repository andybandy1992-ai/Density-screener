from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(slots=True)
class ExchangeHealth:
    market_type: str = ""
    status: str = "starting"
    snapshots_processed: int = 0
    signals_emitted: int = 0
    last_snapshot_at: datetime | None = None
    last_signal_at: datetime | None = None
    last_error: str = ""


class HealthMonitor:
    def __init__(
        self,
        *,
        telegram_enabled: bool,
        control_bot_enabled: bool,
        control_user_ids: tuple[str, ...],
        control_state_path: Path | None,
    ) -> None:
        self._started_at = datetime.now(timezone.utc)
        self._telegram_enabled = telegram_enabled
        self._control_bot_enabled = control_bot_enabled
        self._control_user_ids = control_user_ids
        self._control_state_path = control_state_path
        self._exchanges: dict[str, ExchangeHealth] = {}

    def register_exchange(self, exchange_name: str, market_type: str = "") -> None:
        exchange = self._exchanges.get(exchange_name)
        if exchange is None:
            self._exchanges[exchange_name] = ExchangeHealth(market_type=market_type)
            return
        if market_type and not exchange.market_type:
            exchange.market_type = market_type

    def mark_starting(self, exchange_name: str, market_type: str = "") -> None:
        self.register_exchange(exchange_name, market_type)
        exchange = self._exchanges[exchange_name]
        exchange.status = "starting"
        exchange.last_error = ""

    def mark_snapshot(
        self,
        exchange_name: str,
        *,
        market_type: str = "",
        snapshot_time: datetime | None = None,
        signals_emitted: int = 0,
    ) -> None:
        self.register_exchange(exchange_name, market_type)
        exchange = self._exchanges[exchange_name]
        exchange.status = "running"
        exchange.snapshots_processed += 1
        exchange.signals_emitted += signals_emitted
        exchange.last_snapshot_at = snapshot_time or datetime.now(timezone.utc)
        if signals_emitted:
            exchange.last_signal_at = exchange.last_snapshot_at
        exchange.last_error = ""

    def mark_failure(self, exchange_name: str, error: Exception | str, market_type: str = "") -> None:
        self.register_exchange(exchange_name, market_type)
        exchange = self._exchanges[exchange_name]
        exchange.status = "failed"
        exchange.last_error = describe_error(error)

    def format_report(self, now: datetime | None = None) -> str:
        current_time = now or datetime.now(timezone.utc)
        lines = [
            "Density Screener Health",
            f"Service uptime: {_format_age(self._started_at, current_time)}",
            f"Telegram alerts: {'enabled' if self._telegram_enabled else 'disabled'}",
            f"Control bot: {'enabled' if self._control_bot_enabled else 'disabled'}",
            (
                "Control users: "
                + (", ".join(self._control_user_ids) if self._control_user_ids else "alert chat only")
            ),
            f"Runtime state: {self._control_state_path or 'disabled'}",
        ]

        if not self._exchanges:
            lines.append("Exchanges: none registered yet")
            return "\n".join(lines)

        lines.append("")
        lines.append("Exchanges:")
        for exchange_name in sorted(self._exchanges):
            exchange = self._exchanges[exchange_name]
            line = (
                f"- {exchange_name}: {exchange.status.upper()} | "
                f"market={exchange.market_type or 'n/a'} | "
                f"snapshots={exchange.snapshots_processed} | "
                f"signals={exchange.signals_emitted} | "
                f"last_snapshot={_format_optional_age(exchange.last_snapshot_at, current_time)}"
            )
            if exchange.last_error:
                line += f" | error={exchange.last_error}"
            lines.append(line)
        return "\n".join(lines)


def _format_optional_age(value: datetime | None, now: datetime) -> str:
    if value is None:
        return "n/a"
    return _format_age(value, now)


def _format_age(started_at: datetime, now: datetime) -> str:
    seconds = max(0, int((now - started_at).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def describe_error(error: Exception | str) -> str:
    if isinstance(error, str):
        return error
    message = str(error).strip()
    if message:
        return f"{error.__class__.__name__}: {message}"
    return error.__class__.__name__
