from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import datetime, timezone
import gzip
import json

import aiohttp

from density_screener.blacklist import BlacklistMatcher, ensure_blacklist_matcher
from density_screener.exchanges.base import ExchangeAdapter, ExchangeInstrument, OrderBookState
from density_screener.models import VolumeReference
from density_screener.runtime import ScreenerRuntime
from density_screener.settings import DetectionConfig


class HTXSpotAdapter(ExchangeAdapter):
    REST_BASE = "https://api.huobi.pro"
    WS_URL = "wss://api.huobi.pro/ws"
    STABLE_QUOTES = {"usdt", "usdc", "usd", "fdusd", "busd"}

    def __init__(self, detection: DetectionConfig, *, subscription_batch_size: int = 25) -> None:
        self._detection = detection
        self._subscription_batch_size = subscription_batch_size

    @property
    def name(self) -> str:
        return "htx"

    async def discover_instruments(self, blacklist: BlacklistMatcher) -> list[ExchangeInstrument]:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.REST_BASE}/v1/common/symbols", timeout=20) as response:
                response.raise_for_status()
                payload = await response.json()
        instruments: list[ExchangeInstrument] = []
        for item in payload["data"]:
            if item.get("state") != "online":
                continue
            if item.get("quote-currency") not in self.STABLE_QUOTES:
                continue
            instrument = ExchangeInstrument(
                exchange=self.name,
                symbol=item["symbol"],
                market_type="spot",
                tick_size=10 ** (-int(item["price-precision"])),
                metadata={
                    "baseCurrency": item.get("base-currency", ""),
                    "quoteCurrency": item.get("quote-currency", ""),
                },
            )
            if blacklist.matches(instrument.symbol, instrument.metadata):
                continue
            instruments.append(instrument)
        return instruments

    async def bootstrap_volume_reference(self, instrument: ExchangeInstrument) -> VolumeReference:
        params = {
            "symbol": instrument.symbol,
            "period": "5min",
            "size": str(self._detection.rolling_candle_count),
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.REST_BASE}/market/history/kline", params=params, timeout=20) as response:
                response.raise_for_status()
                payload = await response.json()
        reference = self._volume_reference_from_payload(
            payload,
            interval=self._detection.candle_interval,
            rolling_candle_count=self._detection.rolling_candle_count,
        )
        if reference is None:
            raise ValueError(f"No HTX candle data for {instrument.symbol}")
        return reference

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
            raise RuntimeError("No HTX spot instruments available after filtering.")
        print(f"[htx] discovered={len(instruments)}", flush=True)
        print(f"[htx] symbols={','.join(item.symbol for item in instruments[:5])}", flush=True)

        volume_references = await self._bootstrap_all_volumes(instruments)
        instruments = [instrument for instrument in instruments if instrument.symbol in volume_references]
        if not instruments:
            raise RuntimeError("No HTX spot instruments left after volume bootstrap.")
        print(f"[htx] bootstrapped_volumes={len(volume_references)}", flush=True)

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
                try:
                    references[instrument.symbol] = await self.bootstrap_volume_reference(instrument)
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
                    print(
                        f"[htx] skipped_volume symbol={instrument.symbol} reason={error}",
                        flush=True,
                    )

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

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self.WS_URL, heartbeat=None) as ws:
                for instrument in instruments:
                    await ws.send_json(
                        {
                            "sub": f"market.{instrument.symbol}.depth.step0",
                            "id": instrument.symbol,
                        }
                    )

                async for message in ws:
                    if message.type != aiohttp.WSMsgType.BINARY:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            payload = message.json()
                        elif message.type == aiohttp.WSMsgType.ERROR:
                            raise RuntimeError("HTX websocket error")
                        else:
                            continue
                    else:
                        payload = self._decode_binary_message(message.data)

                    if "ping" in payload:
                        await ws.send_json({"pong": payload["ping"]})
                        continue
                    if payload.get("status") == "ok" and "subbed" in payload:
                        continue
                    if "ch" not in payload or "tick" not in payload:
                        continue

                    channel = payload["ch"]
                    symbol = channel.split(".")[1]
                    tick = payload["tick"]
                    bids = [(float(price), float(size)) for price, size in tick["bids"]]
                    asks = [(float(price), float(size)) for price, size in tick["asks"]]
                    states[symbol].replace(bids, asks)
                    snapshot = states[symbol].to_snapshot(datetime.now(timezone.utc))
                    if snapshot is None:
                        continue
                    signals = await runtime.handle_snapshot(snapshot, volume_references[symbol])
                    if stop_after_snapshots is not None and runtime.stats.snapshots_processed >= stop_after_snapshots:
                        print(f"[htx] processed_snapshots={runtime.stats.snapshots_processed}", flush=True)
                        return
                    for signal in signals:
                        print(runtime.render_signal(signal), flush=True)

    @staticmethod
    def _decode_binary_message(data: bytes) -> dict:
        return json.loads(gzip.decompress(data).decode("utf-8"))

    @staticmethod
    def _volume_reference_from_payload(
        payload: dict,
        *,
        interval: str,
        rolling_candle_count: int,
    ) -> VolumeReference | None:
        raw_candles = payload.get("data")
        if not isinstance(raw_candles, list) or not raw_candles:
            return None
        candles = raw_candles[:rolling_candle_count]
        turnovers = [float(row["vol"]) for row in candles if row.get("vol") is not None]
        if not turnovers:
            return None
        average_turnover = sum(turnovers) / len(turnovers)
        return VolumeReference(
            avg_candle_notional=average_turnover,
            candle_count=len(turnovers),
            interval=interval,
        )
