from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

import aiohttp

from density_screener.blacklist import BlacklistMatcher, ensure_blacklist_matcher
from density_screener.exchanges.base import ExchangeAdapter, ExchangeInstrument, OrderBookState
from density_screener.exchanges.spot_filters import should_skip_spot_base
from density_screener.models import VolumeReference
from density_screener.runtime import ScreenerRuntime
from density_screener.settings import DetectionConfig


class BybitSpotAdapter(ExchangeAdapter):
    REST_BASE = "https://api.bybit.com"
    WS_URL = "wss://stream.bybit.com/v5/public/spot"
    STABLE_QUOTES = {"USDT", "USDC", "USD", "FDUSD", "BUSD"}

    def __init__(self, detection: DetectionConfig, *, subscription_batch_size: int = 10) -> None:
        self._detection = detection
        self._subscription_batch_size = subscription_batch_size

    @property
    def name(self) -> str:
        return "bybit_spot"

    async def discover_instruments(self, blacklist: BlacklistMatcher) -> list[ExchangeInstrument]:
        params = {"category": "spot", "limit": "1000"}
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.REST_BASE}/v5/market/instruments-info", params=params, timeout=20) as response:
                response.raise_for_status()
                payload = await response.json()
        instruments: list[ExchangeInstrument] = []
        for item in payload["result"]["list"]:
            if item.get("status") not in {"Trading", None}:
                continue
            if item.get("quoteCoin") not in self.STABLE_QUOTES:
                continue
            if should_skip_spot_base(item.get("baseCoin")):
                continue
            instrument = ExchangeInstrument(
                exchange=self.name,
                symbol=item["symbol"],
                market_type="spot",
                tick_size=float(item["priceFilter"]["tickSize"]),
                metadata={
                    "baseCoin": item.get("baseCoin", ""),
                    "quoteCoin": item.get("quoteCoin", ""),
                },
            )
            if blacklist.matches(instrument.symbol, instrument.metadata):
                continue
            instruments.append(instrument)
        return instruments

    async def bootstrap_volume_reference(self, instrument: ExchangeInstrument) -> VolumeReference:
        params = {
            "category": "spot",
            "symbol": instrument.symbol,
            "interval": "5",
            "limit": str(self._detection.rolling_candle_count),
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.REST_BASE}/v5/market/kline", params=params, timeout=20) as response:
                response.raise_for_status()
                payload = await response.json()
        candles = payload["result"]["list"]
        turnovers = [float(row[6]) for row in candles[: self._detection.rolling_candle_count]]
        average_turnover = sum(turnovers) / max(len(turnovers), 1)
        return VolumeReference(
            avg_candle_notional=average_turnover,
            candle_count=len(turnovers),
            interval=self._detection.candle_interval,
        )

    async def run(
        self,
        runtime: ScreenerRuntime,
        *,
        blacklist: Iterable[str] = (),
        symbol_limit: int | None = None,
        stop_after_snapshots: int | None = None,
    ) -> None:
        matcher = ensure_blacklist_matcher(blacklist)
        instruments = await self.discover_instruments(matcher)
        if symbol_limit is not None:
            instruments = instruments[:symbol_limit]
        if not instruments:
            raise RuntimeError("No Bybit spot instruments available after filtering.")
        print(f"[bybit_spot] discovered={len(instruments)}", flush=True)

        volume_references = await self._bootstrap_all_volumes(instruments)
        print(f"[bybit_spot] bootstrapped_volumes={len(volume_references)}", flush=True)
        batches = [
            instruments[index : index + self._subscription_batch_size]
            for index in range(0, len(instruments), self._subscription_batch_size)
        ]
        tasks = [
            asyncio.create_task(
                self._run_batch(
                    runtime,
                    batch,
                    volume_references,
                    stop_after_snapshots=stop_after_snapshots,
                )
            )
            for batch in batches
        ]
        await asyncio.gather(*tasks)

    async def _bootstrap_all_volumes(
        self,
        instruments: list[ExchangeInstrument],
    ) -> dict[str, VolumeReference]:
        semaphore = asyncio.Semaphore(8)
        references: dict[str, VolumeReference] = {}

        async def load_one(instrument: ExchangeInstrument) -> None:
            async with semaphore:
                references[instrument.symbol] = await self.bootstrap_volume_reference(instrument)

        await asyncio.gather(*(load_one(instrument) for instrument in instruments))
        return references

    async def _run_batch(
        self,
        runtime: ScreenerRuntime,
        instruments: list[ExchangeInstrument],
        volume_references: dict[str, VolumeReference],
        *,
        stop_after_snapshots: int | None = None,
    ) -> None:
        states = {
            instrument.symbol: OrderBookState(
                exchange=self.name,
                symbol=instrument.symbol,
                market_type="spot",
                tick_size=instrument.tick_size,
            )
            for instrument in instruments
        }
        topics = [f"orderbook.50.{instrument.symbol}" for instrument in instruments]
        subscribe_payload = {"op": "subscribe", "args": topics}

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self.WS_URL, heartbeat=25) as ws:
                print(f"[bybit_spot] ws_connected batch={len(instruments)}", flush=True)
                await ws.send_json(subscribe_payload)
                async for message in ws:
                    if message.type == aiohttp.WSMsgType.TEXT:
                        payload = message.json()
                        topic = payload.get("topic")
                        if not topic or not topic.startswith("orderbook."):
                            continue
                        self._apply_message(states, payload)
                        symbol = payload["data"]["s"]
                        timestamp = datetime.now(timezone.utc)
                        if not runtime.should_process_snapshot(self.name, symbol, timestamp):
                            continue
                        snapshot = states[symbol].to_snapshot(timestamp)
                        if snapshot is None:
                            continue
                        signals = await runtime.handle_snapshot(snapshot, volume_references[symbol])
                        if stop_after_snapshots is not None and runtime.stats.snapshots_processed >= stop_after_snapshots:
                            print(
                                f"[bybit_spot] processed_snapshots={runtime.stats.snapshots_processed}",
                                flush=True,
                            )
                            return
                        for signal in signals:
                            print(runtime.render_signal(signal), flush=True)
                    elif message.type == aiohttp.WSMsgType.ERROR:
                        raise RuntimeError("Bybit websocket error")

    @staticmethod
    def _apply_message(states: dict[str, OrderBookState], payload: dict[str, Any]) -> None:
        data = payload["data"]
        symbol = data["s"]
        state = states[symbol]
        bids = [(float(price), float(size)) for price, size in data.get("b", [])]
        asks = [(float(price), float(size)) for price, size in data.get("a", [])]

        if payload.get("type") == "snapshot":
            state.replace(bids, asks)
            return
        state.apply_delta(bids, asks)
