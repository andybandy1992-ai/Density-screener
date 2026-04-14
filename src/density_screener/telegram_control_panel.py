from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import aiohttp

from density_screener.health import HealthMonitor
from density_screener.runtime_controls import RuntimeControlSnapshot, RuntimeControlStore
from density_screener.settings import TelegramConfig


@dataclass(slots=True, frozen=True)
class PendingAction:
    kind: str
    market_type: str = ""
    exchange: str = ""


class TelegramControlBot:
    POLL_TIMEOUT_SECONDS = 30

    def __init__(
        self,
        config: TelegramConfig,
        controls: RuntimeControlStore,
        health_monitor: HealthMonitor | None = None,
        exchange_markets: dict[str, str] | None = None,
    ) -> None:
        self._config = config
        self._controls = controls
        self._health_monitor = health_monitor
        self._offset = 0
        self._pending_actions: dict[tuple[str, int], PendingAction] = {}
        self._session: aiohttp.ClientSession | None = None
        self._exchange_markets = {
            self._normalize_exchange(name): market_type
            for name, market_type in (exchange_markets or {}).items()
        }

    @property
    def enabled(self) -> bool:
        return self._config.enabled and bool(self._config.bot_token and self._config.chat_id)

    async def run(self) -> None:
        if not self.enabled:
            return
        async with aiohttp.ClientSession() as session:
            self._session = session
            while True:
                try:
                    updates = await self._get_updates()
                    for update in updates:
                        self._offset = max(self._offset, int(update["update_id"]) + 1)
                        await self._handle_update(update)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    print(
                        f"[telegram_bot] reconnecting reason={error.__class__.__name__}: {error}",
                        flush=True,
                    )
                    await asyncio.sleep(2)

    async def _handle_update(self, update: dict[str, Any]) -> None:
        if "callback_query" in update:
            await self._handle_callback_query(update["callback_query"])
            return
        if "message" in update:
            await self._handle_message(update["message"])

    async def _handle_message(self, message: dict[str, Any]) -> None:
        chat_id = str(message.get("chat", {}).get("id", ""))
        user_id = int(message.get("from", {}).get("id", 0))
        if not self._is_authorized(chat_id, user_id):
            return

        text = str(message.get("text", "")).strip()
        if not text:
            return

        pending_key = (chat_id, user_id)
        if text.startswith("/panel") or text.startswith("/start"):
            self._pending_actions.pop(pending_key, None)
            await self._send_panel(chat_id)
            return
        if text.startswith("/health") or text.startswith("/status"):
            self._pending_actions.pop(pending_key, None)
            await self._send_text(chat_id, self._format_health_report())
            return

        pending = self._pending_actions.get(pending_key)
        if pending is None:
            return

        if pending.kind == "set_threshold":
            value = self._parse_numeric_input(text)
            if value is None:
                await self._send_text(
                    chat_id,
                    "Reply with a number in USD, for example: `75000`.",
                    parse_mode="Markdown",
                )
                return
            snapshot = self._controls.set_min_notional(pending.market_type, value)
            self._pending_actions.pop(pending_key, None)
            await self._send_text(chat_id, self._format_threshold_confirmation(pending.market_type, snapshot))
            await self._send_panel(chat_id)
            return

        if pending.kind == "set_exchange_threshold":
            value = self._parse_numeric_input(text)
            if value is None:
                await self._send_text(
                    chat_id,
                    "Reply with a number in USD, for example: `75000`.",
                    parse_mode="Markdown",
                )
                return
            snapshot = self._controls.set_exchange_min_notional(pending.exchange, value)
            self._pending_actions.pop(pending_key, None)
            await self._send_text(
                chat_id,
                self._format_exchange_threshold_confirmation(pending.exchange, snapshot),
            )
            await self._send_exchange_threshold_panel(chat_id, pending.exchange)
            return

        if pending.kind == "set_multiplier":
            value = self._parse_numeric_input(text)
            if value is None:
                await self._send_text(
                    chat_id,
                    "Reply with a multiplier value, for example: `4.5`.",
                    parse_mode="Markdown",
                )
                return
            snapshot = self._controls.set_volume_multiplier(pending.market_type, value)
            self._pending_actions.pop(pending_key, None)
            await self._send_text(chat_id, self._format_multiplier_confirmation(pending.market_type, snapshot))
            await self._send_panel(chat_id)
            return

        if pending.kind == "add_blacklist":
            try:
                added_terms = []
                for term in self._parse_blacklist_terms(text):
                    self._controls.add_blacklist_term(term)
                    added_terms.append(term)
            except ValueError as error:
                await self._send_text(chat_id, str(error))
                return
            if not added_terms:
                await self._send_text(chat_id, "Reply with at least one blacklist rule.")
                return
            self._pending_actions.pop(pending_key, None)
            if len(added_terms) == 1:
                await self._send_text(chat_id, f"Rule added: {added_terms[0]}")
            else:
                await self._send_text(chat_id, "Rules added:\n" + "\n".join(f"- {term}" for term in added_terms))
            await self._send_panel(chat_id)
            return

        if pending.kind == "remove_blacklist":
            try:
                removed_terms = []
                for term in self._parse_blacklist_terms(text):
                    self._controls.remove_blacklist_term(term)
                    removed_terms.append(term)
            except ValueError as error:
                await self._send_text(chat_id, str(error))
                return
            if not removed_terms:
                await self._send_text(chat_id, "Reply with at least one blacklist rule.")
                return
            self._pending_actions.pop(pending_key, None)
            if len(removed_terms) == 1:
                await self._send_text(chat_id, f"Rule removed: {removed_terms[0]}")
            else:
                await self._send_text(chat_id, "Rules removed:\n" + "\n".join(f"- {term}" for term in removed_terms))
            await self._send_panel(chat_id)

    async def _handle_callback_query(self, query: dict[str, Any]) -> None:
        message = query.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        user_id = int(query.get("from", {}).get("id", 0))
        if not self._is_authorized(chat_id, user_id):
            await self._answer_callback_query(query["id"], "Unauthorized chat.")
            return

        pending_key = (chat_id, user_id)
        data = str(query.get("data", ""))
        message_id = int(message.get("message_id", 0))

        if data in {"panel:refresh", "panel:main"}:
            await self._edit_panel(chat_id, message_id)
            await self._answer_callback_query(query["id"], "Panel refreshed.")
            return

        if data == "panel:exchange-thresholds":
            await self._edit_exchange_threshold_menu(chat_id, message_id)
            await self._answer_callback_query(query["id"], "Exchange thresholds.")
            return

        if data == "panel:health":
            await self._answer_callback_query(query["id"], "Sending health report.")
            await self._send_text(chat_id, self._format_health_report())
            return

        if data.startswith("threshold:"):
            _, market_type, action = data.split(":", 2)
            if action == "custom":
                self._pending_actions[pending_key] = PendingAction("set_threshold", market_type)
                await self._answer_callback_query(query["id"], "Reply with a new USD threshold.")
                await self._send_text(chat_id, self._format_threshold_prompt(market_type))
                return
            delta = float(action)
            snapshot = self._controls.adjust_min_notional(market_type, delta)
            await self._edit_panel(chat_id, message_id)
            await self._answer_callback_query(
                query["id"],
                self._format_threshold_confirmation(market_type, snapshot),
            )
            return

        if data.startswith("exchange_threshold:"):
            _, exchange_name, action, *rest = data.split(":")
            normalized_exchange = self._normalize_exchange(exchange_name)
            if action == "show":
                await self._edit_exchange_threshold_panel(chat_id, message_id, normalized_exchange)
                await self._answer_callback_query(query["id"], "Exchange threshold.")
                return
            if action == "custom":
                self._pending_actions[pending_key] = PendingAction(
                    kind="set_exchange_threshold",
                    exchange=normalized_exchange,
                )
                await self._answer_callback_query(query["id"], "Reply with a new exchange threshold.")
                await self._send_text(chat_id, self._format_exchange_threshold_prompt(normalized_exchange))
                return
            if action == "reset":
                try:
                    snapshot = self._controls.clear_exchange_min_notional(normalized_exchange)
                except ValueError as error:
                    await self._answer_callback_query(query["id"], str(error))
                    return
                await self._edit_exchange_threshold_panel(chat_id, message_id, normalized_exchange)
                await self._answer_callback_query(
                    query["id"],
                    self._format_exchange_threshold_confirmation(normalized_exchange, snapshot),
                )
                return
            if action == "adjust" and rest:
                delta = float(rest[0])
                snapshot = self._controls.adjust_exchange_min_notional(normalized_exchange, delta)
                await self._edit_exchange_threshold_panel(chat_id, message_id, normalized_exchange)
                await self._answer_callback_query(
                    query["id"],
                    self._format_exchange_threshold_confirmation(normalized_exchange, snapshot),
                )
                return

        if data.startswith("multiplier:"):
            _, market_type, action = data.split(":", 2)
            if action == "custom":
                self._pending_actions[pending_key] = PendingAction("set_multiplier", market_type)
                await self._answer_callback_query(query["id"], "Reply with a new multiplier.")
                await self._send_text(chat_id, self._format_multiplier_prompt(market_type))
                return
            delta = float(action)
            snapshot = self._controls.adjust_volume_multiplier(market_type, delta)
            await self._edit_panel(chat_id, message_id)
            await self._answer_callback_query(
                query["id"],
                self._format_multiplier_confirmation(market_type, snapshot),
            )
            return

        if data == "blacklist:add":
            self._pending_actions[pending_key] = PendingAction("add_blacklist")
            await self._answer_callback_query(query["id"], "Reply with a symbol or coin.")
            await self._send_text(
                chat_id,
                "Reply with a blacklist rule.\nExamples: `BTC`, `symbol:BTCUSDT`, `pattern:*1000*`",
                parse_mode="Markdown",
            )
            return

        if data == "blacklist:remove":
            self._pending_actions[pending_key] = PendingAction("remove_blacklist")
            await self._answer_callback_query(query["id"], "Reply with a rule to remove.")
            await self._send_text(
                chat_id,
                "Reply with the exact blacklist rule to remove.\nExamples: `BTC`, `symbol:BTCUSDT`, `pattern:*1000*`",
                parse_mode="Markdown",
            )
            return

        if data == "blacklist:show":
            await self._answer_callback_query(query["id"], "Sending blacklist.")
            await self._send_text(chat_id, self._format_blacklist(self._controls.snapshot()))
            return

        await self._answer_callback_query(query["id"], "Unknown action.")

    async def _get_updates(self) -> list[dict[str, Any]]:
        payload = {
            "offset": self._offset,
            "timeout": self.POLL_TIMEOUT_SECONDS,
            "allowed_updates": ["message", "callback_query"],
        }
        response = await self._post_api("getUpdates", payload)
        return list(response.get("result", []))

    async def _send_panel(self, chat_id: str) -> None:
        await self._send_message(
            chat_id,
            self.format_panel(self._controls.snapshot()),
            reply_markup=self.build_panel_markup(),
        )

    async def _edit_panel(self, chat_id: str, message_id: int) -> None:
        await self._edit_message(
            chat_id,
            message_id,
            self.format_panel(self._controls.snapshot()),
            reply_markup=self.build_panel_markup(),
        )

    async def _send_exchange_threshold_panel(self, chat_id: str, exchange_name: str) -> None:
        await self._send_message(
            chat_id,
            self._format_exchange_threshold_panel(exchange_name, self._controls.snapshot()),
            reply_markup=self._build_exchange_threshold_markup(exchange_name),
        )

    async def _edit_exchange_threshold_panel(self, chat_id: str, message_id: int, exchange_name: str) -> None:
        await self._edit_message(
            chat_id,
            message_id,
            self._format_exchange_threshold_panel(exchange_name, self._controls.snapshot()),
            reply_markup=self._build_exchange_threshold_markup(exchange_name),
        )

    async def _edit_exchange_threshold_menu(self, chat_id: str, message_id: int) -> None:
        await self._edit_message(
            chat_id,
            message_id,
            self._format_exchange_threshold_menu(self._controls.snapshot()),
            reply_markup=self._build_exchange_threshold_menu_markup(),
        )

    async def _send_text(
        self,
        chat_id: str,
        text: str,
        *,
        parse_mode: str | None = None,
    ) -> None:
        await self._send_message(chat_id, text, parse_mode=parse_mode)

    async def _send_message(
        self,
        chat_id: str,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        if parse_mode is not None:
            payload["parse_mode"] = parse_mode
        await self._post_api("sendMessage", payload)

    async def _edit_message(
        self,
        chat_id: str,
        message_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        if parse_mode is not None:
            payload["parse_mode"] = parse_mode
        await self._post_api("editMessageText", payload)

    async def _answer_callback_query(self, callback_query_id: str, text: str) -> None:
        await self._post_api(
            "answerCallbackQuery",
            {
                "callback_query_id": callback_query_id,
                "text": text[:180],
                "show_alert": False,
            },
        )

    async def _post_api(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self._session is None:
            raise RuntimeError("TelegramControlBot session is not initialized.")
        url = f"https://api.telegram.org/bot{self._config.bot_token}/{method}"
        async with self._session.post(url, json=payload, timeout=40) as response:
            response.raise_for_status()
            return await response.json()

    @staticmethod
    def build_panel_markup() -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "Spot -10k", "callback_data": "threshold:spot:-10000"},
                    {"text": "Spot +10k", "callback_data": "threshold:spot:10000"},
                ],
                [
                    {"text": "Futures -10k", "callback_data": "threshold:futures:-10000"},
                    {"text": "Futures +10k", "callback_data": "threshold:futures:10000"},
                ],
                [
                    {"text": "Spot custom", "callback_data": "threshold:spot:custom"},
                    {"text": "Futures custom", "callback_data": "threshold:futures:custom"},
                ],
                [
                    {"text": "Exchange minimums", "callback_data": "panel:exchange-thresholds"},
                ],
                [
                    {"text": "Spot x -1.0", "callback_data": "multiplier:spot:-1.0"},
                    {"text": "Spot x +1.0", "callback_data": "multiplier:spot:1.0"},
                ],
                [
                    {"text": "Futures x -1.0", "callback_data": "multiplier:futures:-1.0"},
                    {"text": "Futures x +1.0", "callback_data": "multiplier:futures:1.0"},
                ],
                [
                    {"text": "Spot mult custom", "callback_data": "multiplier:spot:custom"},
                    {"text": "Futures mult custom", "callback_data": "multiplier:futures:custom"},
                ],
                [
                    {"text": "Add blacklist", "callback_data": "blacklist:add"},
                    {"text": "Remove blacklist", "callback_data": "blacklist:remove"},
                ],
                [
                    {"text": "Show blacklist", "callback_data": "blacklist:show"},
                    {"text": "Refresh", "callback_data": "panel:refresh"},
                ],
                [
                    {"text": "Health", "callback_data": "panel:health"},
                ],
            ]
        }

    @staticmethod
    def format_panel(snapshot: RuntimeControlSnapshot) -> str:
        rules_preview = ", ".join(snapshot.blacklist_terms[:5]) or "none"
        if len(snapshot.blacklist_terms) > 5:
            rules_preview += ", ..."
        override_preview = ", ".join(
            f"{exchange}={value:,.0f}"
            for exchange, value in list(snapshot.exchange_min_notional_usd.items())[:4]
        ) or "none"
        if len(snapshot.exchange_min_notional_usd) > 4:
            override_preview += ", ..."
        return (
            "Density Screener Controls\n"
            f"Spot min notional: {snapshot.spot_min_notional_usd:,.0f} USD\n"
            f"Futures min notional: {snapshot.futures_min_notional_usd:,.0f} USD\n"
            f"Spot multiplier: {snapshot.spot_volume_multiplier:.2f}x\n"
            f"Futures multiplier: {snapshot.futures_volume_multiplier:.2f}x\n"
            f"Exchange overrides: {len(snapshot.exchange_min_notional_usd)}\n"
            f"Override preview: {override_preview}\n"
            f"Bot blacklist rules: {len(snapshot.blacklist_terms)}\n"
            f"Preview: {rules_preview}\n\n"
            "Use buttons below to update global filters, exchange overrides, or the bot-managed blacklist.\n"
            "Use /health for the current system and exchange status."
        )

    def _build_exchange_threshold_menu_markup(self) -> dict[str, Any]:
        rows = [
            [
                {
                    "text": self._human_exchange_label(exchange_name),
                    "callback_data": f"exchange_threshold:{exchange_name}:show",
                }
            ]
            for exchange_name in self._sorted_exchange_names()
        ]
        rows.append([{"text": "Back", "callback_data": "panel:main"}])
        return {"inline_keyboard": rows}

    def _build_exchange_threshold_markup(self, exchange_name: str) -> dict[str, Any]:
        normalized_exchange = self._normalize_exchange(exchange_name)
        return {
            "inline_keyboard": [
                [
                    {
                        "text": "-10k",
                        "callback_data": f"exchange_threshold:{normalized_exchange}:adjust:-10000",
                    },
                    {
                        "text": "+10k",
                        "callback_data": f"exchange_threshold:{normalized_exchange}:adjust:10000",
                    },
                ],
                [
                    {
                        "text": "Custom",
                        "callback_data": f"exchange_threshold:{normalized_exchange}:custom",
                    },
                    {
                        "text": "Reset",
                        "callback_data": f"exchange_threshold:{normalized_exchange}:reset",
                    },
                ],
                [
                    {"text": "Back to exchanges", "callback_data": "panel:exchange-thresholds"},
                    {"text": "Main panel", "callback_data": "panel:main"},
                ],
            ]
        }

    def _format_exchange_threshold_menu(self, snapshot: RuntimeControlSnapshot) -> str:
        lines = [
            "Exchange minimum thresholds",
            "Choose an exchange to override its minimum order value.",
            "",
        ]
        for exchange_name in self._sorted_exchange_names():
            lines.append(self._format_exchange_threshold_line(exchange_name, snapshot))
        return "\n".join(lines)

    def _format_exchange_threshold_line(
        self,
        exchange_name: str,
        snapshot: RuntimeControlSnapshot,
    ) -> str:
        market_type = self._exchange_markets.get(exchange_name, "")
        override = snapshot.exchange_min_notional_usd.get(exchange_name)
        if override is not None:
            return f"- {self._human_exchange_label(exchange_name)}: {override:,.0f} USD override"
        if market_type == "spot":
            baseline = snapshot.spot_min_notional_usd
            label = "spot global"
        elif market_type == "futures":
            baseline = snapshot.futures_min_notional_usd
            label = "futures global"
        else:
            return (
                f"- {self._human_exchange_label(exchange_name)}: uses spot/futures globals "
                f"({snapshot.spot_min_notional_usd:,.0f} / {snapshot.futures_min_notional_usd:,.0f} USD)"
            )
        return f"- {self._human_exchange_label(exchange_name)}: {baseline:,.0f} USD ({label})"

    def _format_exchange_threshold_panel(
        self,
        exchange_name: str,
        snapshot: RuntimeControlSnapshot,
    ) -> str:
        normalized_exchange = self._normalize_exchange(exchange_name)
        market_type = self._exchange_markets.get(normalized_exchange, "")
        override = snapshot.exchange_min_notional_usd.get(normalized_exchange)
        lines = [
            f"{self._human_exchange_label(normalized_exchange)} minimum threshold",
            "",
        ]
        if override is None:
            lines.append("Exchange override: not set")
        else:
            lines.append(f"Exchange override: {override:,.0f} USD")

        if market_type == "spot":
            lines.append(f"Global spot threshold: {snapshot.spot_min_notional_usd:,.0f} USD")
            effective = override if override is not None else snapshot.spot_min_notional_usd
        elif market_type == "futures":
            lines.append(f"Global futures threshold: {snapshot.futures_min_notional_usd:,.0f} USD")
            effective = override if override is not None else snapshot.futures_min_notional_usd
        else:
            lines.append(
                "Global mixed baseline: "
                f"spot {snapshot.spot_min_notional_usd:,.0f} USD / "
                f"futures {snapshot.futures_min_notional_usd:,.0f} USD"
            )
            effective = override

        if effective is None:
            lines.append("Effective threshold: uses market-specific global values")
        else:
            lines.append(f"Effective threshold: {effective:,.0f} USD")

        lines.append("")
        lines.append("Buttons below update only this exchange.")
        return "\n".join(lines)

    @staticmethod
    def _format_threshold_confirmation(
        market_type: str,
        snapshot: RuntimeControlSnapshot,
    ) -> str:
        value = snapshot.spot_min_notional_usd if market_type == "spot" else snapshot.futures_min_notional_usd
        label = "Spot" if market_type == "spot" else "Futures"
        return f"{label} threshold set to {value:,.0f} USD."

    @staticmethod
    def _format_threshold_prompt(market_type: str) -> str:
        label = "spot" if market_type == "spot" else "futures"
        return f"Reply with the new global {label} minimum threshold in USD.\nExample: `75000`"

    def _format_exchange_threshold_confirmation(
        self,
        exchange_name: str,
        snapshot: RuntimeControlSnapshot,
    ) -> str:
        value = snapshot.exchange_min_notional_usd.get(self._normalize_exchange(exchange_name))
        if value is None:
            return f"{self._human_exchange_label(exchange_name)} override reset to global."
        return f"{self._human_exchange_label(exchange_name)} threshold set to {value:,.0f} USD."

    def _format_exchange_threshold_prompt(self, exchange_name: str) -> str:
        return (
            f"Reply with the new minimum threshold for {self._human_exchange_label(exchange_name)} in USD.\n"
            "Example: `75000`"
        )

    @staticmethod
    def _format_multiplier_confirmation(
        market_type: str,
        snapshot: RuntimeControlSnapshot,
    ) -> str:
        value = snapshot.spot_volume_multiplier if market_type == "spot" else snapshot.futures_volume_multiplier
        label = "Spot" if market_type == "spot" else "Futures"
        return f"{label} multiplier set to {value:.2f}x."

    @staticmethod
    def _format_multiplier_prompt(market_type: str) -> str:
        label = "spot" if market_type == "spot" else "futures"
        return f"Reply with the new global {label} multiplier.\nExample: `4.5`"

    @staticmethod
    def _format_blacklist(snapshot: RuntimeControlSnapshot) -> str:
        if not snapshot.blacklist_terms:
            return "Bot-managed blacklist is empty."
        return "Bot-managed blacklist:\n" + "\n".join(f"- {term}" for term in snapshot.blacklist_terms)

    @staticmethod
    def _parse_numeric_input(text: str) -> float | None:
        normalized = text.strip().replace(" ", "").replace(",", "")
        if not normalized:
            return None
        try:
            return float(normalized)
        except ValueError:
            return None

    @staticmethod
    def _parse_blacklist_terms(text: str) -> tuple[str, ...]:
        terms: list[str] = []
        for line in text.replace("\r", "\n").splitlines():
            parts = [part.strip() for part in line.split(",")]
            terms.extend(part for part in parts if part)
        return tuple(terms)

    def _sorted_exchange_names(self) -> list[str]:
        return sorted(self._exchange_markets, key=self._human_exchange_label)

    def _is_authorized(self, chat_id: str, user_id: int) -> bool:
        if self._config.control_user_ids:
            return str(user_id) in self._config.control_user_ids
        return chat_id == self._config.chat_id

    def _format_health_report(self) -> str:
        if self._health_monitor is None:
            return "Health monitor is not attached to this bot instance."
        return self._health_monitor.format_report()

    def _human_exchange_label(self, exchange_name: str) -> str:
        normalized_exchange = self._normalize_exchange(exchange_name)
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
            "mixed": "Mixed",
        }
        market_type = self._exchange_markets.get(normalized_exchange, "")
        label = exchange_names.get(normalized_exchange, normalized_exchange)
        market_label = market_names.get(market_type, market_type.title())
        return f"{label} {market_label}".strip()

    @staticmethod
    def _normalize_exchange(exchange_name: str) -> str:
        return exchange_name.strip().lower()
