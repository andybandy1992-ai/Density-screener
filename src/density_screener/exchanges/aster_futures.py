from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import datetime, timezone

import aiohttp

from density_screener.blacklist import BlacklistMatcher, ensure_blacklist_matcher
from density_screener.exchanges.base import ExchangeAdapter, ExchangeInstrument, OrderBookState
from density_screener.models import VolumeReference
from density_screener.runtime import ScreenerRuntime
from density_screener.settings import DetectionConfig


class AsterFuturesAdapter(ExchangeAdapter):
    REST_BASE = "https://fapi.asterdex.com"
    WS_BASE = "wss://fstream.asterdex.com/ws"

    def __init__(self, detection: DetectionConfig, *, subscription_batch_size: int = 10) -> None:
        self._detection = detection
        self._subscription_batch_size = subscription_batch_size

    @property
    def name(self) -> str:
        return "aster"

    async def discover_instruments(self, blacklist: BlacklistMatcher) -> list[ExchangeInstrument]:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.REST_BASE}/fapi/v1/exchangeInfo", timeout=20) as response:
                response.raise_for_status()
                payload = await response.json()
        instruments: list[ExchangeInstrument] = []
        for item in payload["symbols"]:
            if item.get("status") != "TRADING":
                continue
            instrument = ExchangeInstrument(
                exchange=self.name,
                symbol=item["symbol"],
                market_type="futures",
                tick_size=float(item["filters"][0]["tickSize"]),
                metadata={
                    "baseAsset": item.get("baseAsset", ""),
                    "quoteAsset": item.get("quoteAsset", ""),
                },
            )
            if blacklist.matches(instrument.symbol, instrument.metadata):
                continue
            instruments.append(instrument)
        return instruments

    async def bootstrap_volume_reference(self, instrument: ExchangeInstrument) -> VolumeReference:
        params = {
            "symbol": instrument.symbol,
            "interval": "5m",
            "limit": str(self._detection.rolling_candle_count),
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.REST_BASE}/fapi/v1/klines", params=params, timeout=20) as response:
                response.raise_for_status()
                payload = await response.json()
        candles = payload[: self._detection.rolling_candle_count]
        turnovers = [float(row[7]) for row in candles]
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
            raise RuntimeError("No Aster futures instruments available after filtering.")
        print(f"[aster] discovered={len(instruments)}", flush=True)
        print(f"[aster] symbols={','.join(item.symbol for item in instruments[:5])}", flush=True)

        volume_references = await self._bootstrap_all_volumes(instruments)
        instruments = [instrument for instrument in instruments if instrument.symbol in volume_references]
        if not instruments:
            raise RuntimeError("No Aster futures instruments left after volume bootstrap.")
        print(f"[aster] bootstrapped_volumes={len(volume_references)}", flush=True)

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
                tick_size=instrument.tick_size,
            )
            for instrument in instruments
        }
        stream_names = [self._stream_name_for(instrument.symbol) for instrument in instruments]
        if len(stream_names) == 1:
            ws_url = f"{self.WS_BASE}/{stream_names[0]}"
        else:
            ws_url = f"{self.WS_BASE}/stream?streams={'/'.join(stream_names)}"

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(ws_url, heartbeat=None) as ws:
                async for message in ws:
                    if message.type != aiohttp.WSMsgType.TEXT:
                        if message.type == aiohttp.WSMsgType.ERROR:
                            raise RuntimeError("Aster websocket error")
                        continue
                    wrapper = message.json()
                    stream_name = wrapper.get("stream")
                    payload = wrapper.get("data", wrapper)
                    symbol = self._symbol_from_stream_name(stream_name or payload.get("s", ""))
                    if symbol not in states:
                        continue
                    bids = [(float(price), float(size)) for price, size in payload["b"]]
                    asks = [(float(price), float(size)) for price, size in payload["a"]]
                    states[symbol].replace(bids, asks)
                    snapshot = states[symbol].to_snapshot(datetime.now(timezone.utc))
                    if snapshot is None:
                        continue
                    signals = await runtime.handle_snapshot(snapshot, volume_references[symbol])
                    if stop_after_snapshots is not None and runtime.stats.snapshots_processed >= stop_after_snapshots:
                        print(f"[aster] processed_snapshots={runtime.stats.snapshots_processed}", flush=True)
                        return
                    for signal in signals:
                        print(runtime.render_signal(signal), flush=True)

    @staticmethod
    def _stream_name_for(symbol: str) -> str:
        return f"{symbol.lower()}@depth20@100ms"

    @staticmethod
    def _symbol_from_stream_name(stream_name: str) -> str:
        if "@" in stream_name:
            return stream_name.split("@", 1)[0].upper()
        return stream_name.upper()
