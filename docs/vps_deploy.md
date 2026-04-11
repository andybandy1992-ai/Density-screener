# VPS Deploy

## Recommended layout

- repo path: `/opt/density-screener`
- virtualenv: `/opt/density-screener/.venv`
- service manager: `systemd`

## First deploy

1. Copy the project to the VPS.
2. Create a virtual environment:
   - `python3 -m venv .venv`
3. Install dependencies:
   - `.venv/bin/pip install -r requirements.txt`
4. Fill `.env` from `deploy/systemd/density-screener.env.example`.
5. Edit `config/app.toml`.
6. Edit `config/blacklist.txt` with markets or coins you want to skip.

## Changing thresholds later

You can change the global minimum filters any time:

- in `config/app.toml`:
  - `spot_min_notional_usd`
  - `futures_min_notional_usd`
- or in `.env`:
  - `SPOT_MIN_NOTIONAL_USD`
  - `FUTURES_MIN_NOTIONAL_USD`

After changing them, restart the service:

- `sudo systemctl restart density-screener`

## Blacklist rules

- `BTC` blocks all BTC-based instruments.
- `symbol:BTCUSDT` blocks only one exact market.
- `pattern:*1000*` blocks wildcard symbol groups.

## Smoke checks before daemon mode

- `PYTHONPATH=src .venv/bin/python -m density_screener.cli doctor`
- `PYTHONPATH=src .venv/bin/python -m density_screener.cli run-enabled --symbol-limit 1 --max-snapshots 1`
- `PYTHONPATH=src .venv/bin/python -m density_screener.cli test-telegram --text "Density Screener VPS test"`

## systemd

1. Copy `deploy/systemd/density-screener.service.example` to `/etc/systemd/system/density-screener.service`.
2. Adjust `User`, `WorkingDirectory`, and `ExecStart`.
3. Reload systemd:
   - `sudo systemctl daemon-reload`
4. Enable autostart:
   - `sudo systemctl enable density-screener`
5. Start the service:
   - `sudo systemctl start density-screener`

## Useful commands

- `sudo systemctl status density-screener`
- `sudo journalctl -u density-screener -f`
- `sudo systemctl restart density-screener`
