from __future__ import annotations

import aiohttp

from density_screener.blacklist import BlacklistMatcher
from density_screener.exchanges.base import ExchangeInstrument
from density_screener.exchanges.kucoin_base import KuCoinAdapterBase
from density_screener.models import VolumeReference


class KuCoinFuturesAdapter(KuCoinAdapterBase):
    REST_BASE = "https://api-futures.kucoin.com"

    @property
    def name(self) -> str:
        return "kucoin_futures"

    @property
    def public_token_url(self) -> str:
        return f"{self.REST_BASE}/api/v1/bullet-public"

    async def discover_instruments(self, blacklist: BlacklistMatcher) -> list[ExchangeInstrument]:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.REST_BASE}/api/v1/contracts/active", timeout=20) as response:
                response.raise_for_status()
                payload = await response.json()
        instruments: list[ExchangeInstrument] = []
        for item in payload["data"]:
            if item.get("status") not in {"Open", None}:
                continue
            instrument = ExchangeInstrument(
                exchange=self.name,
                symbol=item["symbol"],
                market_type="futures",
                tick_size=float(item["tickSize"]),
                metadata={
                    "baseCurrency": item.get("baseCurrency", ""),
                    "quoteCurrency": item.get("quoteCurrency", ""),
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
        params = {
            "symbol": instrument.symbol,
            "granularity": "5",
        }
        payload = await self._get_json(
            f"{self.REST_BASE}/api/v1/kline/query",
            params=params,
            session=session,
        )
        candles = payload["data"][-self._detection.rolling_candle_count :]
        if not candles:
            raise ValueError(f"No KuCoin futures candles for {instrument.symbol}")
        turnovers = [float(row[6]) for row in candles]
        average_turnover = sum(turnovers) / max(len(turnovers), 1)
        return VolumeReference(
            avg_candle_notional=average_turnover,
            candle_count=len(turnovers),
            interval=self._detection.candle_interval,
        )

    def _topic_for(self, symbol: str) -> str:
        return f"/contractMarket/level2Depth50:{symbol}"
