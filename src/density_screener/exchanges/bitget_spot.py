from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

import aiohttp

from density_screener.blacklist import BlacklistMatcher, ensure_blacklist_matcher
from density_screener.exchanges.base import ExchangeAdapter, ExchangeInstrument, OrderBookState
from density_screener.models import VolumeReference
from density_screener.runtime import ScreenerRuntime
from density_screener.settings import DetectionConfig


class BitgetSpotAdapter(ExchangeAdapter):
    REST_BASE = "https://api.bitget.com"
    WS_URL = "wss://ws.bitget.com/v2/ws/public"
    STABLE_QUOTES = {"USDT", "USDC", "USD", "FDUSD", "BUSD"}
    ORDER_BOOK_CHANNEL = "books15"

    def __init__(self, detection: DetectionConfig, *, subscription_batch_size: int = 40) -> None:
        self._detection = detection
        self._subscription_batch_size = subscription_batch_size

    @property
    def name(self) -> str:
        return "bitget_spot"

    async def discover_instruments(self, blacklist: BlacklistMatcher) -> list[ExchangeInstrument]:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.REST_BASE}/api/v2/spot/public/symbols", timeout=20) as response:
                response.raise_for_status()
                payload = await response.json()
        instruments: list[ExchangeInstrument] = []
        for item in payload["data"]:
            if item.get("status") != "online":
                continue
            if item.get("quoteCoin") not in self.STABLE_QUOTES:
                continue
            instrument = ExchangeInstrument(
                exchange=self.name,
                symbol=item["symbol"],
                market_type="spot",
                tick_size=10 ** (-int(item["pricePrecision"])),
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
            "symbol": instrument.symbol,
            "granularity": "5min",
            "limit": str(self._detection.rolling_candle_count),
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.REST_BASE}/api/v2/spot/market/candles", params=params, timeout=20) as response:
                response.raise_for_status()
                payload = await response.json()
        candles = payload["data"][: self._detection.rolling_candle_count]
        turnovers = [float(row[7] if len(row) > 7 else row[6]) for row in candles]
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
            raise RuntimeError("No Bitget spot instruments available after filtering.")
        print(f"[bitget_spot] discovered={len(instruments)}", flush=True)
        print(f"[bitget_spot] symbols={','.join(item.symbol for item in instruments[:5])}", flush=True)

        volume_references = await self._bootstrap_all_volumes(instruments)
        print(f"[bitget_spot] bootstrapped_volumes={len(volume_references)}", flush=True)
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
        subscribe_payload = {
            "op": "subscribe",
            "args": [
                {
                    "instType": "SPOT",
                    "channel": self.ORDER_BOOK_CHANNEL,
                    "instId": instrument.symbol,
                }
                for instrument in instruments
            ],
        }

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self.WS_URL, heartbeat=25) as ws:
                print(f"[bitget_spot] ws_connected batch={len(instruments)}", flush=True)
                await ws.send_json(subscribe_payload)
                async for message in ws:
                    if message.type == aiohttp.WSMsgType.TEXT:
                        if message.data == "pong":
                            continue
                        payload = message.json()
                        if payload.get("event") == "subscribe":
                            continue
                        if payload.get("event") == "error":
                            raise RuntimeError(f"Bitget subscription error: {payload}")
                        if payload.get("op") == "pong":
                            continue
                        arg = payload.get("arg", {})
                        if arg.get("channel") != self.ORDER_BOOK_CHANNEL:
                            continue
                        symbol = arg["instId"]
                        data = payload["data"][0]
                        bids = [(float(price), float(size)) for price, size in data.get("bids", [])]
                        asks = [(float(price), float(size)) for price, size in data.get("asks", [])]
                        states[symbol].replace(bids, asks)
                        snapshot = states[symbol].to_snapshot(datetime.now(timezone.utc))
                        if snapshot is None:
                            continue
                        signals = await runtime.handle_snapshot(snapshot, volume_references[symbol])
                        if stop_after_snapshots is not None and runtime.stats.snapshots_processed >= stop_after_snapshots:
                            print(
                                f"[bitget_spot] processed_snapshots={runtime.stats.snapshots_processed}",
                                flush=True,
                            )
                            return
                        for signal in signals:
                            print(runtime.render_signal(signal), flush=True)
                    elif message.type == aiohttp.WSMsgType.ERROR:
                        raise RuntimeError("Bitget websocket error")
