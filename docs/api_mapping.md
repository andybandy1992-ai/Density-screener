# Exchange API Mapping

This file records the official API sources used for implementation planning.

## Bybit

- REST instruments: `GET /v5/market/instruments-info`
- REST klines: `GET /v5/market/kline`
- WS public endpoints:
  - spot: `wss://stream.bybit.com/v5/public/spot`
  - linear: `wss://stream.bybit.com/v5/public/linear`
- WS topics:
  - order book: `orderbook.{depth}.{symbol}`
  - kline: `kline.{interval}.{symbol}`

## Bitget

- REST spot symbols: `GET /api/v2/spot/public/symbols`
- REST spot candles: `GET /api/v2/spot/market/candles`
- REST futures candles: `GET /api/v2/mix/market/candles`
- WS public endpoint: `wss://ws.bitget.com/v2/ws/public`
- WS topics:
  - depth snapshot/increment: `books`, `books1`, `books5`, `books50`
  - spot kline: `candle5m`

## KuCoin

- Spot public token: `POST https://api.kucoin.com/api/v1/bullet-public`
- Futures public token: `POST https://api-futures.kucoin.com/api/v1/bullet-public`
- Spot symbols: `GET https://api.kucoin.com/api/v2/symbols`
- Spot candles: `GET https://api.kucoin.com/api/v1/market/candles?symbol={symbol}&type=5min`
- Futures contracts: `GET https://api-futures.kucoin.com/api/v1/contracts/active`
- Futures candles: `GET https://api-futures.kucoin.com/api/v1/kline/query?symbol={symbol}&granularity=5`
- Spot WS snapshot depth:
  - `/spotMarket/level2Depth50:{symbol}`
- Futures WS snapshot depth:
  - `/contractMarket/level2Depth50:{symbol}`
- WS connection shape:
  - `{instanceServer.endpoint}?token={token}&connectId={uuid}`

## Hyperliquid

- Info endpoint: `POST https://api.hyperliquid.xyz/info`
- WS endpoint: `wss://api.hyperliquid.xyz/ws`
- WS subscriptions:
  - `l2Book`
- Candle bootstrap:
  - `candleSnapshot`

## HTX

- REST base: `https://api.huobi.pro`
- WS depth endpoints:
  - normal feed: `wss://api.huobi.pro/ws`
  - MBP feed: `wss://api.huobi.pro/feed`
- Depth topics:
  - `market.$symbol.depth.$type`
  - `market.$symbol.mbp.$levels`

## Lighter

- Order book metadata: `GET https://mainnet.zklighter.elliot.ai/api/v1/orderBooks?market_id=255&filter=all`
- Candles: `GET https://mainnet.zklighter.elliot.ai/api/v1/candles`
- WS endpoint: `wss://mainnet.zklighter.elliot.ai/stream`
- WS read-only endpoint: `wss://mainnet.zklighter.elliot.ai/stream?readonly=true`
- WS channel:
  - `order_book/{MARKET_INDEX}`
- WS update shape:
  - `type = update/order_book`
  - initial subscribe returns a full snapshot, later messages are deltas
  - continuity can be checked with `begin_nonce -> nonce`

## Aster

- REST futures base: `https://fapi.asterdex.com`
- WS futures base: `wss://fstream.asterdex.com`
- Order book REST:
  - `GET /fapi/v1/depth`
- Klines REST:
  - `GET /fapi/v1/klines`

## Implementation note

Not every venue exposes the same mix of:

- full-book snapshots;
- partial-book snapshots;
- kline WS streams;
- efficient bulk symbol discovery.

Because of this, the core is exchange-agnostic, while each adapter can choose the safest venue-specific bootstrap strategy.
