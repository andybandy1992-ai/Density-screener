from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiohttp

from density_screener.models import DensitySignal
from density_screener.settings import TelegramConfig


@dataclass(slots=True, frozen=True)
class TelegramMessage:
    url: str
    payload: dict[str, Any]


def format_signal(signal: DensitySignal) -> str:
    side = "BID" if signal.side == "bid" else "ASK"
    mid_price = _coerce_float(signal.metadata.get("mid_price"))
    distance_line = "Distance from current: n/a"
    if mid_price and mid_price > 0:
        distance_abs = abs(signal.price - mid_price)
        distance_pct = (distance_abs / mid_price) * 100
        relation = "below" if signal.price < mid_price else "above" if signal.price > mid_price else "at market"
        distance_line = (
            f"Distance from current: {distance_pct:.2f}% "
            f"({distance_abs:,.8f}) {relation}"
        )
    return (
        f"Exchange: {signal.exchange}\n"
        f"Instrument: {signal.symbol}\n"
        f"Market: {signal.market_type}\n"
        f"Side: {side}\n"
        f"Price: {signal.price:.8f}\n"
        f"{distance_line}\n"
        f"Lifetime: {signal.resting_seconds:.1f}s"
    )


class TelegramNotifier:
    def __init__(self, config: TelegramConfig) -> None:
        self._config = config

    @property
    def enabled(self) -> bool:
        return self._config.enabled and bool(self._config.bot_token and self._config.chat_id)

    def api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self._config.bot_token}/{method}"

    def build_message(self, signal: DensitySignal) -> TelegramMessage:
        return self.build_text_message(format_signal(signal))

    def build_text_message(
        self,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> TelegramMessage:
        payload: dict[str, Any] = {
            "chat_id": self._config.chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return TelegramMessage(
            url=self.api_url("sendMessage"),
            payload=payload,
        )

    async def send(self, signal: DensitySignal) -> bool:
        if not self.enabled:
            return False
        message = self.build_message(signal)
        return await self._send_message(message)

    async def send_text(self, text: str) -> bool:
        if not self.enabled:
            return False
        message = self.build_text_message(text)
        return await self._send_message(message)

    async def _send_message(self, message: TelegramMessage) -> bool:
        async with aiohttp.ClientSession() as session:
            async with session.post(message.url, json=message.payload, timeout=10) as response:
                response.raise_for_status()
                return response.status == 200


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
