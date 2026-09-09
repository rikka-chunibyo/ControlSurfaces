from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from control_surfaces import (
    Emits, LC11Surface, TriCasterSurface, find_port_by_serial, list_serial_ports,
)

from .models import PanelConfig

log = logging.getLogger(__name__)

SURFACE_CLASSES = {
    "lc11": LC11Surface,
    "tricaster": TriCasterSurface,
}


def control_catalog(device_type: str):
    cls = SURFACE_CLASSES[device_type]
    return cls("CATALOG").controls


def input_control_names(device_type: str) -> tuple[str, ...]:
    return tuple(sorted(name for name, control in control_catalog(device_type).items()
                        if control.emits != Emits.NONE))


def led_control_names(device_type: str) -> tuple[str, ...]:
    return tuple(sorted(name for name, control in control_catalog(device_type).items()
                        if control.has_led))


def triggers_for_control(device_type: str, name: str) -> tuple[str, ...]:
    control = control_catalog(device_type).get(name)
    if control is None:
        return ()
    triggers = []
    if Emits.BUTTON in control.emits:
        triggers.extend(("press", "release"))
    if Emits.DIAL in control.emits or Emits.JOYSTICK in control.emits:
        triggers.append("change")
    if Emits.TBAR in control.emits:
        triggers.extend(("change", "top", "bottom"))
    return tuple(dict.fromkeys(triggers))


@dataclass
class PanelRuntime:
    config: PanelConfig
    surface: object


class PanelManager:
    def __init__(self) -> None:
        self.runtimes: dict[str, PanelRuntime] = {}
        self._event_callbacks: list[Callable] = []
        self._status_callbacks: list[Callable] = []
        self._error_callbacks: list[Callable] = []

    @staticmethod
    def ports() -> list[dict]:
        return [{
            "port": item.device,
            "serial_number": item.serial_number or "",
            "description": item.description or "",
        } for item in list_serial_ports()]

    def on_event(self, callback: Callable) -> Callable:
        self._event_callbacks.append(callback)
        return callback

    def on_status(self, callback: Callable) -> Callable:
        self._status_callbacks.append(callback)
        return callback

    def on_error(self, callback: Callable) -> Callable:
        self._error_callbacks.append(callback)
        return callback

    def connect_all(self, configs: list[PanelConfig]) -> None:
        self.disconnect_all()
        for config in configs:
            if config.enabled:
                self.connect_panel(config)

    def connect_panel(self, config: PanelConfig) -> bool:
        port = (find_port_by_serial(config.serial_number)
                if config.serial_number else None) or config.port
        if not port:
            self._notify_error(config.id, RuntimeError("No serial port is configured"))
            return False
        cls = SURFACE_CLASSES.get(config.device_type)
        if cls is None:
            self._notify_error(config.id, ValueError(
                f"Unsupported panel type: {config.device_type}"
            ))
            return False
        surface = cls(
            port, auto_leds=False, threadsafe=True, reconnect=True,
            reconnect_interval=1.0,
        )
        surface.on_button(lambda event, pid=config.id: self._notify_event(pid, event))
        surface.on_dial(lambda event, pid=config.id: self._notify_event(pid, event))
        surface.on_tbar(lambda event, pid=config.id: self._notify_event(pid, event))
        surface.on_joystick(lambda event, pid=config.id: self._notify_event(pid, event))
        surface.on_connection(
            lambda event, pid=config.id: self._notify_status(pid, event)
        )
        surface.on_error(
            lambda event, pid=config.id: self._notify_error(pid, event)
        )
        try:
            surface.connect()
            surface.start()
        except Exception as exc:
            self._notify_error(config.id, exc)
            try:
                surface.disconnect()
            except Exception:
                pass
            return False
        config.port = port
        self.runtimes[config.id] = PanelRuntime(config, surface)
        return True

    def disconnect_all(self) -> None:
        runtimes, self.runtimes = self.runtimes, {}
        for runtime in runtimes.values():
            try:
                runtime.surface.disconnect()
            except Exception:
                log.exception("Failed to disconnect panel %s", runtime.config.name)

    def poll(self) -> None:
        for runtime in tuple(self.runtimes.values()):
            runtime.surface.poll()

    def sync_leds(self, desired: dict[str, set[str]]) -> None:
        for panel_id, runtime in tuple(self.runtimes.items()):
            surface = runtime.surface
            if not surface.is_connected:
                continue
            valid = {name for name in desired.get(panel_id, set())
                     if name in surface.controls and surface.controls[name].has_led}
            current = set(surface.state.lit)
            try:
                surface.clear(current - valid)
                surface.set(valid - current)
            except Exception as exc:
                self._notify_error(panel_id, exc)

    def status(self, panel_id: str) -> str:
        runtime = self.runtimes.get(panel_id)
        return runtime.surface.status.value if runtime else "disconnected"

    def _notify_event(self, panel_id: str, event) -> None:
        for callback in tuple(self._event_callbacks):
            callback(panel_id, event)

    def _notify_status(self, panel_id: str, event) -> None:
        for callback in tuple(self._status_callbacks):
            callback(panel_id, event)

    def _notify_error(self, panel_id: str, event) -> None:
        for callback in tuple(self._error_callbacks):
            callback(panel_id, event)
