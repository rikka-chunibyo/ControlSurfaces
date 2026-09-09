from __future__ import annotations

import json
import time

from .models import ActionSpec


ACTION_LABELS = {
    "set_preview_scene": "Select preview scene",
    "set_program_scene": "Switch program scene",
    "trigger_transition": "Transition to scene (Studio Mode)",
    "transition_preview": "Transition current Preview (Studio Mode)",
    "set_transition": "Select transition",
    "set_transition_duration": "Set transition duration",
    "set_tbar_position": "Move OBS T-bar",
    "set_mute": "Input mute",
    "set_input_volume": "Input volume",
    "set_input_monitoring": "Input monitoring",
    "set_source_visibility": "Scene source visibility",
    "media_action": "Control media input",
    "set_studio_mode": "Studio Mode",
    "recording": "Recording",
    "toggle_record_pause": "Pause/resume recording",
    "streaming": "Streaming",
    "virtual_camera": "Virtual camera",
    "replay_buffer": "Replay buffer",
    "save_replay_buffer": "Save replay buffer",
    "raw_request": "Advanced: raw OBS request",
}


def execute_action(client, action: ActionSpec, context: dict) -> None:
    if action.delay_ms:
        time.sleep(action.delay_ms / 1000.0)
    params = _resolve(dict(action.params), context)
    kind = action.kind

    if kind == "set_preview_scene":
        client.call("SetCurrentPreviewScene", {"sceneName": params["scene"]})
    elif kind == "set_program_scene":
        client.call("SetCurrentProgramScene", {"sceneName": params["scene"]})
    elif kind == "trigger_transition":
        if not client.call("GetStudioModeEnabled")["studioModeEnabled"]:
            raise RuntimeError("Studio Mode is off; no Preview transition can run")
        scene = params.get("scene")
        if scene:
            program = client.call("GetCurrentProgramScene").get("currentProgramSceneName")
            if scene == program:
                raise RuntimeError(f"{scene} is already in Program")
            client.call("SetCurrentPreviewScene", {"sceneName": scene})
        transition = params.get("transition")
        if transition:
            client.call("SetCurrentSceneTransition", {"transitionName": transition})
        duration = params.get("duration_ms")
        if duration:
            client.call("SetCurrentSceneTransitionDuration", {
                "transitionDuration": int(duration),
            })
        client.call("TriggerStudioModeTransition")
    elif kind == "transition_preview":
        if not client.call("GetStudioModeEnabled")["studioModeEnabled"]:
            raise RuntimeError("Studio Mode is off; no Preview transition can run")
        preview = client.call("GetCurrentPreviewScene").get("currentPreviewSceneName")
        program = client.call("GetCurrentProgramScene").get("currentProgramSceneName")
        if not preview:
            raise RuntimeError("OBS has no current Preview scene")
        if preview == program:
            raise RuntimeError(f"{preview} is already in Program; select a different Preview scene")
        client.call("SetCurrentSceneTransition", {
            "transitionName": params["transition"],
        })
        client.call("TriggerStudioModeTransition")
    elif kind == "set_transition":
        client.call("SetCurrentSceneTransition", {"transitionName": params["transition"]})
    elif kind == "set_transition_duration":
        client.call("SetCurrentSceneTransitionDuration", {
            "transitionDuration": int(params["duration_ms"]),
        })
    elif kind == "set_tbar_position":
        client.call("SetTBarPosition", {
            "position": max(0.0, min(1.0, float(params.get("position", 0)))),
            "release": bool(params.get("release", False)),
        })
    elif kind == "set_mute":
        mode = _mode(params, "muted")
        if mode == "toggle":
            client.call("ToggleInputMute", {"inputName": params["input"]})
        else:
            client.call("SetInputMute", {
                "inputName": params["input"], "inputMuted": mode == "on",
            })
    elif kind == "set_input_volume":
        # OBS uses a multiplier: 1.0 is unity gain (0 dB) and 20.0 is its
        # documented upper bound.  $event.volume is the LC-11 dial's
        # normalized 0.0--1.0 position, so the normal mapping never boosts.
        volume = max(0.0, min(20.0, float(params["volume"])))
        client.call("SetInputVolume", {
            "inputName": params["input"], "inputVolumeMul": volume,
        })
    elif kind == "set_input_monitoring":
        monitor_type = _monitor_type(client, params)
        client.call("SetInputAudioMonitorType", {
            "inputName": params["input"], "monitorType": monitor_type,
        })
    elif kind in ("toggle_source_visibility", "set_source_visibility", "show_source", "hide_source"):
        scene = params["scene"]
        item_id = client.call("GetSceneItemId", {
            "sceneName": scene, "sourceName": params["source"],
        })["sceneItemId"]
        legacy_modes = {"toggle_source_visibility": "toggle", "show_source": "on", "hide_source": "off"}
        mode = legacy_modes.get(kind, _mode(params, "enabled"))
        if mode == "toggle":
            current = client.call("GetSceneItemEnabled", {
                "sceneName": scene, "sceneItemId": item_id,
            })["sceneItemEnabled"]
            enabled = not current
        else:
            enabled = mode == "on"
        client.call("SetSceneItemEnabled", {
            "sceneName": scene, "sceneItemId": item_id,
            "sceneItemEnabled": enabled,
        })
    elif kind == "media_action":
        client.call("TriggerMediaInputAction", {
            "inputName": params["input"],
            "mediaAction": params.get("media_action", "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART"),
        })
    elif kind == "set_studio_mode":
        mode = _mode(params, "enabled")
        if mode == "toggle":
            enabled = client.call("GetStudioModeEnabled")["studioModeEnabled"]
            client.call("SetStudioModeEnabled", {"studioModeEnabled": not enabled})
        else:
            client.call("SetStudioModeEnabled", {"studioModeEnabled": mode == "on"})
    elif kind == "toggle_studio_mode":
        enabled = client.call("GetStudioModeEnabled")["studioModeEnabled"]
        client.call("SetStudioModeEnabled", {"studioModeEnabled": not enabled})
    elif kind == "toggle_record":
        client.call("ToggleRecord")
    elif kind == "start_record":
        client.call("StartRecord")
    elif kind == "stop_record":
        client.call("StopRecord")
    elif kind == "toggle_record_pause":
        client.call("ToggleRecordPause")
    elif kind == "toggle_stream":
        client.call("ToggleStream")
    elif kind == "start_stream":
        client.call("StartStream")
    elif kind == "stop_stream":
        client.call("StopStream")
    elif kind == "toggle_virtual_camera":
        client.call("ToggleVirtualCam")
    elif kind == "toggle_replay_buffer":
        client.call("ToggleReplayBuffer")
    elif kind in ("recording", "streaming", "virtual_camera", "replay_buffer"):
        requests = {
            "recording": {"toggle": "ToggleRecord", "on": "StartRecord", "off": "StopRecord"},
            "streaming": {"toggle": "ToggleStream", "on": "StartStream", "off": "StopStream"},
            "virtual_camera": {"toggle": "ToggleVirtualCam", "on": "StartVirtualCam", "off": "StopVirtualCam"},
            "replay_buffer": {"toggle": "ToggleReplayBuffer", "on": "StartReplayBuffer", "off": "StopReplayBuffer"},
        }
        client.call(requests[kind][_mode(params)])
    elif kind == "save_replay_buffer":
        client.call("SaveReplayBuffer")
    elif kind == "raw_request":
        data = params.get("request_data", {})
        if isinstance(data, str):
            data = json.loads(data) if data.strip() else None
        client.call(params["request_type"], data)
    else:
        raise ValueError(f"Unknown action kind: {kind}")


def _resolve(value, context):
    if isinstance(value, dict):
        return {key: _resolve(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve(item, context) for item in value]
    if isinstance(value, str) and value.startswith("$event."):
        return context.get(value[7:])
    return value


def _mode(params: dict, legacy_key: str | None = None) -> str:
    mode = params.get("mode")
    if mode in ("on", "off", "toggle"):
        return mode
    if legacy_key and legacy_key in params:
        return "on" if bool(params[legacy_key]) else "off"
    return "toggle"


def _monitor_type(client, params: dict) -> str:
    """Return OBS's monitor enum, with a useful on/off-style toggle."""
    mode = str(params.get("mode", "toggle")).lower().replace("_", " ")
    monitor_types = {
        "off": "OBS_MONITORING_TYPE_NONE",
        "monitor only": "OBS_MONITORING_TYPE_MONITOR_ONLY",
        "monitor and output": "OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT",
    }
    if mode in monitor_types:
        return monitor_types[mode]
    if mode != "toggle":
        raise ValueError(f"Unknown input monitoring mode: {params.get('mode')}")
    current = client.call("GetInputAudioMonitorType", {
        "inputName": params["input"],
    }).get("monitorType")
    # A toggle means enable/disable monitoring, rather than unexpectedly
    # changing an existing Monitor-and-Output route into Monitor Only.
    return ("OBS_MONITORING_TYPE_MONITOR_ONLY"
            if current == "OBS_MONITORING_TYPE_NONE"
            else "OBS_MONITORING_TYPE_NONE")
