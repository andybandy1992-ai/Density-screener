from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import datetime, timezone
import math
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
    AGGREGATION_DISTANCE_PCT = 0.02

    def __init__(
        self,
        detection: DetectionConfig,
        *,
        subscription_batch_size: int = 20,
        bootstrap_delay_seconds: float = 0.2,
        bootstrap_retry_attempts: int = 5,
    ) -> None:
        self._detection = detection
        self._subscription_batch_size = subscription_batch_size
        self._bootstrap_delay_seconds = bootstrap_delay_seconds
        self._bootstrap_retry_attempts = bootstrap_retry_attempts

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

    async def bootstrap_volume_reference(
        self,
        instrument: ExchangeInstrument,
        *,
        session: aiohttp.ClientSession | None = None,
    ) -> VolumeReference:
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
            },
            session=session,
        )
        return self._volume_reference_from_candles(
            payload,
            interval=self._detection.candle_interval,
            rolling_candle_count=self._detection.rolling_candle_count,
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
        instruments = [instrument for instrument in instruments if instrument.symbol in volume_references]
        if not instruments:
            raise RuntimeError("No Hyperliquid instruments left after volume bootstrap.")
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
        references: dict[str, VolumeReference] = {}
        async with aiohttp.ClientSession() as session:
            for index, instrument in enumerate(instruments):
                if index:
                    await asyncio.sleep(self._bootstrap_delay_seconds)
                try:
                    references[instrument.symbol] = await self.bootstrap_volume_reference(
                        instrument,
                        session=session,
                    )
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
                    reason = str(error) or error.__class__.__name__
                    print(
                        f"[hyperliquid] skipped_volume symbol={instrument.symbol} reason={reason}",
                        flush=True,
                    )
        return references

    async def _run_batch(
        self,
        runtime: ScreenerRuntime,
        instruments: list[ExchangeInstrument],
        volume_references: dict[str, VolumeReference],
        *,
        stop_after_snapshots: int | None = None,
    ) -> None:
        async with aiohttp.ClientSession() as session:
            while True:
                states = {
                    instrument.symbol: OrderBookState(
                        exchange=self.name,
                        symbol=instrument.symbol,
                        market_type="futures",
                        tick_size=None,
                    )
                    for instrument in instruments
                }
                try:
                    async with session.ws_connect(self.WS_URL, heartbeat=None) as ws:
                        print(f"[hyperliquid] ws_connected batch={len(instruments)}", flush=True)
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
                            raw_bids = [(float(level["px"]), float(level["sz"])) for level in bid_levels]
                            raw_asks = [(float(level["px"]), float(level["sz"])) for level in ask_levels]
                            if not raw_bids or not raw_asks:
                                continue
                            mid_price = (raw_bids[0][0] + raw_asks[0][0]) / 2
                            bids = self._aggregate_levels(raw_bids, side="bid", mid_price=mid_price)
                            asks = self._aggregate_levels(raw_asks, side="ask", mid_price=mid_price)
                            states[symbol].replace(bids, asks)
                            snapshot = states[symbol].to_snapshot(datetime.now(timezone.utc))
                            if snapshot is None:
                                continue
                            signals = await runtime.handle_snapshot(snapshot, volume_references[symbol])
                            if (
                                stop_after_snapshots is not None
                                and runtime.stats.snapshots_processed >= stop_after_snapshots
                            ):
                                print(
                                    f"[hyperliquid] processed_snapshots={runtime.stats.snapshots_processed}",
                                    flush=True,
                                )
                                return
                            for signal in signals:
                                print(runtime.render_signal(signal), flush=True)

                    raise RuntimeError("Hyperliquid websocket closed unexpectedly")
                except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as error:
                    print(
                        f"[hyperliquid] reconnecting_batch reason={error.__class__.__name__}: {error}",
                        flush=True,
                    )
                    await asyncio.sleep(1)
                    continue

    async def _post_info(
        self,
        payload: dict,
        *,
        session: aiohttp.ClientSession | None = None,
    ) -> dict | list:
        owns_session = session is None
        client = session or aiohttp.ClientSession()
        backoff_seconds = 1.0
        try:
            for attempt in range(1, self._bootstrap_retry_attempts + 1):
                async with client.post(self.INFO_URL, json=payload, timeout=20) as response:
                    if response.status == 429 and attempt < self._bootstrap_retry_attempts:
                        await asyncio.sleep(backoff_seconds)
                        backoff_seconds = min(backoff_seconds * 2, 8.0)
                        continue
                    response.raise_for_status()
                    return await response.json()
        finally:
            if owns_session:
                await client.close()
        raise RuntimeError("Hyperliquid request retries exhausted.")

    @staticmethod
    def _volume_reference_from_candles(
        payload: list[dict],
        *,
        interval: str,
        rolling_candle_count: int,
    ) -> VolumeReference:
        candles = payload[-rolling_candle_count:]
        notionals = [float(row["v"]) * float(row["c"]) for row in candles]
        average_notional = sum(notionals) / max(len(notionals), 1)
        return VolumeReference(
            avg_candle_notional=average_notional,
            candle_count=len(notionals),
            interval=interval,
        )

    @classmethod
    def _aggregate_levels(
        cls,
        levels: list[tuple[float, float]],
        *,
        side: str,
        mid_price: float,
    ) -> list[tuple[float, float]]:
        bucket_size = cls._nice_bucket_size(mid_price * cls.AGGREGATION_DISTANCE_PCT / 100)
        buckets: dict[int, float] = {}
        for price, quantity in levels:
            bucket_id = math.floor(price / bucket_size)
            buckets[bucket_id] = buckets.get(bucket_id, 0.0) + price * quantity

        aggregated: list[tuple[float, float]] = []
        for bucket_id, notional in buckets.items():
            if side == "bid":
                bucket_price = (bucket_id + 1) * bucket_size
            else:
                bucket_price = bucket_id * bucket_size
            if bucket_price <= 0:
                continue
            aggregated.append((bucket_price, notional / bucket_price))

        reverse = side == "bid"
        return sorted(aggregated, key=lambda item: item[0], reverse=reverse)

    @staticmethod
    def _nice_bucket_size(raw_size: float) -> float:
        if raw_size <= 0:
            return 1e-12
        magnitude = 10 ** math.floor(math.log10(raw_size))
        normalized = raw_size / magnitude
        if normalized <= 1:
            nice = 1
        elif normalized <= 2:
            nice = 2
        elif normalized <= 5:
            nice = 5
        else:
            nice = 10
        return nice * magnitude
