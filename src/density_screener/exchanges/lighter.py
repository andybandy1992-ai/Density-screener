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


class _ResyncRequired(RuntimeError):
    pass


class LighterAdapter(ExchangeAdapter):
    REST_BASE = "https://mainnet.zklighter.elliot.ai/api/v1"
    WS_URL = "wss://mainnet.zklighter.elliot.ai/stream?readonly=true"
    STABLE_QUOTES = {"USD", "USDC", "USDT", "FDUSD", "BUSD"}

    def __init__(self, detection: DetectionConfig, *, subscription_batch_size: int = 10) -> None:
        self._detection = detection
        self._subscription_batch_size = subscription_batch_size

    @property
    def name(self) -> str:
        return "lighter"

    async def discover_instruments(self, blacklist: BlacklistMatcher) -> list[ExchangeInstrument]:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.REST_BASE}/orderBooks",
                params={"market_id": "255", "filter": "all"},
                timeout=20,
            ) as response:
                response.raise_for_status()
                payload = await response.json()

        instruments: list[ExchangeInstrument] = []
        for item in payload["order_books"]:
            if item.get("status") != "active":
                continue

            raw_market_type = item.get("market_type", "")
            symbol = item["symbol"]
            if raw_market_type == "spot" and not self._is_supported_spot_symbol(symbol):
                continue
            if raw_market_type not in {"spot", "perp"}:
                continue

            instrument = ExchangeInstrument(
                exchange=self.name,
                symbol=symbol,
                market_type="spot" if raw_market_type == "spot" else "futures",
                tick_size=self._tick_size_from_decimals(int(item.get("supported_price_decimals", 0))),
                metadata={
                    "baseAsset": self._base_asset_from_symbol(symbol),
                    "market_id": int(item["market_id"]),
                    "raw_market_type": raw_market_type,
                },
            )
            if blacklist.matches(instrument.symbol, instrument.metadata):
                continue
            instruments.append(instrument)
        return instruments

    async def bootstrap_volume_reference(self, instrument: ExchangeInstrument) -> VolumeReference:
        market_id = int(instrument.metadata["market_id"])
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - self._detection.rolling_candle_count * 5 * 60 * 1000
        params = {
            "market_id": str(market_id),
            "resolution": "5m",
            "start_timestamp": str(start_ms),
            "end_timestamp": str(end_ms),
            "count_back": str(self._detection.rolling_candle_count),
            "set_timestamp_to_end": "true",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.REST_BASE}/candles", params=params, timeout=20) as response:
                response.raise_for_status()
                payload = await response.json()

        candles = payload["c"][-self._detection.rolling_candle_count :]
        average_notional = self._average_notional_from_candles(candles)
        return VolumeReference(
            avg_candle_notional=average_notional,
            candle_count=len(candles),
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
            raise RuntimeError("No Lighter instruments available after filtering.")
        print(f"[lighter] discovered={len(instruments)}", flush=True)
        print(f"[lighter] symbols={','.join(item.symbol for item in instruments[:5])}", flush=True)

        volume_references = await self._bootstrap_all_volumes(instruments)
        print(f"[lighter] bootstrapped_volumes={len(volume_references)}", flush=True)

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
        instruments_by_market_id = {
            int(instrument.metadata["market_id"]): instrument for instrument in instruments
        }

        async with aiohttp.ClientSession() as session:
            while True:
                states = {
                    market_id: OrderBookState(
                        exchange=self.name,
                        symbol=instrument.symbol,
                        market_type=instrument.market_type,
                        tick_size=instrument.tick_size,
                    )
                    for market_id, instrument in instruments_by_market_id.items()
                }
                last_nonces: dict[int, int] = {}
                try:
                    async with session.ws_connect(self.WS_URL, heartbeat=30) as ws:
                        for market_id in instruments_by_market_id:
                            await ws.send_json(
                                {
                                    "type": "subscribe",
                                    "channel": f"order_book/{market_id}",
                                }
                            )

                        async for message in ws:
                            if message.type != aiohttp.WSMsgType.TEXT:
                                if message.type == aiohttp.WSMsgType.ERROR:
                                    raise RuntimeError("Lighter websocket error")
                                continue

                            payload = message.json()
                            if payload.get("type") == "connected":
                                continue
                            if payload.get("type") != "update/order_book":
                                continue

                            market_id = self._extract_market_id(payload.get("channel", ""))
                            if market_id is None or market_id not in instruments_by_market_id:
                                continue

                            instrument = instruments_by_market_id[market_id]
                            book = payload["order_book"]
                            if int(book.get("code", 0)) != 0:
                                continue

                            bids = self._parse_side(book.get("bids", []))
                            asks = self._parse_side(book.get("asks", []))
                            nonce = int(book["nonce"])
                            previous_nonce = last_nonces.get(market_id)

                            if previous_nonce is None:
                                states[market_id].replace(bids, asks)
                            else:
                                begin_nonce = int(book["begin_nonce"])
                                if begin_nonce != previous_nonce:
                                    raise _ResyncRequired(
                                        f"market_id={market_id} begin_nonce={begin_nonce} previous_nonce={previous_nonce}"
                                    )
                                states[market_id].apply_delta(bids, asks)

                            last_nonces[market_id] = nonce
                            snapshot = states[market_id].to_snapshot(datetime.now(timezone.utc))
                            if snapshot is None:
                                continue
                            signals = await runtime.handle_snapshot(
                                snapshot,
                                volume_references[instrument.symbol],
                            )
                            if (
                                stop_after_snapshots is not None
                                and runtime.stats.snapshots_processed >= stop_after_snapshots
                            ):
                                print(
                                    f"[lighter] processed_snapshots={runtime.stats.snapshots_processed}",
                                    flush=True,
                                )
                                return
                            for signal in signals:
                                print(runtime.render_signal(signal), flush=True)

                    raise RuntimeError("Lighter websocket closed unexpectedly")
                except _ResyncRequired as error:
                    print(f"[lighter] reconnecting_batch reason={error}", flush=True)
                    await asyncio.sleep(1)
                    continue
                except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as error:
                    print(
                        f"[lighter] reconnecting_batch reason={error.__class__.__name__}: {error}",
                        flush=True,
                    )
                    await asyncio.sleep(1)
                    continue

    @classmethod
    def _is_supported_spot_symbol(cls, symbol: str) -> bool:
        if "/" not in symbol:
            return False
        _, quote = symbol.rsplit("/", 1)
        return quote.upper() in cls.STABLE_QUOTES

    @staticmethod
    def _base_asset_from_symbol(symbol: str) -> str:
        if "/" in symbol:
            return symbol.split("/", 1)[0].upper()
        return symbol.upper()

    @staticmethod
    def _tick_size_from_decimals(decimals: int) -> float:
        if decimals <= 0:
            return 1.0
        return 10 ** (-decimals)

    @staticmethod
    def _parse_side(levels: list[dict[str, str]]) -> list[tuple[float, float]]:
        return [(float(level["price"]), float(level["size"])) for level in levels]

    @staticmethod
    def _extract_market_id(channel: str) -> int | None:
        if ":" not in channel:
            return None
        _, raw_market_id = channel.split(":", 1)
        if not raw_market_id.isdigit():
            return None
        return int(raw_market_id)

    @staticmethod
    def _average_notional_from_candles(candles: list[dict]) -> float:
        if not candles:
            return 0.0
        notionals = [
            float(candle["V"]) if candle.get("V") is not None else float(candle["v"]) * float(candle["c"])
            for candle in candles
        ]
        return sum(notionals) / len(notionals)
