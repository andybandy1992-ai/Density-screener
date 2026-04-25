#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/density-screener}"
JOURNAL_VACUUM_TIME="${JOURNAL_VACUUM_TIME:-7d}"
JOURNAL_VACUUM_SIZE="${JOURNAL_VACUUM_SIZE:-200M}"

echo "[maintenance] started"

if command -v journalctl >/dev/null 2>&1; then
  journalctl --vacuum-time="$JOURNAL_VACUUM_TIME" --vacuum-size="$JOURNAL_VACUUM_SIZE"
fi

if [ -d "$APP_DIR" ]; then
  find "$APP_DIR" -type d -name "__pycache__" -prune -exec rm -rf {} +
  find "$APP_DIR" -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete
  find "$APP_DIR" -type d \( -name ".pytest_cache" -o -name ".mypy_cache" -o -name ".ruff_cache" \) -prune -exec rm -rf {} +
  find "$APP_DIR" -type d -path "$APP_DIR/.npm-cache" -prune -exec rm -rf {} +
fi

df -h / || true
du -sh /var/log/journal "$APP_DIR/state" 2>/dev/null || true

echo "[maintenance] finished"
