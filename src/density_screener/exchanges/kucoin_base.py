from __future__ import annotations

import asyncio
from collections.abc import Iterable
from contextlib import suppress
from datetime import datetime, timezone
import uuid

import aiohttp

from density_screener.blacklist import ensure_blacklist_matcher
from density_screener.exchanges.base import ExchangeAdapter, ExchangeInstrument, OrderBookState
from density_screener.models import VolumeReference
from density_screener.runtime import ScreenerRuntime
from density_screener.settings import DetectionConfig


class KuCoinAdapterBase(ExchangeAdapter):
    STABLE_QUOTES = {"USDT", "USDC", "USD", "FDUSD", "BUSD"}

    def __init__(
        self,
        detection: DetectionConfig,
        *,
        subscription_batch_size: int = 25,
        bootstrap_delay_seconds: float = 0.2,
        bootstrap_retry_attempts: int = 5,
    ) -> None:
        self._detection = detection
        self._subscription_batch_size = subscription_batch_size
        self._bootstrap_delay_seconds = bootstrap_delay_seconds
        self._bootstrap_retry_attempts = bootstrap_retry_attempts

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
            raise RuntimeError(f"No {self.name} instruments available after filtering.")
        print(f"[{self.name}] discovered={len(instruments)}", flush=True)
        print(f"[{self.name}] symbols={','.join(item.symbol for item in instruments[:5])}", flush=True)

        volume_references = await self._bootstrap_all_volumes(instruments)
        instruments = [instrument for instrument in instruments if instrument.symbol in volume_references]
        if not instruments:
            raise RuntimeError(f"No {self.name} instruments left after volume bootstrap.")
        print(f"[{self.name}] bootstrapped_volumes={len(volume_references)}", flush=True)

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
                    print(
                        f"[{self.name}] skipped_volume symbol={instrument.symbol} reason={error}",
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
        token_payload = await self._get_public_token_payload()
        server = token_payload["instanceServers"][0]
        connect_id = str(uuid.uuid4())
        ws_url = f"{server['endpoint']}?token={token_payload['token']}&connectId={connect_id}"
        states = {
            instrument.symbol: OrderBookState(
                exchange=self.name,
                symbol=instrument.symbol,
                market_type=instrument.market_type,
                tick_size=instrument.tick_size,
            )
            for instrument in instruments
        }

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(ws_url, heartbeat=None) as ws:
                welcome = await ws.receive(timeout=10)
                print(f"[{self.name}] welcome={welcome.data}", flush=True)
                heartbeat_task = asyncio.create_task(
                    self._heartbeat(ws, int(server["pingInterval"]))
                )
                try:
                    for instrument in instruments:
                        await ws.send_json(
                            {
                                "id": connect_id,
                                "type": "subscribe",
                                "topic": self._topic_for(instrument.symbol),
                                "response": True,
                            }
                        )

                    async for message in ws:
                        if message.type != aiohttp.WSMsgType.TEXT:
                            if message.type == aiohttp.WSMsgType.ERROR:
                                raise RuntimeError(f"{self.name} websocket error")
                            continue
                        payload = message.json()
                        if payload.get("type") in {"ack", "welcome", "pong"}:
                            continue
                        if payload.get("type") == "error":
                            raise RuntimeError(f"{self.name} subscription error: {payload}")
                        if payload.get("subject") != "level2":
                            continue

                        symbol = self._symbol_from_topic(payload["topic"])
                        state = states[symbol]
                        book = payload["data"]
                        bids = [(float(price), float(size)) for price, size in book["bids"]]
                        asks = [(float(price), float(size)) for price, size in book["asks"]]
                        state.replace(bids, asks)
                        snapshot = state.to_snapshot(datetime.now(timezone.utc))
                        if snapshot is None:
                            continue
                        signals = await runtime.handle_snapshot(snapshot, volume_references[symbol])
                        if stop_after_snapshots is not None and runtime.stats.snapshots_processed >= stop_after_snapshots:
                            print(f"[{self.name}] processed_snapshots={runtime.stats.snapshots_processed}", flush=True)
                            return
                        for signal in signals:
                            print(runtime.render_signal(signal), flush=True)
                finally:
                    heartbeat_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await heartbeat_task

    async def _heartbeat(self, ws: aiohttp.ClientWebSocketResponse, ping_interval_ms: int) -> None:
        interval = max(1.0, ping_interval_ms / 1000 / 2)
        while True:
            await asyncio.sleep(interval)
            await ws.send_json({"id": str(uuid.uuid4()), "type": "ping"})

    def _symbol_from_topic(self, topic: str) -> str:
        return topic.rsplit(":", 1)[1]

    async def _get_public_token_payload(self) -> dict:
        async with aiohttp.ClientSession() as session:
            async with session.post(self.public_token_url, timeout=20) as response:
                response.raise_for_status()
                payload = await response.json()
        return payload["data"]

    async def _get_json(
        self,
        url: str,
        *,
        params: dict[str, str],
        session: aiohttp.ClientSession | None = None,
    ) -> dict:
        owns_session = session is None
        client = session or aiohttp.ClientSession()
        backoff_seconds = 1.0
        try:
            for attempt in range(1, self._bootstrap_retry_attempts + 1):
                async with client.get(url, params=params, timeout=20) as response:
                    if response.status == 429 and attempt < self._bootstrap_retry_attempts:
                        await asyncio.sleep(backoff_seconds)
                        backoff_seconds = min(backoff_seconds * 2, 8.0)
                        continue
                    response.raise_for_status()
                    return await response.json()
        finally:
            if owns_session:
                await client.close()
        raise RuntimeError(f"{self.name} request retries exhausted.")

    @property
    def public_token_url(self) -> str:
        raise NotImplementedError

    def _topic_for(self, symbol: str) -> str:
        raise NotImplementedError
