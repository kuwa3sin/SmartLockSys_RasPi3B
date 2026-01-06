#!/usr/bin/env python3
"""Smart lock web service entry point for MG996R angle servo."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from contextlib import suppress

try:
    from .servo_controller import ServoConfig, ServoController
    from .web_app import create_app
except ImportError:  # pragma: no cover - direct script execution
    from servo_controller import ServoConfig, ServoController  # type: ignore
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
    parser.add_argument("--pin", type=int, default=_env_int("SMARTLOCK_SERVO_PIN", 12))
    parser.add_argument(
        "--min-pulse-width",
        type=float,
        default=_env_float("SMARTLOCK_MIN_PULSE_WIDTH", 0.0005),
        help="Servo minimum pulse width in seconds (MG996R default: 0.0005)",
    )
    parser.add_argument(
        "--max-pulse-width",
        type=float,
        default=_env_float("SMARTLOCK_MAX_PULSE_WIDTH", 0.0025),
        help="Servo maximum pulse width in seconds (MG996R default: 0.0025)",
    )
    # --- 角度設定 ---
    parser.add_argument(
        "--neutral-angle",
        type=float,
        default=_env_float("SMARTLOCK_NEUTRAL_ANGLE", 0.0),
        help="待機位置（中立）の角度 (degrees, default 0.0)",
    )
    parser.add_argument(
        "--lock-angle",
        type=float,
        default=_env_float("SMARTLOCK_LOCK_ANGLE", -85.0),
        help="施錠時のターゲット角度 (degrees, default -90.0)",
    )
    parser.add_argument(
        "--unlock-angle",
        type=float,
        default=_env_float("SMARTLOCK_UNLOCK_ANGLE", 85.0),
        help="開錠時のターゲット角度 (degrees, default 90.0)",
    )
    # --- 動作時間設定 ---
    parser.add_argument(
        "--move-time",
        type=float,
        default=_env_float("SMARTLOCK_MOVE_TIME", 0.5),
        help="角度移動にかける目安時間（秒）",
    )
    parser.add_argument(
        "--hold-time",
        type=float,
        default=_env_float("SMARTLOCK_HOLD_TIME", 0.5),
        help="回転しきった状態で保持する時間（秒）",
    )

    # サーバー設定
    parser.add_argument("--host", default=os.getenv("SMARTLOCK_HTTP_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=_env_int("SMARTLOCK_HTTP_PORT", 8080))
    parser.add_argument("--log-level", default=os.getenv("SMARTLOCK_LOG_LEVEL", "INFO"))
    parser.add_argument("--dry-run", action="store_true", help="Force simulation mode")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    parser.add_argument(
        "--ssl",
        choices=('none', 'adhoc', 'cert'),
        default=os.getenv('SMARTLOCK_SSL_MODE', 'none'),
        help='TLS設定: none/adhoc/cert',
    )
    parser.add_argument("--cert", help="SSL証明書ファイルへのパス")
    parser.add_argument("--key", help="SSL秘密鍵ファイルへのパス")
    return parser.parse_args()


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
    _configure_logging(args.log_level)
    dry_run = args.dry_run or _env_bool("SMARTLOCK_DRY_RUN", False)

    # 修正された ServoConfig に合わせてパラメータを設定
    config = ServoConfig(
        pin=args.pin,
        min_pulse_width=args.min_pulse_width,
        max_pulse_width=args.max_pulse_width,
        neutral_angle=args.neutral_angle,  # 追加
        lock_angle=args.lock_angle,
        unlock_angle=args.unlock_angle,
        move_time=args.move_time,
        hold_time=args.hold_time,          # 追加 (旧 hold=... は削除)
    )

    logging.info(
        "Starting SmartLock Service: Neutral=%.1f, Lock=%.1f, Unlock=%.1f",
        config.neutral_angle, config.lock_angle, config.unlock_angle
    )

    servo = ServoController(config, dry_run=dry_run)
    _register_signal_handlers(servo)

    ssl_context = None
    if args.ssl == 'adhoc':
        ssl_context = 'adhoc'
    elif args.ssl == 'cert':
        if not args.cert or not args.key:
            raise SystemExit('certモードには --cert と --key の指定が必要です')
        ssl_context = (args.cert, args.key)

    try:
        servo.initialize()
        app = create_app(servo)
        app.run(
            host=args.host,
            port=args.port,
            debug=args.debug,
            use_reloader=False,
            ssl_context=ssl_context,
        )
    except KeyboardInterrupt:
        logging.info('Interrupted; shutting down')
    finally:
        with suppress(Exception):
            servo.cleanup()


if __name__ == "__main__":
    main()