# Density Screener

Real-time density screener for crypto exchanges with Telegram alerts.

## What this project does

- watches order books in real time;
- finds large resting sizes in the book;
- compares them against rolling 14 x 5m average traded notional;
- filters out market-maker-like symmetric liquidity;
- sends a single Telegram alert per symbol + side + price level.

## Current scope

The project is designed around:

- spot and linear futures;
- per-exchange settings;
- whole-market scan with blacklist support;
- VPS deployment.

## Working assumptions

These two values were ambiguous in the initial interview, so they are configurable and currently default to:

- futures minimum density notional: `100_000 USD`;
- scan window: `5%` from `mid-price`.

## Planned exchange coverage

- Bitget Spot
- Bybit Spot
- KuCoin Spot
- KuCoin Futures
- Hyperliquid
- Aster
- Lighter
- HTX

## Development flow

After each module change we run local verification:

- unit tests;
- import/compile checks;
- a lightweight debug command for the module or subsystem.

## Quick start

1. Create and edit `config/app.toml`.
2. Install dependencies from `requirements.txt`.
3. Run `python -m density_screener doctor`.
4. Run one of the live commands from `python -m density_screener.cli`.

## Threshold tuning

You can change the global minimum density filters at any time without touching code:

- in `config/app.toml`:
  - `spot_min_notional_usd = 50000`
  - `futures_min_notional_usd = 100000`
- or via `.env` / environment variables:
  - `SPOT_MIN_NOTIONAL_USD=50000`
  - `FUTURES_MIN_NOTIONAL_USD=100000`

The `doctor` command prints the active values after all overrides are applied.

## Telegram control panel

When the live service is running with Telegram enabled, open the bot panel by sending `/panel` from an authorized Telegram chat or user.

Alerts always go to `TELEGRAM_CHAT_ID`, while bot controls can be restricted to one or more personal Telegram users via `TELEGRAM_CONTROL_USER_IDS`.

From the panel you can:

- change the global spot minimum threshold;
- change the global futures minimum threshold;
- set a minimum threshold override for one specific exchange;
- add a bot-managed blacklist rule;
- remove a bot-managed blacklist rule;
- view the current bot-managed blacklist.
- request a `/health` report with system and exchange status.

Global controls are shared across all enabled exchanges, while exchange-specific overrides are applied only to the chosen venue. Everything is persisted in the runtime state file.

## Health checks

Use `/health` in Telegram to get a live status report from the running process.

The report includes:

- service uptime;
- Telegram alert/control status;
- runtime state file path;
- one line per exchange with status, snapshot count, signal count, and last snapshot age.

## Useful commands

- `python -m density_screener.cli doctor`
- `python -m density_screener.cli debug-simulate`
- `python -m density_screener.cli run-enabled`
- `python -m density_screener.cli run-enabled --exchanges lighter --symbol-limit 1 --max-snapshots 1`
- `python -m density_screener.cli run-bitget-spot --symbol-limit 5`
- `python -m density_screener.cli run-bitget-spot --symbol-limit 1 --max-snapshots 3`
- `python -m density_screener.cli run-kucoin-spot --symbol-limit 1 --max-snapshots 3`
- `python -m density_screener.cli run-kucoin-futures --symbol-limit 1 --max-snapshots 3`
- `python -m density_screener.cli run-htx-spot --symbol-limit 1 --max-snapshots 3`
- `python -m density_screener.cli run-aster-futures --symbol-limit 1 --max-snapshots 3`
- `python -m density_screener.cli run-hyperliquid --symbol-limit 1 --max-snapshots 3`
- `python -m density_screener.cli run-lighter --symbol-limit 1 --max-snapshots 3`
- `python -m density_screener.cli run-bybit-spot --symbol-limit 1 --max-snapshots 3`
- `python -m density_screener.cli test-telegram --text "Density Screener test"`

## Blacklist

You can exclude markets in two places:

- inline in `config/app.toml` via `[market].global_blacklist`
- line-by-line in `config/blacklist.txt`
- dynamically from Telegram via the bot-managed runtime blacklist

Supported rule shapes:

- `BTC` blocks the whole coin across markets where the base asset is BTC
- `symbol:BTCUSDT` blocks only one exact market
- `pattern:*1000*` blocks wildcard groups

The default blacklist file already includes precious metals plus the currently exposed U.S. stock / ETF tickers that appear on the supported venues.

## Current live status

- `Bitget Spot`: live smoke verified in this environment
- `KuCoin Spot`: live smoke verified in this environment
- `KuCoin Futures`: live smoke verified in this environment
- `HTX Spot`: live smoke verified in this environment
- `Aster Futures`: live smoke verified in this environment
- `Hyperliquid`: live smoke verified in this environment
- `Lighter`: live smoke verified in read-only websocket mode; adapter covers active perps and stable-quoted spot
- `Bybit Spot`: adapter implemented, current environment receives `403` from public REST
- Remaining exchanges: planned in the shared adapter architecture

## Supervisor mode

Use `run-enabled` when you want one VPS process to run multiple enabled exchanges from `config/app.toml`.

Important behavior:

- each exchange keeps its own detector/runtime state;
- the supervisor can run only a chosen subset with `--exchanges`;
- if one exchange fails during startup, the others keep running.

## VPS

The repo now includes a ready-to-adapt `systemd` unit example and a short VPS setup note in `docs/vps_deploy.md`.

## GitHub publication

The repo is prepared so secrets stay local:

- `.env` is ignored by git;
- `.env.example` shows the required runtime variables;
- `config/app.toml.example` can be used as the public template.

Publication steps are documented in `docs/github_publish.md`.

## Important note about spot markets

The current spot logic safely interprets USD thresholds only for stable-quoted pairs such as `USDT`, `USDC`, `USD`, `FDUSD`, `BUSD`.

That restriction is intentional for now:

- it keeps the `50,000 USD` filter mathematically correct;
- it avoids false sizing on cross pairs like `ETH/BTC`.

## Project layout

- `src/density_screener/` - application package
- `tests/` - unit tests
- `docs/` - design notes and API mapping
- `config/` - runtime configuration
