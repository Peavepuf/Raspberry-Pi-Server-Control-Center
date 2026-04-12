from __future__ import annotations

import logging
import threading
from pathlib import Path

from monitor.models import FanSettings

LOGGER = logging.getLogger(__name__)

CPU_TEMP_PATH = Path("/sys/class/thermal/thermal_zone0/temp")

try:
    import RPi.GPIO as GPIO
except Exception:
    GPIO = None


class TemperatureFanController:
    def __init__(self, settings: FanSettings) -> None:
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._settings = settings
        self._gpio_ready = False
        self._available = GPIO is not None
        self._last_error: str | None = None if self._available else "RPi.GPIO module was not found."
        self._last_temp_c: float | None = None
        self._current_speed_percent = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._setup_gpio()
        self._thread = threading.Thread(target=self._run_loop, name="fan-controller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

        if GPIO is not None and self._gpio_ready:
            try:
                with self._lock:
                    settings = self._settings
                self._write_output(settings, turn_on=False)
                GPIO.cleanup(settings.pin)
            except Exception:
                LOGGER.exception("GPIO cleanup failed.")
            finally:
                with self._lock:
                    self._gpio_ready = False
                    self._current_speed_percent = 0

    def update_settings(self, settings: FanSettings) -> None:
        with self._lock:
            previous_settings = self._settings
            pin_changed = settings.pin != previous_settings.pin
            logic_changed = settings.active_low != previous_settings.active_low
            current_speed_percent = self._current_speed_percent
            self._settings = settings

        if pin_changed:
            if GPIO is not None and self._gpio_ready:
                try:
                    self._write_output(previous_settings, turn_on=False)
                    GPIO.cleanup(previous_settings.pin)
                except Exception:
                    LOGGER.exception("GPIO cleanup before reconfiguration failed.")
                finally:
                    with self._lock:
                        self._gpio_ready = False
                        self._current_speed_percent = 0
            self._setup_gpio()
            return

        if logic_changed and GPIO is not None and self._gpio_ready:
            try:
                self._write_output(settings, turn_on=current_speed_percent > 0)
                with self._lock:
                    self._last_error = None
            except Exception as exc:
                LOGGER.exception("Failed to update relay logic: %s", exc)
                with self._lock:
                    self._last_error = f"Failed to update relay logic: {exc}"

    def get_status(self) -> dict[str, object]:
        with self._lock:
            settings = self._settings
            return {
                "available": self._available,
                "gpio_ready": self._gpio_ready,
                "fan_on": self._current_speed_percent > 0,
                "pin": settings.pin,
                "min_temp_c": settings.min_temp_c,
                "max_temp_c": settings.max_temp_c,
                "off_temp_c": settings.min_temp_c,
                "on_temp_c": settings.max_temp_c,
                "active_low": settings.active_low,
                "min_speed_percent": settings.min_speed_percent,
                "max_speed_percent": settings.max_speed_percent,
                "last_temp_c": self._last_temp_c,
                "current_speed_percent": self._current_speed_percent,
                "poll_interval_seconds": settings.poll_interval_seconds,
                "last_error": self._last_error,
            }

    def _setup_gpio(self) -> None:
        if GPIO is None:
            with self._lock:
                self._gpio_ready = False
                self._last_error = "RPi.GPIO module was not found."
            return

        try:
            with self._lock:
                settings = self._settings

            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(settings.pin, GPIO.OUT, initial=self._relay_output_level(settings, turn_on=False))
            with self._lock:
                self._gpio_ready = True
                self._last_error = None
        except Exception as exc:
            LOGGER.exception("GPIO setup failed: %s", exc)
            with self._lock:
                self._gpio_ready = False
                self._current_speed_percent = 0
                self._last_error = f"GPIO setup failed: {exc}"

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            temp_c = self._read_cpu_temp_c()
            if temp_c is not None:
                self._apply_temperature(temp_c)

            poll_interval = self.get_status()["poll_interval_seconds"]
            self._stop_event.wait(max(2, int(poll_interval)))

    def _read_cpu_temp_c(self) -> float | None:
        try:
            raw = CPU_TEMP_PATH.read_text(encoding="utf-8").strip()
            temp_c = round(int(raw) / 1000.0, 2)
            with self._lock:
                self._last_temp_c = temp_c
                if self._last_error == "CPU temperature could not be read.":
                    self._last_error = None
            return temp_c
        except Exception:
            with self._lock:
                self._last_temp_c = None
                if self._last_error is None:
                    self._last_error = "CPU temperature could not be read."
            return None

    def _apply_temperature(self, temp_c: float) -> None:
        with self._lock:
            settings = self._settings
            current_speed_percent = self._current_speed_percent

        desired_speed = self._calculate_speed(temp_c, settings, currently_on=current_speed_percent > 0)
        if desired_speed == current_speed_percent:
            return

        if GPIO is None or not self._gpio_ready:
            with self._lock:
                self._current_speed_percent = desired_speed
            return

        try:
            self._write_output(settings, turn_on=desired_speed > 0)
            with self._lock:
                self._current_speed_percent = desired_speed
                self._last_error = None
        except Exception as exc:
            LOGGER.exception("Failed to update relay output: %s", exc)
            with self._lock:
                self._last_error = f"Failed to update relay output: {exc}"

    def _calculate_speed(self, temp_c: float, settings: FanSettings, *, currently_on: bool) -> int:
        if temp_c <= settings.min_temp_c:
            return 0
        if temp_c >= settings.max_temp_c:
            return 100
        return 100 if currently_on else 0

    def _write_output(self, settings: FanSettings, *, turn_on: bool) -> None:
        if GPIO is None:
            return
        GPIO.output(settings.pin, self._relay_output_level(settings, turn_on=turn_on))

    def _relay_output_level(self, settings: FanSettings, *, turn_on: bool) -> int:
        if GPIO is None:
            return 0
        if turn_on:
            return GPIO.LOW if settings.active_low else GPIO.HIGH
        return GPIO.HIGH if settings.active_low else GPIO.LOW
