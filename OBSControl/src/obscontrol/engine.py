from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from control_surfaces import ButtonEvent, DialEvent, JoystickEvent, TBarEvent

from .actions import execute_action
from .config import local_obs_connection
from .models import AppConfig, Mapping, ObsState
from .obs_client import ObsClient
from .panels import PanelManager

log = logging.getLogger(__name__)


class ControllerEngine:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.obs = ObsClient()
        self.panels = PanelManager()
        self.state = ObsState()
        self._stop = threading.Event()
        self._refresh = threading.Event()
        self._obs_thread: threading.Thread | None = None
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="OBS action")
        self._analog_lock = threading.Lock()
        self._analog_pending: dict[str, tuple[Mapping, dict]] = {}
        self._analog_running: set[str] = set()
        self._dial_values: dict[tuple[str, str], int] = {}
        self._log_callbacks: list[Callable[[str, str], None]] = []
        self._state_callbacks: list[Callable[[ObsState], None]] = []
        self._panel_callbacks: list[Callable[[str, str], None]] = []
        self._config_lock = threading.RLock()

        self.obs.on_event(self._on_obs_event)
        self.obs.on_disconnect(lambda error: self._refresh.set())
        self.panels.on_event(self._on_panel_event)
        self.panels.on_status(
            lambda panel_id, event: self._notify_panel(panel_id, event.status.value)
        )
        self.panels.on_error(self._on_panel_error)

    def on_log(self, callback: Callable[[str, str], None]) -> Callable:
        self._log_callbacks.append(callback)
        return callback

    def on_state(self, callback: Callable[[ObsState], None]) -> Callable:
        self._state_callbacks.append(callback)
        return callback

    def on_panel_status(self, callback: Callable[[str, str], None]) -> Callable:
        self._panel_callbacks.append(callback)
        return callback

    def start(self) -> None:
        if self._obs_thread and self._obs_thread.is_alive():
            return
        self._stop.clear()
        self.panels.connect_all(self.config.panels)
        self._obs_thread = threading.Thread(
            target=self._obs_supervisor, name="OBS supervisor", daemon=True,
        )
        self._obs_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.obs.close()
        self.panels.disconnect_all()
        if self._obs_thread and self._obs_thread.is_alive():
            self._obs_thread.join(timeout=2.0)
        self._obs_thread = None
        self._executor.shutdown(wait=False, cancel_futures=True)

    def restart(self) -> None:
        self.obs.close()
        with self._analog_lock:
            self._dial_values.clear()
        self.panels.connect_all(self.config.panels)
        self._refresh.set()

    def poll_panels(self) -> None:
        self.panels.poll()

    def update_config(self, config: AppConfig) -> None:
        with self._config_lock:
            self.config = config
        self.panels.connect_all(config.panels)
        self.obs.close()
        self._refresh.set()

    def request_refresh(self) -> None:
        self._refresh.set()

    def _obs_supervisor(self) -> None:
        while not self._stop.is_set():
            if not self.obs.connected:
                try:
                    host, port, password = self._connection_values()
                    self._log("INFO", f"Connecting to OBS at {host}:{port}")
                    self.obs.connect(host, port, password)
                    self._log(
                        "INFO", f"Connected to OBS {self.obs.obs_version} "
                        f"(WebSocket {self.obs.websocket_version})",
                    )
                    self._refresh.set()
                except Exception as exc:
                    self._set_state(ObsState())
                    self._log("ERROR", f"OBS connection failed: {exc}")
                    self._stop.wait(self.config.obs.reconnect_interval)
                    continue
            if self._refresh.wait(5.0):
                self._refresh.clear()
            if self._stop.is_set():
                break
            if self.obs.connected:
                try:
                    self._refresh_state()
                except Exception as exc:
                    self._log("ERROR", f"OBS state refresh failed: {exc}")
                    self.obs.close()
        self._set_state(ObsState())

    def _connection_values(self) -> tuple[str, int, str]:
        settings = self.config.obs
        if settings.use_local_obs_config:
            local = local_obs_connection()
            if local:
                return local
        return settings.host, settings.port, settings.password

    def _refresh_state(self) -> None:
        version = self.obs.call("GetVersion")
        scene_data = self.obs.call("GetSceneList")
        transition_data = self.obs.call("GetSceneTransitionList")
        transition = self.obs.call("GetCurrentSceneTransition")
        inputs_data = self.obs.call("GetInputList")
        studio = self.obs.call("GetStudioModeEnabled")["studioModeEnabled"]
        program = self.obs.call("GetCurrentProgramScene").get("currentProgramSceneName", "")
        preview = ""
        if studio:
            preview = self.obs.call("GetCurrentPreviewScene").get("currentPreviewSceneName", "")
        inputs = tuple(item["inputName"] for item in inputs_data.get("inputs", []))
        mutes = []
        for name in inputs:
            try:
                muted = self.obs.call("GetInputMute", {"inputName": name})["inputMuted"]
                mutes.append((name, muted))
            except Exception:
                pass
        scene_items = []
        for scene in (item["sceneName"] for item in scene_data.get("scenes", [])):
            try:
                items = self.obs.call("GetSceneItemList", {"sceneName": scene}).get("sceneItems", [])
                scene_items.extend((scene, item["sourceName"], item["sceneItemEnabled"])
                                   for item in items)
            except Exception:
                pass
        def output_active(request: str, key: str) -> bool:
            try:
                return bool(self.obs.call(request).get(key, False))
            except Exception:
                return False
        state = ObsState(
            connected=True,
            obs_version=version.get("obsVersion", ""),
            websocket_version=version.get("obsWebSocketVersion", ""),
            scenes=tuple(item["sceneName"] for item in scene_data.get("scenes", [])),
            transitions=tuple(item["transitionName"]
                              for item in transition_data.get("transitions", [])),
            inputs=inputs,
            program_scene=program,
            preview_scene=preview,
            current_transition=transition_data.get("currentSceneTransitionName", ""),
            transition_duration=transition.get("transitionDuration"),
            studio_mode=studio,
            input_mutes=tuple(mutes),
            scene_items=tuple(scene_items),
            recording=output_active("GetRecordStatus", "outputActive"),
            streaming=output_active("GetStreamStatus", "outputActive"),
            virtual_camera=output_active("GetVirtualCamStatus", "outputActive"),
            replay_buffer=output_active("GetReplayBufferStatus", "outputActive"),
        )
        self._set_state(state)
        self._sync_feedback()

    def _set_state(self, state: ObsState) -> None:
        if state == self.state:
            return
        self.state = state
        for callback in tuple(self._state_callbacks):
            callback(state)

    def _on_obs_event(self, event_type: str, data: dict) -> None:
        self._log("OBS", event_type)
        self._refresh.set()

    def _on_panel_event(self, panel_id: str, event) -> None:
        if isinstance(event, ButtonEvent):
            detail = "pressed" if event.held else "released"
        elif isinstance(event, TBarEvent):
            detail = f"{event.position:.1%}"
        else:
            detail = str(getattr(event, "value", "changed"))
        with self._config_lock:
            mappings = [mapping for mapping in self.config.mappings
                        if mapping.enabled and mapping.panel_id == panel_id
                        and mapping.control == event.control
                        and self._matches_trigger(mapping, event)]
        self._log(
            "PANEL", f"{panel_id}: {event.control} {detail}"
            + (f" -> {len(mappings)} mapping(s)" if mappings else ""),
        )
        dial_delta = self._dial_delta(panel_id, event) if isinstance(event, DialEvent) else None
        for mapping in mappings:
            context = {
                "position": getattr(event, "position", None),
                "value": getattr(event, "value", None),
                "volume": (getattr(event, "value", 0) / 255.0
                           if isinstance(event, DialEvent) else None),
                "delta": dial_delta,
                "raw": getattr(event, "raw", None),
                "held": getattr(event, "held", None),
                "at_top": getattr(event, "at_top", False),
                "at_bottom": getattr(event, "at_bottom", False),
                "at_endpoint": (getattr(event, "at_top", False)
                                or getattr(event, "at_bottom", False)),
            }
            if isinstance(event, (TBarEvent, DialEvent, JoystickEvent)):
                self._submit_latest(mapping, context)
            else:
                self._executor.submit(self._run_mapping, mapping, context)

    def _submit_latest(self, mapping: Mapping, context: dict) -> None:
        """Coalesce analog input, while retaining every relative dial movement."""
        with self._analog_lock:
            previous = self._analog_pending.get(mapping.id)
            if previous and context.get("delta") is not None:
                context = dict(context)
                context["delta"] += previous[1].get("delta") or 0
            self._analog_pending[mapping.id] = (mapping, context)
            if mapping.id in self._analog_running:
                return
            self._analog_running.add(mapping.id)
        self._executor.submit(self._drain_latest, mapping.id)

    def _dial_delta(self, panel_id: str, event: DialEvent) -> int:
        """Find a signed encoder step, correctly handling the 0/255 wrap."""
        key = (panel_id, event.control)
        with self._analog_lock:
            previous = self._dial_values.get(key)
            self._dial_values[key] = event.value
        if previous is None:
            return 0
        delta = event.value - previous
        if delta > 127:
            return delta - 256
        if delta < -127:
            return delta + 256
        return delta

    def _drain_latest(self, mapping_id: str) -> None:
        while True:
            with self._analog_lock:
                item = self._analog_pending.pop(mapping_id, None)
                if item is None:
                    self._analog_running.discard(mapping_id)
                    return
            self._run_mapping(*item)

    @staticmethod
    def _matches_trigger(mapping: Mapping, event) -> bool:
        trigger = mapping.trigger
        if isinstance(event, ButtonEvent):
            return (trigger == "press" and event.held) or (trigger == "release" and not event.held)
        if isinstance(event, TBarEvent):
            return (trigger == "change" or
                    (trigger == "top" and event.at_top) or
                    (trigger == "bottom" and event.at_bottom))
        return trigger == "change" and isinstance(event, (DialEvent, JoystickEvent))

    def _run_mapping(self, mapping: Mapping, context: dict) -> None:
        if not self.obs.connected:
            self._log("ERROR", f"{mapping.name}: OBS is disconnected")
            return
        try:
            for action in mapping.actions:
                execute_action(self.obs, action, context)
            self._log("ACTION", mapping.name)
            self._refresh.set()
        except Exception as exc:
            self._log("ERROR", f"{mapping.name}: {exc}")

    def _sync_feedback(self) -> None:
        desired: dict[str, set[str]] = {}
        mute_map = self.state.mute_map
        scene_items = {(scene, source): enabled
                       for scene, source, enabled in self.state.scene_items}
        with self._config_lock:
            rules = tuple(self.config.led_rules)
        for rule in rules:
            if not rule.enabled:
                continue
            params = rule.params
            kind = rule.condition
            active = {
                "always": True,
                "obs_connected": self.state.connected,
                "program_scene": self.state.program_scene == params.get("scene"),
                "preview_scene": self.state.preview_scene == params.get("scene"),
                "current_transition": self.state.current_transition == params.get("transition"),
                "input_muted": mute_map.get(params.get("input", ""), False),
                "studio_mode": self.state.studio_mode,
                "source_visible": scene_items.get(
                    (params.get("scene", ""), params.get("source", "")), False,
                ),
                "recording": self.state.recording,
                "streaming": self.state.streaming,
                "virtual_camera": self.state.virtual_camera,
                "replay_buffer": self.state.replay_buffer,
            }.get(kind, False)
            if rule.invert:
                active = not active
            if active:
                desired.setdefault(rule.panel_id, set()).add(rule.led)
        self.panels.sync_leds(desired)

    def _on_panel_error(self, panel_id: str, event) -> None:
        error = getattr(event, "error", event)
        self._log("ERROR", f"Panel {panel_id}: {error}")

    def _notify_panel(self, panel_id: str, status: str) -> None:
        for callback in tuple(self._panel_callbacks):
            callback(panel_id, status)

    def _log(self, level: str, message: str) -> None:
        getattr(log, level.lower(), log.info)(message)
        for callback in tuple(self._log_callbacks):
            callback(level, message)
