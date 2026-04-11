# Validation Notes

## Local checks

- `python -m unittest discover -s tests -v`
- `python -m density_screener.cli doctor`
- `python -m density_screener.cli debug-simulate`

Current local result:

- `27` unit tests pass;
- detector simulation emits one signal after the configured 5-second lifetime;
- config doctor loads successfully and prints the active spot/futures thresholds;
- env overrides for `SPOT_MIN_NOTIONAL_USD` and `FUTURES_MIN_NOTIONAL_USD` were verified locally.

## Live smoke checks

### Bitget Spot

Validated from the current environment with:

- symbol discovery;
- candle bootstrap;
- websocket connect;
- order book snapshots.

Observed successful run:

- discovered `1` symbol in smoke mode;
- bootstrapped `1` volume reference;
- connected to websocket;
- processed `3` live order-book snapshots.

### KuCoin Spot

Validated from the current environment with:

- public token bootstrap;
- symbol discovery;
- 5-minute candle bootstrap;
- websocket connect;
- order book snapshots.

Observed successful run:

- discovered `1` symbol in smoke mode;
- bootstrapped `1` volume reference;
- received websocket `welcome`;
- processed `1` live order-book snapshot.

### KuCoin Futures

Validated from the current environment with:

- public token bootstrap;
- contracts discovery;
- 5-minute candle bootstrap;
- websocket connect;
- order book snapshots.

Observed successful run:

- discovered `1` contract in smoke mode;
- bootstrapped `1` volume reference;
- received websocket `welcome`;
- processed `1` live order-book snapshot.

### HTX Spot

Validated from the current environment with:

- symbol discovery;
- 5-minute candle bootstrap;
- websocket connect;
- gzip order-book message decoding.

Observed successful run:

- discovered `1` symbol in smoke mode;
- bootstrapped `1` volume reference;
- processed `1` live order-book snapshot.

### Hyperliquid

Validated from the current environment with:

- market discovery;
- 5-minute candle bootstrap;
- websocket connect;
- `l2Book` snapshot handling.

Observed successful run:

- discovered `1` market in smoke mode;
- bootstrapped `1` volume reference;
- processed `1` live order-book snapshot.

### Aster Futures

Validated from the current environment with:

- contracts discovery;
- 5-minute candle bootstrap;
- websocket connect;
- depth20 snapshot handling.

Observed successful run:

- discovered `1` contract in smoke mode;
- bootstrapped `1` volume reference;
- processed `1` live order-book snapshot.

### Lighter

Validated from the current environment with:

- order book metadata discovery;
- 5-minute candle bootstrap;
- websocket connect in read-only mode;
- initial snapshot plus incremental order-book delta handling.

Observed successful run:

- discovered `1` market in smoke mode;
- bootstrapped `1` volume reference;
- processed `1` live order-book snapshot.

### Bybit Spot

The adapter code exists, but the current environment receives `403 Forbidden` from the public REST market endpoint.

This suggests one of:

- regional restriction on the current IP;
- edge or bot protection on the current host;
- a need for an alternative official Bybit regional hostname in deployment.

### Supervisor mode

Validated from the current environment with:

- `run-enabled --exchanges lighter --symbol-limit 1 --max-snapshots 1`
- `run-enabled --exchanges bybit_spot,lighter --symbol-limit 1 --max-snapshots 1`

Observed successful behavior:

- the supervisor starts the selected exchanges from config;
- `Lighter` completed a smoke run under the supervisor;
- `Bybit Spot` failed with `403`, while `Lighter` continued and finished normally.
- `Lighter` also completed a fresh post-change smoke run after threshold configurability updates.

## Operational assumptions

- spot USD thresholds are currently safe only for stable-quoted spot pairs;
- futures minimum notional is currently set to `100,000 USD`;
- scan radius is currently interpreted as `5% from mid-price`.
