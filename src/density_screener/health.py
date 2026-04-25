from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil


@dataclass(slots=True)
class ExchangeHealth:
    market_type: str = ""
    status: str = "starting"
    snapshots_processed: int = 0
    signals_emitted: int = 0
    last_snapshot_at: datetime | None = None
    last_signal_at: datetime | None = None
    last_error: str = ""


@dataclass(slots=True, frozen=True)
class SystemMetrics:
    load_average: tuple[float, float, float] | None = None
    memory_total_bytes: int | None = None
    memory_available_bytes: int | None = None
    disk_total_bytes: int | None = None
    disk_free_bytes: int | None = None
    network_rx_bytes: int | None = None
    network_tx_bytes: int | None = None


class HealthMonitor:
    def __init__(
        self,
        *,
        telegram_enabled: bool,
        control_bot_enabled: bool,
        control_user_ids: tuple[str, ...],
        control_state_path: Path | None,
        system_metrics_provider: Callable[[], SystemMetrics | None] | None = None,
    ) -> None:
        self._started_at = datetime.now(timezone.utc)
        self._telegram_enabled = telegram_enabled
        self._control_bot_enabled = control_bot_enabled
        self._control_user_ids = control_user_ids
        self._control_state_path = control_state_path
        self._system_metrics_provider = system_metrics_provider or collect_system_metrics
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
        lines.extend(self._format_system_metrics())

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

    def _format_system_metrics(self) -> list[str]:
        metrics = self._system_metrics_provider()
        if metrics is None:
            return []

        lines = ["", "System:"]
        if metrics.load_average is not None:
            one, five, fifteen = metrics.load_average
            lines.append(f"Load avg: {one:.2f} / {five:.2f} / {fifteen:.2f}")
        if metrics.memory_total_bytes and metrics.memory_available_bytes is not None:
            used = max(0, metrics.memory_total_bytes - metrics.memory_available_bytes)
            used_pct = used / metrics.memory_total_bytes * 100
            lines.append(
                f"Memory: {_format_bytes(used)} / {_format_bytes(metrics.memory_total_bytes)} ({used_pct:.0f}%)"
            )
        if metrics.disk_total_bytes and metrics.disk_free_bytes is not None:
            used = max(0, metrics.disk_total_bytes - metrics.disk_free_bytes)
            used_pct = used / metrics.disk_total_bytes * 100
            lines.append(
                f"Disk /: {_format_bytes(used)} / {_format_bytes(metrics.disk_total_bytes)} ({used_pct:.0f}%)"
            )
        if metrics.network_rx_bytes is not None and metrics.network_tx_bytes is not None:
            lines.append(
                "Network since boot: "
                f"rx={_format_bytes(metrics.network_rx_bytes)} "
                f"tx={_format_bytes(metrics.network_tx_bytes)}"
            )
        return lines


def collect_system_metrics() -> SystemMetrics | None:
    network_rx_bytes, network_tx_bytes = _read_network_bytes()
    return SystemMetrics(
        load_average=_read_load_average(),
        memory_total_bytes=_read_memory_total_bytes(),
        memory_available_bytes=_read_memory_available_bytes(),
        disk_total_bytes=_read_disk_total_bytes(),
        disk_free_bytes=_read_disk_free_bytes(),
        network_rx_bytes=network_rx_bytes,
        network_tx_bytes=network_tx_bytes,
    )


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


def _read_load_average() -> tuple[float, float, float] | None:
    if not hasattr(os, "getloadavg"):
        return None
    try:
        return os.getloadavg()
    except OSError:
        return None


def _read_memory_total_bytes() -> int | None:
    return _read_meminfo_value("MemTotal")


def _read_memory_available_bytes() -> int | None:
    return _read_meminfo_value("MemAvailable")


def _read_meminfo_value(key: str) -> int | None:
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return None
    try:
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            if not line.startswith(f"{key}:"):
                continue
            parts = line.split()
            if len(parts) < 2:
                return None
            return int(parts[1]) * 1024
    except (OSError, ValueError):
        return None
    return None


def _read_disk_total_bytes() -> int | None:
    try:
        return shutil.disk_usage("/").total
    except OSError:
        return None


def _read_disk_free_bytes() -> int | None:
    try:
        return shutil.disk_usage("/").free
    except OSError:
        return None


def _read_network_bytes() -> tuple[int | None, int | None]:
    net_dev = Path("/proc/net/dev")
    if not net_dev.exists():
        return None, None
    rx_total = 0
    tx_total = 0
    try:
        for line in net_dev.read_text(encoding="utf-8").splitlines()[2:]:
            if ":" not in line:
                continue
            interface, raw_values = line.split(":", 1)
            if interface.strip() == "lo":
                continue
            values = raw_values.split()
            if len(values) < 16:
                continue
            rx_total += int(values[0])
            tx_total += int(values[8])
    except (OSError, ValueError):
        return None, None
    return rx_total, tx_total


def _format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
