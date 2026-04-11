# Project Brief

## User requirements

- Exchanges:
  - Bitget Spot
  - Bybit Spot
  - KuCoin Spot
  - KuCoin Futures
  - Hyperliquid
  - Aster
  - Lighter
  - HTX
- Market scope:
  - if exchange name has no suffix, both spot and futures are relevant where available;
  - the screener must support whole-market scan;
  - a blacklist must be supported.
- Exchange settings:
  - separate settings per exchange are required.
- Density definition:
  - level notional must be at least `5x` bigger than the average traded notional of the last `14` completed `5m` candles;
  - spot floor: `50_000 USD`;
  - futures floor: `100_000 USD`.
- Distance rule:
  - assumed scan window is `5% from mid-price`.
- Persistence rule:
  - the size must stay in the book for at least `5` seconds.
- Sides:
  - bids and asks.
- Repeat alerts:
  - disabled for the same price level.
- Anti market-maker priority:
  - avoid symmetric liquidity, even if sizes are only approximately equal.
- Missed signal tolerance:
  - false negatives are preferable to false positives only if necessary, but the user explicitly prefers not to miss good densities.
- Strict filtering mode:
  - enabled.
- Notification target:
  - Telegram group or channel.
- Notification body:
  - instrument name;
  - price level;
  - how long the level has been resting;
  - how many times it exceeds the average traded notional.
- Alert deduplication:
  - not more than one alert per same price level.
- Runtime:
  - VPS.
- Delivery process:
  - prepare the project for GitHub publication;
  - verify each module after implementation.

## Derived architecture decisions

- One shared detection engine.
- One adapter module per exchange or venue family.
- One config section per exchange.
- One notifier module for Telegram.
- One state store for rolling candles, active candidates, and dedupe memory.

## Initial anti-MM heuristic

A level is considered market-maker-like when the opposite side has a similar notional and similar distance from mid-price within configured tolerances.

Default draft tolerances:

- opposite side notional similarity: within `20%`;
- mirrored distance similarity: within `15%`;
- first `1` tick near top of book can be optionally suppressed per exchange;
- minimum lifetime before alert: `5` seconds.

## Open assumptions to revisit later

- Whether the `5%` window should be narrower for very illiquid markets.
- Whether Aster should be split into spot and perpetual profiles in config by default.
