from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any
import tomllib

from density_screener.blacklist import BlacklistMatcher
from density_screener.models import MarketType


@dataclass(slots=True, frozen=True)
class DetectionConfig:
    volume_multiplier: float
    rolling_candle_count: int
    candle_interval: str
    spot_min_notional_usd: float
    futures_min_notional_usd: float
    price_window_pct: float
    min_lifetime_seconds: float
    same_price_cooldown_seconds: float
    symmetry_notional_tolerance_pct: float
    symmetry_distance_tolerance_pct: float
    suppress_top_ticks: int

    def min_notional_for(self, market_type: MarketType) -> float:
        if market_type == "spot":
            return self.spot_min_notional_usd
        return self.futures_min_notional_usd


@dataclass(slots=True, frozen=True)
class TelegramConfig:
    enabled: bool
    bot_token: str
    chat_id: str
    control_user_ids: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class ExchangeConfig:
    enabled: bool
    market_type: str


@dataclass(slots=True, frozen=True)
class AppConfig:
    timezone: str
    strict_mode: bool
    control_state_file: str
    control_state_path: Path
    detection: DetectionConfig
    telegram: TelegramConfig
    global_blacklist: tuple[str, ...]
    blacklist_file: str
    blacklist: BlacklistMatcher
    exchanges: dict[str, ExchangeConfig]


def load_config(path: str | Path) -> AppConfig:
    file_path = Path(path)
    raw = _read_toml(file_path)
    env = _read_env_overlay(file_path)
    app_raw = raw.get("app", {})
    detection_raw = raw.get("detection", {})
    telegram_raw = raw.get("telegram", {})
    market_raw = raw.get("market", {})
    exchanges_raw = raw.get("exchanges", {})
    control_state_file = str(app_raw.get("control_state_file", "../state/runtime_controls.json"))
    control_state_path = _resolve_optional_path(file_path, control_state_file)
    if control_state_path is None:
        control_state_path = file_path.parent.parent / "state" / "runtime_controls.json"

    detection = DetectionConfig(
        volume_multiplier=float(detection_raw["volume_multiplier"]),
        rolling_candle_count=int(detection_raw["rolling_candle_count"]),
        candle_interval=str(detection_raw["candle_interval"]),
        spot_min_notional_usd=_parse_float(
            env.get("SPOT_MIN_NOTIONAL_USD"),
            float(detection_raw["spot_min_notional_usd"]),
        ),
        futures_min_notional_usd=_parse_float(
            env.get("FUTURES_MIN_NOTIONAL_USD"),
            float(detection_raw["futures_min_notional_usd"]),
        ),
        price_window_pct=float(detection_raw["price_window_pct"]),
        min_lifetime_seconds=float(detection_raw["min_lifetime_seconds"]),
        same_price_cooldown_seconds=float(detection_raw["same_price_cooldown_seconds"]),
        symmetry_notional_tolerance_pct=float(detection_raw["symmetry_notional_tolerance_pct"]),
        symmetry_distance_tolerance_pct=float(detection_raw["symmetry_distance_tolerance_pct"]),
        suppress_top_ticks=int(detection_raw.get("suppress_top_ticks", 0)),
    )

    telegram = TelegramConfig(
        enabled=_parse_bool(env.get("TELEGRAM_ENABLED"), bool(telegram_raw.get("enabled", False))),
        bot_token=str(env.get("TELEGRAM_BOT_TOKEN", telegram_raw.get("bot_token", ""))),
        chat_id=str(env.get("TELEGRAM_CHAT_ID", telegram_raw.get("chat_id", ""))),
        control_user_ids=_parse_control_user_ids(
            env.get("TELEGRAM_CONTROL_USER_IDS"),
            telegram_raw.get("control_user_ids", []),
        ),
    )

    exchanges = {
        name: ExchangeConfig(
            enabled=bool(payload.get("enabled", False)),
            market_type=str(payload["market_type"]),
        )
        for name, payload in exchanges_raw.items()
    }

    global_blacklist = tuple(str(item) for item in market_raw.get("global_blacklist", []))
    blacklist_file = str(market_raw.get("blacklist_file", ""))
    blacklist_path = _resolve_optional_path(file_path, blacklist_file)

    return AppConfig(
        timezone=str(app_raw.get("timezone", "UTC")),
        strict_mode=bool(app_raw.get("strict_mode", True)),
        control_state_file=control_state_file,
        control_state_path=control_state_path,
        detection=detection,
        telegram=telegram,
        global_blacklist=global_blacklist,
        blacklist_file=blacklist_file,
        blacklist=BlacklistMatcher.load(
            inline_terms=global_blacklist,
            file_path=blacklist_path,
        ),
        exchanges=exchanges,
    )


def _read_toml(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    with file_path.open("rb") as handle:
        return tomllib.load(handle)


def _read_env_overlay(config_path: Path) -> dict[str, str]:
    overlay: dict[str, str] = {}
    candidates = [
        config_path.parent.parent / ".env",
        Path.cwd() / ".env",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            overlay[key.strip()] = value.strip()
    overlay.update(os.environ)
    return overlay


def _resolve_optional_path(config_path: Path, raw_path: str) -> Path | None:
    stripped = raw_path.strip()
    if not stripped:
        return None
    candidate = Path(stripped)
    if candidate.is_absolute():
        return candidate
    return config_path.parent / candidate


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value.strip())
    except ValueError:
        return default


def _parse_control_user_ids(
    raw_value: str | None,
    default_values: Any,
) -> tuple[str, ...]:
    if raw_value is not None:
        return tuple(
            value.strip()
            for value in raw_value.split(",")
            if value.strip()
        )
    if isinstance(default_values, (list, tuple)):
        return tuple(str(value).strip() for value in default_values if str(value).strip())
    return ()
