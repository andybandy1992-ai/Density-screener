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
7. Set `TELEGRAM_CONTROL_USER_IDS` in `.env` if you want alerts to go to the group but controls to stay on your personal Telegram user.
8. Use `/panel` in Telegram after startup if you want to change global thresholds or the bot-managed blacklist without touching files.
9. Use `/health` in Telegram to get one status message for the whole service and every enabled exchange.

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

## Runtime state

The bot-managed settings are persisted in the runtime state file configured by `app.control_state_file`.

By default this is:

- `/opt/density-screener/state/runtime_controls.json`

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
