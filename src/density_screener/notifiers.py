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
        f"{summary['headline']}\n"
        f"Цена: {summary['price_line']}\n"
        f"Объем: {summary['order_value']}\n"
        f"Расстояние от спреда: {summary['distance']}\n"
        f"Время жизни: {summary['lifetime']}\n"
        f"Exchange: {summary['exchange_label']}"
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
            f"<b>{escape(summary['headline'])}</b>\n\n"
            f"<b>Цена: {escape(summary['price_prefix'])}{escape(summary['price'])} {escape(summary['price_pct'])}</b>\n"
            f"<b>Объем: {escape(summary['order_value'])}</b>\n"
            f"Расстояние от спреда: <code>{escape(summary['distance'])}</code>\n"
            f"Время жизни: <code>{escape(summary['lifetime'])}</code>\n"
            f"Exchange: <code>{escape(summary['exchange_label'])}</code>"
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
    side = "BUY (BID)" if signal.side == "bid" else "SELL (ASK)"
    mid_price = _coerce_float(signal.metadata.get("mid_price"))
    price_pct = ""
    distance_line = "n/a"
    if mid_price and mid_price > 0:
        price_delta = signal.price - mid_price
        distance_pct = abs(price_delta) / mid_price * 100
        signed_pct = f"{price_delta / mid_price * 100:+.2f}%"
        direction = "↑" if price_delta > 0 else "↓" if price_delta < 0 else "→"
        price_pct = f"({signed_pct})"
        distance_line = f"{_format_signed_price(price_delta)} ({distance_pct:.2f}%) {direction}"
    return {
        "headline": f"{signal.symbol} — {side}",
        "exchange_label": _human_exchange_label(signal.exchange, signal.market_type),
        "price_prefix": "🟢 " if signal.side == "bid" else "🔴 ",
        "price": _format_price_value(signal.price),
        "price_line": f"{_format_price_value(signal.price)} {price_pct}".strip(),
        "order_value": _format_dollar_value(signal.notional),
        "distance": distance_line,
        "lifetime": f"{signal.resting_seconds:.1f} сек",
        "price_pct": price_pct,
    }


def _format_price_value(value: float) -> str:
    text = f"{value:.8f}".rstrip("0").rstrip(".")
    if "." not in text:
        return text + ".0000"
    whole, fractional = text.split(".", 1)
    return f"{whole}.{fractional.ljust(4, '0')}"


def _format_signed_price(value: float) -> str:
    sign = "+" if value > 0 else "-" if value < 0 else " "
    return f"{sign}{_format_price_value(abs(value))}" if sign.strip() else _format_price_value(0.0)


def _format_dollar_value(value: float) -> str:
    return "$" + f"{value:,.2f}".replace(",", " ")


def _human_exchange_label(exchange: str, market_type: str) -> str:
    exchange_names = {
        "aster": "Aster",
        "bitget_spot": "Bitget",
        "bybit_spot": "Bybit",
        "htx": "HTX",
        "hyperliquid": "Hyperliquid",
        "kucoin_futures": "KuCoin",
        "kucoin_spot": "KuCoin",
        "lighter": "Lighter",
    }
    market_names = {
        "spot": "Spot",
        "futures": "Futures",
    }
    return f"{exchange_names.get(exchange, exchange)} {market_names.get(market_type, market_type.title())}".strip()
