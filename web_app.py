"""Flask application for the smart lock web interface."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

try:
    from flask import Flask, jsonify, render_template
except ImportError as exc:  # pragma: no cover - configuration error
    raise RuntimeError("Flask is required. Install with 'pip install flask'.") from exc

try:
    from .servo_controller import ServoController
except ImportError:  # pragma: no cover - direct script execution
    from servo_controller import ServoController  # type: ignore


def create_app(servo: ServoController) -> Flask:
    # テンプレートディレクトリはパッケージ内の templates 配下を指す
    template_dir = Path(__file__).resolve().parent / "templates"
    app = Flask(__name__, template_folder=str(template_dir))

    def _current() -> Dict[str, Any]:
        """現在の設定とステータスを返す（モーメンタリー動作のためstateは固定）"""
        return {
            "status": "idle",  # 基本的に常に待機・脱力状態
            "dryRun": servo.dry_run,
            "pin": servo.config.pin,
            # 新しい設定項目をレスポンスに追加
            "angles": {
                "neutral": servo.config.neutral_angle,
                "lock": servo.config.lock_angle,
                "unlock": servo.config.unlock_angle,
            },
            "times": {
                "move": servo.config.move_time,
                "hold": servo.config.hold_time,
            }
        }

    @app.get("/api/status")
    def status() -> Any:
        # ステータスをポーリングするためのエンドポイント
        return jsonify(_current())

    @app.post("/api/lock")
    def do_lock() -> Any:
        # 施錠コマンドを発行
        # コントローラーはブロック処理（回転→待機→戻る）を行い、完了後に戻り値を返す
        action_result = servo.lock()
        
        response = _current()
        response["lastAction"] = action_result  # "locked"
        return jsonify(response)

    @app.post("/api/unlock")
    def do_unlock() -> Any:
        # 解錠コマンドを発行
        action_result = servo.unlock()
        
        response = _current()
        response["lastAction"] = action_result  # "unlocked"
        return jsonify(response)

    @app.get("/")
    def index() -> Any:
        # 単一ページのUIを描画
        return render_template("index.html")

    return app