from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys
from typing import Callable

from density_screener.debug import run_debug_simulation
from density_screener.detector import DensityDetector
from density_screener.exchanges.aster_futures import AsterFuturesAdapter
from density_screener.exchanges.bitget_spot import BitgetSpotAdapter
from density_screener.exchanges.hyperliquid import HyperliquidAdapter
from density_screener.exchanges.htx_spot import HTXSpotAdapter
from density_screener.exchanges.lighter import LighterAdapter
from density_screener.exchanges.bybit_spot import BybitSpotAdapter
from density_screener.exchanges.kucoin_futures import KuCoinFuturesAdapter
from density_screener.exchanges.kucoin_spot import KuCoinSpotAdapter
from density_screener.notifiers import TelegramNotifier
from density_screener.runtime import ScreenerRuntime
from density_screener.settings import load_config


AdapterFactory = Callable[[object], object]

ADAPTER_FACTORIES: dict[str, AdapterFactory] = {
    "bybit_spot": BybitSpotAdapter,
    "bitget_spot": BitgetSpotAdapter,
    "kucoin_spot": KuCoinSpotAdapter,
    "kucoin_futures": KuCoinFuturesAdapter,
    "htx": HTXSpotAdapter,
    "aster": AsterFuturesAdapter,
    "hyperliquid": HyperliquidAdapter,
    "lighter": LighterAdapter,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Density screener")
    parser.add_argument("--config", default="config/app.toml", help="Path to TOML config")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("doctor", help="Validate config and environment")
    subparsers.add_parser("debug-simulate", help="Run synthetic detector scenario")
    bybit_parser = subparsers.add_parser("run-bybit-spot", help="Run live Bybit spot screener")
    bybit_parser.add_argument("--symbol-limit", type=int, default=5, help="Limit symbols for smoke tests")
    bybit_parser.add_argument("--max-snapshots", type=int, default=None, help="Stop after N processed snapshots")
    bitget_parser = subparsers.add_parser("run-bitget-spot", help="Run live Bitget spot screener")
    bitget_parser.add_argument("--symbol-limit", type=int, default=5, help="Limit symbols for smoke tests")
    bitget_parser.add_argument("--max-snapshots", type=int, default=None, help="Stop after N processed snapshots")
    kucoin_spot_parser = subparsers.add_parser("run-kucoin-spot", help="Run live KuCoin spot screener")
    kucoin_spot_parser.add_argument("--symbol-limit", type=int, default=5, help="Limit symbols for smoke tests")
    kucoin_spot_parser.add_argument("--max-snapshots", type=int, default=None, help="Stop after N processed snapshots")
    kucoin_futures_parser = subparsers.add_parser("run-kucoin-futures", help="Run live KuCoin futures screener")
    kucoin_futures_parser.add_argument("--symbol-limit", type=int, default=5, help="Limit symbols for smoke tests")
    kucoin_futures_parser.add_argument("--max-snapshots", type=int, default=None, help="Stop after N processed snapshots")
    htx_parser = subparsers.add_parser("run-htx-spot", help="Run live HTX spot screener")
    htx_parser.add_argument("--symbol-limit", type=int, default=5, help="Limit symbols for smoke tests")
    htx_parser.add_argument("--max-snapshots", type=int, default=None, help="Stop after N processed snapshots")
    aster_parser = subparsers.add_parser("run-aster-futures", help="Run live Aster futures screener")
    aster_parser.add_argument("--symbol-limit", type=int, default=1, help="Limit symbols for smoke tests")
    aster_parser.add_argument("--max-snapshots", type=int, default=None, help="Stop after N processed snapshots")
    hyperliquid_parser = subparsers.add_parser("run-hyperliquid", help="Run live Hyperliquid screener")
    hyperliquid_parser.add_argument("--symbol-limit", type=int, default=5, help="Limit symbols for smoke tests")
    hyperliquid_parser.add_argument("--max-snapshots", type=int, default=None, help="Stop after N processed snapshots")
    lighter_parser = subparsers.add_parser("run-lighter", help="Run live Lighter screener")
    lighter_parser.add_argument("--symbol-limit", type=int, default=5, help="Limit symbols for smoke tests")
    lighter_parser.add_argument("--max-snapshots", type=int, default=None, help="Stop after N processed snapshots")
    enabled_parser = subparsers.add_parser("run-enabled", help="Run all enabled exchanges from config")
    enabled_parser.add_argument("--exchanges", default="", help="Optional comma-separated subset of enabled exchange keys")
    enabled_parser.add_argument("--symbol-limit", type=int, default=None, help="Limit symbols per exchange for smoke tests")
    enabled_parser.add_argument("--max-snapshots", type=int, default=None, help="Stop each exchange after N processed snapshots")
    telegram_parser = subparsers.add_parser("test-telegram", help="Send a test Telegram message")
    telegram_parser.add_argument("--text", default="Density Screener test message", help="Telegram message text")

    args = parser.parse_args(argv)

    if args.command == "doctor":
        return _doctor(Path(args.config))
    if args.command == "debug-simulate":
        return _debug_simulate()
    if args.command == "run-bybit-spot":
        return asyncio.run(_run_bybit_spot(Path(args.config), args.symbol_limit, args.max_snapshots))
    if args.command == "run-bitget-spot":
        return asyncio.run(_run_bitget_spot(Path(args.config), args.symbol_limit, args.max_snapshots))
    if args.command == "run-kucoin-spot":
        return asyncio.run(_run_kucoin_spot(Path(args.config), args.symbol_limit, args.max_snapshots))
    if args.command == "run-kucoin-futures":
        return asyncio.run(_run_kucoin_futures(Path(args.config), args.symbol_limit, args.max_snapshots))
    if args.command == "run-htx-spot":
        return asyncio.run(_run_htx_spot(Path(args.config), args.symbol_limit, args.max_snapshots))
    if args.command == "run-aster-futures":
        return asyncio.run(_run_aster_futures(Path(args.config), args.symbol_limit, args.max_snapshots))
    if args.command == "run-hyperliquid":
        return asyncio.run(_run_hyperliquid(Path(args.config), args.symbol_limit, args.max_snapshots))
    if args.command == "run-lighter":
        return asyncio.run(_run_lighter(Path(args.config), args.symbol_limit, args.max_snapshots))
    if args.command == "run-enabled":
        return asyncio.run(_run_enabled(Path(args.config), args.exchanges, args.symbol_limit, args.max_snapshots))
    if args.command == "test-telegram":
        return asyncio.run(_test_telegram(Path(args.config), args.text))
    if not Path(args.config).exists():
        parser.error(f"Config file not found: {args.config}")
    print("Live runtime is being added incrementally. Use 'doctor' or 'debug-simulate' for now.")
    return 0


def _doctor(config_path: Path) -> int:
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        return 1
    config = load_config(config_path)
    print(f"timezone={config.timezone}")
    print(f"strict_mode={config.strict_mode}")
    print(f"spot_min_notional_usd={config.detection.spot_min_notional_usd:.0f}")
    print(f"futures_min_notional_usd={config.detection.futures_min_notional_usd:.0f}")
    print(f"volume_multiplier={config.detection.volume_multiplier:.2f}")
    print(f"price_window_pct={config.detection.price_window_pct:.2f}")
    print(f"min_lifetime_seconds={config.detection.min_lifetime_seconds:.1f}")
    print(f"blacklist_size={config.blacklist.entries_count}")
    print(f"blacklist_inline={len(config.global_blacklist)}")
    print(f"blacklist_exact={len(config.blacklist.exact_symbols)}")
    print(f"blacklist_base_assets={len(config.blacklist.base_assets)}")
    print(f"blacklist_patterns={len(config.blacklist.patterns)}")
    print(f"blacklist_file={config.blacklist_file or 'disabled'}")
    enabled = [name for name, payload in config.exchanges.items() if payload.enabled]
    print(f"enabled_exchanges={','.join(enabled)}")
    print(f"telegram_enabled={config.telegram.enabled}")
    return 0


def _debug_simulate() -> int:
    results = run_debug_simulation()
    if not results:
        print("No signals were produced by the simulation.")
        return 1
    for line in results:
        print(line)
    return 0


async def _run_bybit_spot(config_path: Path, symbol_limit: int, max_snapshots: int | None) -> int:
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        return 1
    config = load_config(config_path)
    await _run_named_exchange(config, "bybit_spot", symbol_limit, max_snapshots)
    return 0


async def _run_bitget_spot(config_path: Path, symbol_limit: int, max_snapshots: int | None) -> int:
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        return 1
    config = load_config(config_path)
    await _run_named_exchange(config, "bitget_spot", symbol_limit, max_snapshots)
    return 0


async def _run_kucoin_spot(config_path: Path, symbol_limit: int, max_snapshots: int | None) -> int:
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        return 1
    config = load_config(config_path)
    await _run_named_exchange(config, "kucoin_spot", symbol_limit, max_snapshots)
    return 0


async def _run_kucoin_futures(config_path: Path, symbol_limit: int, max_snapshots: int | None) -> int:
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        return 1
    config = load_config(config_path)
    await _run_named_exchange(config, "kucoin_futures", symbol_limit, max_snapshots)
    return 0


async def _run_htx_spot(config_path: Path, symbol_limit: int, max_snapshots: int | None) -> int:
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        return 1
    config = load_config(config_path)
    await _run_named_exchange(config, "htx", symbol_limit, max_snapshots)
    return 0


async def _run_aster_futures(config_path: Path, symbol_limit: int, max_snapshots: int | None) -> int:
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        return 1
    config = load_config(config_path)
    await _run_named_exchange(config, "aster", symbol_limit, max_snapshots)
    return 0


async def _run_hyperliquid(config_path: Path, symbol_limit: int, max_snapshots: int | None) -> int:
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        return 1
    config = load_config(config_path)
    await _run_named_exchange(config, "hyperliquid", symbol_limit, max_snapshots)
    return 0


async def _run_lighter(config_path: Path, symbol_limit: int, max_snapshots: int | None) -> int:
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        return 1
    config = load_config(config_path)
    await _run_named_exchange(config, "lighter", symbol_limit, max_snapshots)
    return 0


async def _run_enabled(
    config_path: Path,
    selected_exchanges: str,
    symbol_limit: int | None,
    max_snapshots: int | None,
) -> int:
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        return 1
    config = load_config(config_path)
    requested = _parse_exchange_names(selected_exchanges)
    available = _enabled_exchange_names(config.exchanges, requested)
    unknown = requested - set(ADAPTER_FACTORIES) if requested else set()
    if unknown:
        print(f"[supervisor] unknown_exchanges={','.join(sorted(unknown))}", flush=True)
    if not available:
        print("[supervisor] no enabled exchanges selected", flush=True)
        return 1

    print(f"[supervisor] exchanges={','.join(available)}", flush=True)
    tasks = [
        asyncio.create_task(
            _run_supervised_exchange(
                config,
                exchange_name,
                symbol_limit=symbol_limit,
                max_snapshots=max_snapshots,
            )
        )
        for exchange_name in available
    ]
    results = await asyncio.gather(*tasks)
    return 0 if any(results) else 1


async def _run_named_exchange(
    config,
    exchange_name: str,
    symbol_limit: int | None,
    max_snapshots: int | None,
) -> None:
    detector = DensityDetector(config.detection)
    notifier = TelegramNotifier(config.telegram)
    runtime = ScreenerRuntime(detector, notifier if notifier.enabled else None)
    adapter = ADAPTER_FACTORIES[exchange_name](config.detection)
    await adapter.run(
        runtime,
        blacklist=config.blacklist,
        symbol_limit=symbol_limit,
        stop_after_snapshots=max_snapshots,
    )


async def _run_supervised_exchange(
    config,
    exchange_name: str,
    *,
    symbol_limit: int | None,
    max_snapshots: int | None,
) -> bool:
    try:
        print(f"[supervisor] starting={exchange_name}", flush=True)
        await _run_named_exchange(config, exchange_name, symbol_limit, max_snapshots)
    except Exception as error:
        print(f"[supervisor] exchange_failed={exchange_name} error={error}", flush=True)
        return False
    return True


def _parse_exchange_names(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def _enabled_exchange_names(
    exchanges: dict[str, object],
    requested: set[str],
) -> list[str]:
    selected: list[str] = []
    for name, payload in exchanges.items():
        if name not in ADAPTER_FACTORIES:
            continue
        if not payload.enabled:
            continue
        if requested and name not in requested:
            continue
        selected.append(name)
    return selected


async def _test_telegram(config_path: Path, text: str) -> int:
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        return 1
    config = load_config(config_path)
    notifier = TelegramNotifier(config.telegram)
    if not notifier.enabled:
        print("Telegram is not enabled. Check config/app.toml and .env.")
        return 1
    ok = await notifier.send_text(text)
    print(f"telegram_sent={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
