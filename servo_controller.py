"""
MG996R 標準角型サーボコントローラー (モーメンタリー動作版)

MG996R のような標準サーボ向けの実装。
「中立位置から指定角度へ回転し、作業後に中立位置へ戻る」動作を行います。
これにより、手動でのサムターン操作を阻害しないようにします。

使用方法:
    GPIOZERO_PIN_FACTORY=pigpio python3 -m smartlock_servo --pin 12
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Optional

_USE_PIGPIO = os.environ.get("GPIOZERO_PIN_FACTORY", "").lower() == "pigpio"

try:
    from gpiozero import AngularServo
    ServoClass = AngularServo
    if _USE_PIGPIO:
        from gpiozero.pins.pigpio import PiGPIOFactory
        from gpiozero import Device
        try:
            Device.pin_factory = PiGPIOFactory()
        except Exception:
            pass
except Exception:
    AngularServo = None
    ServoClass = None


class _MockServo:
    """テスト/ドライラン用モック"""
    def __init__(self) -> None:
        self.angle: Optional[float] = None
    def detach(self) -> None:
        self.angle = None
    def close(self) -> None:
        pass


@dataclass(frozen=True)
class ServoConfig:
    """
    MG996R などの標準サーボ用設定
    """
    pin: int = 12
    min_pulse_width: float = 0.0005
    max_pulse_width: float = 0.0025

    # 角度設定 (degrees)
    neutral_angle: float = 0.0   # 待機位置（手動操作を邪魔しない位置）
    lock_angle: float = 90.0     # 施錠方向に回す角度
    unlock_angle: float = -90.0  # 開錠方向に回す角度

    # 動作設定
    move_time: float = 0.5       # 回転にかかる時間の目安
    hold_time: float = 0.5       # 回転しきった状態で保持する時間（秒）


class ServoController:
    """MG996R等の角度型サーボのライフサイクル管理"""

    def __init__(self, config: ServoConfig, dry_run: bool = False) -> None:
        self.config = config
        self.dry_run = dry_run or ServoClass is None
        self._lock = threading.Lock()
        self._servo: Optional[object] = None
        self._initialized = False

    def initialize(self) -> None:
        """サーボデバイスをセットアップ"""
        if self._initialized:
            return

        if self.dry_run:
            logging.warning("Dry-run mode: サーボ出力は無効です")
            self._servo = _MockServo()  # type: ignore
        else:
            if ServoClass is None:
                raise RuntimeError("gpiozero AngularServo が利用できません")
            try:
                # 初期位置は neutral_angle に設定して起動
                self._servo = ServoClass(
                    self.config.pin,
                    min_angle=-90,
                    max_angle=90,
                    initial_angle=self.config.neutral_angle,
                    min_pulse_width=self.config.min_pulse_width,
                    max_pulse_width=self.config.max_pulse_width,
                )
                # 起動直後は一度detachしておくと安全
                time.sleep(0.1)
                self._servo.detach()
                
            except Exception as exc:
                raise RuntimeError(f"サーボ初期化失敗 (GPIO {self.config.pin})") from exc

        self._initialized = True
        pin_factory = os.environ.get("GPIOZERO_PIN_FACTORY", "rpigpio")
        logging.info("サーボ初期化完了: GPIO %d, pin_factory=%s", self.config.pin, pin_factory)

    def cleanup(self) -> None:
        """リソースを解放"""
        if not self._initialized:
            return
        with self._lock:
            if self._servo:
                try:
                    self._detach() # 安全のため脱力
                    if hasattr(self._servo, 'close'):
                        self._servo.close()
                except Exception:
                    logging.exception("cleanup中に例外")
        self._servo = None
        self._initialized = False
        logging.info("サーボをクリーンアップしました")

    def lock(self) -> str:
        """施錠アクション: Neutral -> Lock -> (Wait) -> Neutral -> Detach"""
        logging.info("施錠動作開始: ターゲット %.1f deg", self.config.lock_angle)
        self._perform_action(self.config.lock_angle)
        return "locked"

    def unlock(self) -> str:
        """開錠アクション: Neutral -> Unlock -> (Wait) -> Neutral -> Detach"""
        logging.info("開錠動作開始: ターゲット %.1f deg", self.config.unlock_angle)
        self._perform_action(self.config.unlock_angle)
        return "unlocked"

    def _perform_action(self, target_angle: float) -> None:
        """往復動作の実行ロジック"""
        with self._lock:
            try:
                # 1. ターゲットへ移動
                logging.debug("移動: %.1f -> %.1f", self.config.neutral_angle, target_angle)
                self._set_angle(target_angle)
                
                # 移動完了待ち + 保持時間
                time.sleep(self.config.move_time + self.config.hold_time)

                # 2. 中立位置へ戻る
                logging.debug("復帰: %.1f -> %.1f", target_angle, self.config.neutral_angle)
                self._set_angle(self.config.neutral_angle)
                
                # 戻り移動完了待ち
                time.sleep(self.config.move_time)

            finally:
                # 3. 最後に必ず脱力（手動操作のため）
                self._detach()

    def _set_angle(self, angle: float) -> None:
        """サーボを角度 (degrees) に設定する"""
        if self.dry_run:
            logging.debug("Dry-run: set angle=%.1f", angle)
            return
        if self._servo is None:
            raise RuntimeError("サーボが初期化されていません")
        try:
            setattr(self._servo, 'angle', float(angle))
        except Exception as exc:
            logging.error("角度設定失敗: %s", exc)

    def _detach(self) -> None:
        """PWM信号を停止してサーボを解放"""
        if self._servo is None or self.dry_run:
            return
        if hasattr(self._servo, 'detach'):
            try:
                self._servo.detach()
                logging.debug("Servo detached")
            except Exception:
                logging.exception("detach失敗")