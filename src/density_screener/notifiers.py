from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any

import aiohttp

from density_screener.models import DensitySignal
from density_screener.settings import TelegramConfig


@dataclass(slots=True, frozen=True)
class TelegramMessage:
    url: str
    payload: dict[str, Any]


def format_signal(signal: DensitySignal) -> str:
    summary = _build_signal_summary(signal)
    return (
        "Density signal\n"
        f"{summary['exchange']} | {summary['market']} | {summary['side']}\n\n"
        f"Instrument: {summary['symbol']}\n"
        f"Price: {summary['price']}\n"
        f"Order value: {summary['order_value']}\n"
        f"Distance: {summary['distance']}\n"
        f"Lifetime: {summary['lifetime']}\n"
        f"14x5m avg: {summary['average']}\n"
        f"Above avg: {summary['ratio']}"
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
        summary = _build_signal_summary(signal)
        text = (
            "<b>Density Signal</b>\n"
            f"<code>{escape(summary['exchange'])} | {escape(summary['market'])} | {escape(summary['side'])}</code>\n\n"
            f"<b>Instrument</b>: <code>{escape(summary['symbol'])}</code>\n"
            f"<b>Price</b>: <code>{escape(summary['price'])}</code>\n"
            f"<b>Order value</b>: <code>{escape(summary['order_value'])}</code>\n"
            f"<b>Distance</b>: <code>{escape(summary['distance'])}</code>\n"
            f"<b>Lifetime</b>: <code>{escape(summary['lifetime'])}</code>\n\n"
            f"<b>14x5m avg</b>: <code>{escape(summary['average'])}</code>\n"
            f"<b>Above avg</b>: <code>{escape(summary['ratio'])}</code>"
        )
        return self.build_text_message(text, parse_mode="HTML")

    def build_text_message(
        self,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = None,
    ) -> TelegramMessage:
        payload: dict[str, Any] = {
            "chat_id": self._config.chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if parse_mode is not None:
            payload["parse_mode"] = parse_mode
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


def _build_signal_summary(signal: DensitySignal) -> dict[str, str]:
    side = "BID" if signal.side == "bid" else "ASK"
    mid_price = _coerce_float(signal.metadata.get("mid_price"))
    distance_line = "n/a"
    if mid_price and mid_price > 0:
        distance_pct = (abs(signal.price - mid_price) / mid_price) * 100
        relation = "below market" if signal.price < mid_price else "above market" if signal.price > mid_price else "at market"
        distance_line = f"{distance_pct:.2f}% {relation}"
    return {
        "exchange": signal.exchange,
        "market": signal.market_type,
        "side": side,
        "symbol": signal.symbol,
        "price": f"{signal.price:.8f}",
        "order_value": f"${signal.notional:,.2f}",
        "distance": distance_line,
        "lifetime": f"{signal.resting_seconds:.1f}s",
        "average": f"${signal.average_candle_notional:,.2f}",
        "ratio": f"{signal.ratio_to_average:.2f}x",
    }
