from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import datetime, timezone
import time

import aiohttp

from density_screener.blacklist import BlacklistMatcher, ensure_blacklist_matcher
from density_screener.exchanges.base import ExchangeAdapter, ExchangeInstrument, OrderBookState
from density_screener.models import VolumeReference
from density_screener.runtime import ScreenerRuntime
from density_screener.settings import DetectionConfig


class HyperliquidAdapter(ExchangeAdapter):
    INFO_URL = "https://api.hyperliquid.xyz/info"
    WS_URL = "wss://api.hyperliquid.xyz/ws"

    def __init__(self, detection: DetectionConfig, *, subscription_batch_size: int = 20) -> None:
        self._detection = detection
        self._subscription_batch_size = subscription_batch_size

    @property
    def name(self) -> str:
        return "hyperliquid"

    async def discover_instruments(self, blacklist: BlacklistMatcher) -> list[ExchangeInstrument]:
        payload = await self._post_info({"type": "meta"})
        instruments: list[ExchangeInstrument] = []
        for item in payload["universe"]:
            if item.get("isDelisted", False):
                continue
            instrument = ExchangeInstrument(
                exchange=self.name,
                symbol=item["name"],
                market_type="futures",
                tick_size=None,
                metadata={
                    "baseAsset": item.get("name", ""),
                    "szDecimals": item.get("szDecimals", 0),
                },
            )
            if blacklist.matches(instrument.symbol, instrument.metadata):
                continue
            instruments.append(instrument)
        return instruments

    async def bootstrap_volume_reference(self, instrument: ExchangeInstrument) -> VolumeReference:
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - self._detection.rolling_candle_count * 5 * 60 * 1000
        payload = await self._post_info(
            {
                "type": "candleSnapshot",
                "req": {
                    "coin": instrument.symbol,
                    "interval": "5m",
                    "startTime": start_ms,
                    "endTime": end_ms,
                },
            }
        )
        candles = payload[-self._detection.rolling_candle_count :]
        notionals = [float(row["v"]) * float(row["c"]) for row in candles]
        average_notional = sum(notionals) / max(len(notionals), 1)
        return VolumeReference(
            avg_candle_notional=average_notional,
            candle_count=len(notionals),
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
            raise RuntimeError("No Hyperliquid instruments available after filtering.")
        print(f"[hyperliquid] discovered={len(instruments)}", flush=True)
        print(f"[hyperliquid] symbols={','.join(item.symbol for item in instruments[:5])}", flush=True)

        volume_references = await self._bootstrap_all_volumes(instruments)
        print(f"[hyperliquid] bootstrapped_volumes={len(volume_references)}", flush=True)

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
                market_type="futures",
                tick_size=None,
            )
            for instrument in instruments
        }
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self.WS_URL, heartbeat=None) as ws:
                for instrument in instruments:
                    await ws.send_json(
                        {
                            "method": "subscribe",
                            "subscription": {
                                "type": "l2Book",
                                "coin": instrument.symbol,
                            },
                        }
                    )

                async for message in ws:
                    if message.type != aiohttp.WSMsgType.TEXT:
                        if message.type == aiohttp.WSMsgType.ERROR:
                            raise RuntimeError("Hyperliquid websocket error")
                        continue
                    payload = message.json()
                    if payload.get("channel") == "subscriptionResponse":
                        continue
                    if payload.get("channel") != "l2Book":
                        continue

                    book = payload["data"]
                    symbol = book["coin"]
                    bid_levels = book["levels"][0]
                    ask_levels = book["levels"][1]
                    bids = [(float(level["px"]), float(level["sz"])) for level in bid_levels]
                    asks = [(float(level["px"]), float(level["sz"])) for level in ask_levels]
                    states[symbol].replace(bids, asks)
                    snapshot = states[symbol].to_snapshot(datetime.now(timezone.utc))
                    if snapshot is None:
                        continue
                    signals = await runtime.handle_snapshot(snapshot, volume_references[symbol])
                    if stop_after_snapshots is not None and runtime.stats.snapshots_processed >= stop_after_snapshots:
                        print(
                            f"[hyperliquid] processed_snapshots={runtime.stats.snapshots_processed}",
                            flush=True,
                        )
                        return
                    for signal in signals:
                        print(runtime.render_signal(signal), flush=True)

    async def _post_info(self, payload: dict) -> dict | list:
        async with aiohttp.ClientSession() as session:
            async with session.post(self.INFO_URL, json=payload, timeout=20) as response:
                response.raise_for_status()
                return await response.json()
