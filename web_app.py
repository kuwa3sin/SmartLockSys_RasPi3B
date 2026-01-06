"""Flask application for the smart lock web interface."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import threading
import time

try:
    from flask import Flask, jsonify, render_template, request  # pyright: ignore[reportMissingImports]
except ImportError as exc:  # pragma: no cover - configuration error
    raise RuntimeError("Flask is required. Install with 'pip install flask'.") from exc

try:
    from .servo_controller import ServoController
except ImportError:  # pragma: no cover - direct script execution
    from servo_controller import ServoController  # type: ignore

try:
    from .sensor_controller import ReedSwitchMonitor
except ImportError:  # pragma: no cover - direct script execution
    from sensor_controller import ReedSwitchMonitor  # type: ignore


def create_app(servo: ServoController, sensors: Optional[ReedSwitchMonitor] = None) -> Flask:
    # テンプレートディレクトリはパッケージ内の templates 配下を指す
    template_dir = Path(__file__).resolve().parent / "templates"
    app = Flask(__name__, template_folder=str(template_dir))

    state_lock = threading.Lock()
    auto_lock_seconds: float = 0.0
    last_unlock_ts: Optional[float] = None
    virtual_locked: Optional[bool] = None

    def _now() -> float:
        # MicroPython互換も意識してtime.timeを使用
        return float(time.time())

    def _read_sensor_state() -> Dict[str, Any]:
        lock_on = sensors.lock_switch_on() if sensors else None
        door_on = sensors.door_switch_on() if sensors else None

        state_lock.acquire()
        try:
            v_locked = virtual_locked
        finally:
            state_lock.release()

        effective_locked = lock_on if lock_on is not None else v_locked
        return {
            "lockSwitchOn": lock_on,
            "doorSwitchOn": door_on,
            "locked": lock_on,
            "doorClosed": door_on,
            "effectiveLocked": effective_locked,
            "lockKnown": effective_locked is not None,
            "lockSource": "sensor" if lock_on is not None else ("virtual" if v_locked is not None else "unknown"),
        }

    def _current() -> Dict[str, Any]:
        """現在の設定とステータスを返す。"""
        state_lock.acquire()
        try:
            als = auto_lock_seconds
            lu = last_unlock_ts
        finally:
            state_lock.release()

        sensors_state = _read_sensor_state()
        now = _now()

        return {
            "status": "idle",  # 基本的に常に待機・脱力状態
            "dryRun": servo.dry_run,
            "pin": servo.config.pin,
            "sensors": sensors_state,
            "autoLock": {
                "seconds": als,
                "enabled": als > 0,
                "secondsSinceLastUnlock": None if lu is None else max(0.0, now - lu),
            },
            "angles": {
                "neutral": servo.config.neutral_angle,
                "lock": servo.config.lock_angle,
                "unlock": servo.config.unlock_angle,
            },
            "times": {
                "move": servo.config.move_time,
                "hold": servo.config.hold_time,
            },
        }

    def _door_is_open() -> Optional[bool]:
        if not sensors:
            return None
        closed = sensors.is_door_closed()
        return None if closed is None else (not closed)

    def _is_locked() -> Optional[bool]:
        state_lock.acquire()
        try:
            v_locked = virtual_locked
        finally:
            state_lock.release()

        if not sensors:
            return v_locked
        locked = sensors.is_locked()
        return locked if locked is not None else v_locked

    def _set_virtual_locked(value: Optional[bool]) -> None:
        nonlocal virtual_locked
        state_lock.acquire()
        try:
            virtual_locked = value
        finally:
            state_lock.release()

    def _set_last_unlock_now() -> None:
        nonlocal last_unlock_ts
        state_lock.acquire()
        try:
            last_unlock_ts = _now()
        finally:
            state_lock.release()

    def _set_auto_lock_seconds(value: float) -> None:
        nonlocal auto_lock_seconds
        state_lock.acquire()
        try:
            auto_lock_seconds = max(0.0, float(value))
        finally:
            state_lock.release()

    @app.get("/api/status")
    def status() -> Any:
        # ステータスをポーリングするためのエンドポイント
        return jsonify(_current())

    @app.post("/api/autolock")
    def set_autolock() -> Any:
        payload = request.get_json(silent=True) or {}
        seconds = payload.get("seconds", 0) if isinstance(payload, dict) else 0
        try:
            seconds_f = float(seconds)
        except Exception:
            return jsonify({"error": "invalid_seconds"}), 400

        _set_auto_lock_seconds(seconds_f)
        response = _current()
        response["lastAction"] = "autolock_updated"
        return jsonify(response)

    @app.post("/api/lock")
    def do_lock() -> Any:
        # ドアが開いている場合は施錠拒否
        door_open = _door_is_open()
        if door_open is True:
            response = _current()
            response["error"] = "door_open"
            response["message"] = "ドアが開いているため施錠できません"
            return jsonify(response), 409

        action_result = servo.lock()
        _set_virtual_locked(True)
        response = _current()
        response["lastAction"] = action_result
        return jsonify(response)

    @app.post("/api/unlock")
    def do_unlock() -> Any:
        # 解錠コマンドを発行
        action_result = servo.unlock()

        _set_last_unlock_now()
        _set_virtual_locked(False)
        
        response = _current()
        response["lastAction"] = action_result  # "unlocked"
        return jsonify(response)

    @app.post("/api/toggle")
    def do_toggle() -> Any:
        locked = _is_locked()
        # 状態不明時は安全側で「開錠」を実行して状態を確定させる
        if locked is None or locked is True:
            action_result = servo.unlock()
            _set_last_unlock_now()
            _set_virtual_locked(False)
            response = _current()
            response["lastAction"] = action_result
            return jsonify(response)

        # unlocked -> lock (door open check)
        door_open = _door_is_open()
        if door_open is True:
            response = _current()
            response["error"] = "door_open"
            response["message"] = "ドアが開いているため施錠できません"
            return jsonify(response), 409

        action_result = servo.lock()
        _set_virtual_locked(True)
        response = _current()
        response["lastAction"] = action_result
        return jsonify(response)

    @app.get("/")
    def index() -> Any:
        # 単一ページのUIを描画
        return render_template("index.html")

    def _start_autolock_thread() -> None:
        if not sensors:
            return

        sensors_local = sensors

        nonlocal last_unlock_ts

        # 起動時点で既に開錠なら、起動時刻を「前回開錠」とみなす
        try:
            if sensors_local.is_locked() is False:
                state_lock.acquire()
                try:
                    last_unlock_ts = _now()
                finally:
                    state_lock.release()
        except Exception:
            pass

        def _loop() -> None:
            nonlocal last_unlock_ts
            prev_locked: Optional[bool] = None
            while True:
                try:
                    locked = sensors_local.is_locked()
                    door_closed = sensors_local.is_door_closed()

                    # 施錠->開錠への遷移を検知（手動開錠も含めてタイムスタンプ更新）
                    if prev_locked is True and locked is False:
                        state_lock.acquire()
                        try:
                            last_unlock_ts = _now()
                        finally:
                            state_lock.release()

                    prev_locked = locked

                    state_lock.acquire()
                    try:
                        als = auto_lock_seconds
                        lu = last_unlock_ts
                    finally:
                        state_lock.release()

                    if als > 0 and locked is False and door_closed is True and lu is not None:
                        if (_now() - lu) >= als:
                            # 施錠実行（サーボ制御は内部で排他）
                            try:
                                servo.lock()
                            finally:
                                # 直後に再連打しないよう、タイムスタンプを進めておく
                                state_lock.acquire()
                                try:
                                    last_unlock_ts = _now()
                                finally:
                                    state_lock.release()

                except Exception:
                    # センサーの一時エラー等で落ちないようにする
                    pass
                time.sleep(0.5)

        t = threading.Thread(target=_loop, name="smartlock-autolock", daemon=True)
        t.start()

    _start_autolock_thread()

    return app