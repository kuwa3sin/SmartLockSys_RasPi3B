#!/usr/bin/env python3
"""Smart lock web service entry point for MG996R angle servo."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
from contextlib import suppress
from pathlib import Path

try:
    from .servo_controller import ServoConfig, ServoController
    from .sensor_controller import ReedSwitchMonitor
    from .web_app import create_app
except ImportError:  # pragma: no cover - direct script execution
    from servo_controller import ServoConfig, ServoController  # type: ignore
    from sensor_controller import ReedSwitchMonitor  # type: ignore
    from web_app import create_app  # type: ignore


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logging.warning("Invalid float for %s=%r; using %s", name, raw, default)
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logging.warning("Invalid int for %s=%r; using %s", name, raw, default)
        return default


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smart lock servo control service (MG996R angle servo)"
    )
    parser.add_argument(
        "--config",
        default=os.getenv("SMARTLOCK_CONFIG", "config.json"),
        help="設定ファイル(JSON)へのパス（デフォルト: config.json）",
    )

    # 以降のオプションは設定ファイルを上書きするための互換用
    parser.add_argument("--pin", type=int, default=None)
    parser.add_argument(
        "--min-pulse-width",
        type=float,
        default=None,
        help="Servo minimum pulse width in seconds (MG996R default: 0.0005)",
    )
    parser.add_argument(
        "--max-pulse-width",
        type=float,
        default=None,
        help="Servo maximum pulse width in seconds (MG996R default: 0.0025)",
    )
    # --- 角度設定 ---
    parser.add_argument(
        "--neutral-angle",
        type=float,
        default=None,
        help="待機位置（中立）の角度 (degrees, default 0.0)",
    )
    parser.add_argument(
        "--lock-angle",
        type=float,
        default=None,
        help="施錠時のターゲット角度 (degrees, default -90.0)",
    )
    parser.add_argument(
        "--unlock-angle",
        type=float,
        default=None,
        help="開錠時のターゲット角度 (degrees, default 90.0)",
    )
    # --- 動作時間設定 ---
    parser.add_argument(
        "--move-time",
        type=float,
        default=None,
        help="角度移動にかける目安時間（秒）",
    )
    parser.add_argument(
        "--hold-time",
        type=float,
        default=None,
        help="回転しきった状態で保持する時間（秒）",
    )

    # サーバー設定
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--log-level", default=None)
    parser.add_argument("--dry-run", action="store_true", help="Force simulation mode")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    parser.add_argument(
        "--ssl",
        choices=('none', 'adhoc', 'cert'),
        default=None,
        help='TLS設定: none/adhoc/cert',
    )
    parser.add_argument("--cert", help="SSL証明書ファイルへのパス")
    parser.add_argument("--key", help="SSL秘密鍵ファイルへのパス")
    return parser.parse_args()


def _load_config(path: str) -> dict:
    cfg_path = Path(path)
    if not cfg_path.is_absolute():
        cfg_path = Path(__file__).resolve().parent / cfg_path
    if not cfg_path.exists():
        raise SystemExit(f"設定ファイルが見つかりません: {cfg_path}")
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"設定ファイルの読み込みに失敗しました: {cfg_path}: {exc}")


def _cfg_get(cfg: dict, path: str, default):
    cur = cfg
    for key in path.split('.'):
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _pick(arg_value, cfg_value, default):
    return cfg_value if arg_value is None else arg_value


def _configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), None)
    if not isinstance(level, int):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
        )
        logging.warning("Unknown log level %s; defaulting to INFO", level_name)
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def _register_signal_handlers(servo: ServoController) -> None:
    def _handler(signum, _frame):
        logging.info("Received signal %s; shutting down", signum)
        servo.cleanup()
        sys.exit(0)

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handler)


def main() -> None:
    args = _parse_args()

    cfg = _load_config(args.config)

    log_level = _pick(args.log_level, _cfg_get(cfg, "logging.level", "INFO"), "INFO")
    _configure_logging(str(log_level))

    dry_run_cfg = bool(_cfg_get(cfg, "dry_run", False))
    dry_run = bool(args.dry_run) or dry_run_cfg

    # 修正された ServoConfig に合わせてパラメータを設定
    servo_cfg = _cfg_get(cfg, "servo", {})
    config = ServoConfig(
        pin=int(_pick(args.pin, servo_cfg.get("pin", 12), 12)),
        min_pulse_width=float(_pick(args.min_pulse_width, servo_cfg.get("min_pulse_width", 0.0005), 0.0005)),
        max_pulse_width=float(_pick(args.max_pulse_width, servo_cfg.get("max_pulse_width", 0.0025), 0.0025)),
        neutral_angle=float(_pick(args.neutral_angle, servo_cfg.get("neutral_angle", 0.0), 0.0)),
        lock_angle=float(_pick(args.lock_angle, servo_cfg.get("lock_angle", -85.0), -85.0)),
        unlock_angle=float(_pick(args.unlock_angle, servo_cfg.get("unlock_angle", 85.0), 85.0)),
        move_time=float(_pick(args.move_time, servo_cfg.get("move_time", 0.5), 0.5)),
        hold_time=float(_pick(args.hold_time, servo_cfg.get("hold_time", 0.5), 0.5)),
    )

    logging.info(
        "Starting SmartLock Service: Neutral=%.1f, Lock=%.1f, Unlock=%.1f",
        config.neutral_angle, config.lock_angle, config.unlock_angle
    )

    servo = ServoController(config, dry_run=dry_run)
    sensors = ReedSwitchMonitor.from_config(_cfg_get(cfg, "sensors", {}), dry_run=dry_run)
    _register_signal_handlers(servo)

    web_cfg = _cfg_get(cfg, "web", {})
    ssl_cfg = web_cfg.get("ssl", {}) if isinstance(web_cfg, dict) else {}

    host = str(_pick(args.host, web_cfg.get("host", "0.0.0.0"), "0.0.0.0"))
    port = int(_pick(args.port, web_cfg.get("port", 8080), 8080))
    debug = bool(args.debug) or bool(web_cfg.get("debug", False))

    ssl_mode = _pick(args.ssl, ssl_cfg.get("mode", "none"), "none")
    cert = args.cert if args.cert else ssl_cfg.get("cert")
    key = args.key if args.key else ssl_cfg.get("key")

    ssl_context = None
    if ssl_mode == 'adhoc':
        ssl_context = 'adhoc'
    elif ssl_mode == 'cert':
        if not cert or not key:
            raise SystemExit('certモードには設定ファイルまたは --cert/--key の指定が必要です')
        ssl_context = (cert, key)

    try:
        servo.initialize()
        sensors.initialize()
        features_cfg = _cfg_get(cfg, "features", {})
        auto_lock_seconds = float(features_cfg.get("auto_lock_seconds", 0)) if isinstance(features_cfg, dict) else 0.0
        action_confirm_timeout_s = float(features_cfg.get("action_confirm_timeout_seconds", 3.0)) if isinstance(features_cfg, dict) else 3.0

        app = create_app(
            servo,
            sensors,
            auto_lock_seconds_default=auto_lock_seconds,
            action_confirm_timeout_s=action_confirm_timeout_s,
        )
        app.run(
            host=host,
            port=port,
            debug=debug,
            use_reloader=False,
            ssl_context=ssl_context,
        )
    except KeyboardInterrupt:
        logging.info('Interrupted; shutting down')
    finally:
        with suppress(Exception):
            sensors.cleanup()
        with suppress(Exception):
            servo.cleanup()


if __name__ == "__main__":
    main()