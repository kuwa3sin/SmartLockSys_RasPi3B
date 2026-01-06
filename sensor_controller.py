"""GPIO reed switch input helpers for SmartLock.

Two reed switches are assumed:
- Lock state switch: ON => locked, OFF => unlocked
- Door state switch: ON => closed, OFF => open

"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

try:
    import pigpio  # pyright: ignore[reportMissingImports]
except Exception:  # pragma: no cover - runtime dependency
    pigpio = None

try:
    from gpiozero import DigitalInputDevice  # pyright: ignore[reportMissingImports]
except Exception:  # pragma: no cover - runtime dependency
    DigitalInputDevice = None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class ReedSwitchConfig:
    def __init__(
        self,
        pin: int,
        pull_up: bool = True,
        active_low: bool = True,
        bounce_time: float = 0.05,
    ) -> None:
        self.pin = int(pin)
        self.pull_up = bool(pull_up)
        self.active_low = bool(active_low)
        self.bounce_time = float(bounce_time)


class ReedSwitchMonitor:
    def __init__(
        self,
        lock_switch: Optional[ReedSwitchConfig],
        door_switch: Optional[ReedSwitchConfig],
        *,
        dry_run: bool = False,
    ) -> None:
        self._lock_cfg = lock_switch
        self._door_cfg = door_switch
        self.dry_run = dry_run or (DigitalInputDevice is None and pigpio is None)

        self._lock_dev: Optional[Any] = None
        self._door_dev: Optional[Any] = None
        self._pi: Optional[Any] = None
        self._initialized = False

    @staticmethod
    def from_env(*, dry_run: bool = False) -> "ReedSwitchMonitor":
        def _env_int_optional(name: str) -> Optional[int]:
            raw = os.getenv(name)
            if raw is None or raw.strip() == "":
                return None
            try:
                return int(raw)
            except ValueError:
                logging.warning("Invalid int for %s=%r; ignoring", name, raw)
                return None

        lock_pin = _env_int_optional("SMARTLOCK_LOCK_SWITCH_PIN")
        door_pin = _env_int_optional("SMARTLOCK_DOOR_SWITCH_PIN")

        lock_active_low = _env_bool("SMARTLOCK_LOCK_SWITCH_ACTIVE_LOW", True)
        door_active_low = _env_bool("SMARTLOCK_DOOR_SWITCH_ACTIVE_LOW", True)

        lock_pull_up = _env_bool("SMARTLOCK_LOCK_SWITCH_PULL_UP", True)
        door_pull_up = _env_bool("SMARTLOCK_DOOR_SWITCH_PULL_UP", True)

        lock_cfg = None if lock_pin is None else ReedSwitchConfig(lock_pin, lock_pull_up, lock_active_low)
        door_cfg = None if door_pin is None else ReedSwitchConfig(door_pin, door_pull_up, door_active_low)
        return ReedSwitchMonitor(lock_cfg, door_cfg, dry_run=dry_run)

    def initialize(self) -> None:
        if self._initialized:
            return

        if self.dry_run:
            logging.warning("Dry-run mode: reed switches are disabled")
            self._initialized = True
            return

        # pigpioが使えるなら優先（glitch filter/コールバック等が強い）
        if pigpio is not None:
            pi = pigpio.pi()  # type: ignore[attr-defined]
            if not getattr(pi, "connected", False):
                try:
                    pi.stop()
                except Exception:
                    pass
            else:
                self._pi = pi
                for cfg in (self._lock_cfg, self._door_cfg):
                    if cfg is None:
                        continue
                    pi.set_mode(cfg.pin, pigpio.INPUT)  # type: ignore[attr-defined]
                    if cfg.pull_up:
                        pi.set_pull_up_down(cfg.pin, pigpio.PUD_UP)  # type: ignore[attr-defined]
                    else:
                        pi.set_pull_up_down(cfg.pin, pigpio.PUD_DOWN)  # type: ignore[attr-defined]

                    # bounce_time秒をglitch filter(μs)に変換してノイズ除去
                    glitch_us = int(max(0.0, cfg.bounce_time) * 1_000_000)
                    pi.set_glitch_filter(cfg.pin, glitch_us)

        # pigpioが無理ならgpiozeroでフォールバック
        if self._pi is None:
            if DigitalInputDevice is None:
                raise RuntimeError("pigpio または gpiozero が必要です")

            if self._lock_cfg is not None:
                self._lock_dev = DigitalInputDevice(
                    self._lock_cfg.pin,
                    pull_up=self._lock_cfg.pull_up,
                    active_state=(not self._lock_cfg.active_low),
                    bounce_time=self._lock_cfg.bounce_time,
                )
            if self._door_cfg is not None:
                self._door_dev = DigitalInputDevice(
                    self._door_cfg.pin,
                    pull_up=self._door_cfg.pull_up,
                    active_state=(not self._door_cfg.active_low),
                    bounce_time=self._door_cfg.bounce_time,
                )

        self._initialized = True
        logging.info(
            "Reed switches initialized: lock=%s door=%s",
            None if self._lock_cfg is None else f"GPIO {self._lock_cfg.pin}",
            None if self._door_cfg is None else f"GPIO {self._door_cfg.pin}",
        )

    def cleanup(self) -> None:
        if not self._initialized:
            return
        if self._pi is not None:
            try:
                self._pi.stop()
            except Exception:
                logging.exception("Failed to stop pigpio")
            self._pi = None
        for dev in (self._lock_dev, self._door_dev):
            if dev is None:
                continue
            try:
                if hasattr(dev, "close"):
                    getattr(dev, "close")()
            except Exception:
                logging.exception("Failed to close reed switch device")
        self._lock_dev = None
        self._door_dev = None
        self._initialized = False

    def lock_switch_on(self) -> Optional[bool]:
        """True when switch is ON, False when OFF, None when unavailable."""
        if self.dry_run or self._lock_cfg is None:
            return None

        if self._pi is not None:
            try:
                level = int(self._pi.read(self._lock_cfg.pin))
                return (level == 0) if self._lock_cfg.active_low else (level == 1)
            except Exception:
                return None

        if self._lock_dev is None:
            return None
        return bool(getattr(self._lock_dev, "is_active"))

    def door_switch_on(self) -> Optional[bool]:
        """True when switch is ON, False when OFF, None when unavailable."""
        if self.dry_run or self._door_cfg is None:
            return None

        if self._pi is not None:
            try:
                level = int(self._pi.read(self._door_cfg.pin))
                return (level == 0) if self._door_cfg.active_low else (level == 1)
            except Exception:
                return None

        if self._door_dev is None:
            return None
        return bool(getattr(self._door_dev, "is_active"))

    def is_locked(self) -> Optional[bool]:
        """ON => locked, OFF => unlocked."""
        return self.lock_switch_on()

    def is_door_closed(self) -> Optional[bool]:
        """ON => closed, OFF => open."""
        return self.door_switch_on()
