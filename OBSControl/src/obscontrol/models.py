from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
import uuid


def new_id() -> str:
    return str(uuid.uuid4())[:8]


@dataclass
class ObsSettings:
    host: str = "127.0.0.1"
    port: int = 4455
    password: str = ""
    use_local_obs_config: bool = True
    reconnect_interval: float = 2.0


@dataclass
class PanelConfig:
    id: str = field(default_factory=new_id)
    name: str = "Control Surface"
    device_type: str = "lc11"
    serial_number: str = ""
    port: str = ""
    enabled: bool = True

    @property
    def stable_id(self) -> str:
        return self.serial_number or self.port or self.id


@dataclass
class ActionSpec:
    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    delay_ms: int = 0


@dataclass
class FeedbackSpec:
    kind: str = "none"
    params: dict[str, Any] = field(default_factory=dict)
    invert: bool = False


@dataclass
class LedRule:
    id: str = field(default_factory=new_id)
    name: str = "New LED rule"
    panel_id: str = ""
    led: str = ""
    condition: str = "obs_connected"
    params: dict[str, Any] = field(default_factory=dict)
    invert: bool = False
    enabled: bool = True


@dataclass
class Mapping:
    id: str = field(default_factory=new_id)
    name: str = "New mapping"
    panel_id: str = ""
    control: str = ""
    trigger: str = "press"
    actions: list[ActionSpec] = field(default_factory=list)
    feedback: FeedbackSpec = field(default_factory=FeedbackSpec)
    enabled: bool = True


@dataclass
class AppConfig:
    obs: ObsSettings = field(default_factory=ObsSettings)
    panels: list[PanelConfig] = field(default_factory=list)
    mappings: list[Mapping] = field(default_factory=list)
    led_rules: list[LedRule] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AppConfig":
        obs = ObsSettings(**raw.get("obs", {}))
        panels = [PanelConfig(**item) for item in raw.get("panels", [])]
        mappings = []
        migrated_led_rules = []
        for item in raw.get("mappings", []):
            actions = [_normalized_action(ActionSpec(**action))
                       for action in item.get("actions", [])]
            feedback = FeedbackSpec(**item.get("feedback", {}))
            values = {key: value for key, value in item.items()
                      if key not in ("actions", "feedback")}
            mapping = Mapping(**values, actions=actions, feedback=FeedbackSpec())
            mappings.append(mapping)
            if feedback.kind != "none":
                migrated_led_rules.append(LedRule(
                    name=f"{mapping.name} LED", panel_id=mapping.panel_id,
                    led=mapping.control, condition=feedback.kind,
                    params=feedback.params, invert=feedback.invert,
                ))
        led_rules = [LedRule(**item) for item in raw.get("led_rules", [])]
        return cls(obs=obs, panels=panels, mappings=mappings,
                   led_rules=led_rules + migrated_led_rules)


@dataclass(frozen=True)
class ObsState:
    connected: bool = False
    obs_version: str = ""
    websocket_version: str = ""
    scenes: tuple[str, ...] = ()
    transitions: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    program_scene: str = ""
    preview_scene: str = ""
    current_transition: str = ""
    transition_duration: int | None = None
    studio_mode: bool = False
    input_mutes: tuple[tuple[str, bool], ...] = ()
    scene_items: tuple[tuple[str, str, bool], ...] = ()
    recording: bool = False
    streaming: bool = False
    virtual_camera: bool = False
    replay_buffer: bool = False

    @property
    def mute_map(self) -> dict[str, bool]:
        return dict(self.input_mutes)

    @property
    def scene_item_names(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item[1] for item in self.scene_items))


def _normalized_action(action: ActionSpec) -> ActionSpec:
    """Upgrade 0.1.x's separate on/off/toggle action names in memory."""
    kind, params = action.kind, dict(action.params)
    if kind == "set_tbar_position" and "release" not in params:
        params["release"] = "$event.at_endpoint"
    if kind == "toggle_mute":
        kind, params["mode"] = "set_mute", "toggle"
    elif kind == "set_mute" and "mode" not in params:
        params["mode"] = "on" if params.pop("muted", True) else "off"
    elif kind in ("toggle_source_visibility", "show_source", "hide_source"):
        mode = {"toggle_source_visibility": "toggle", "show_source": "on", "hide_source": "off"}[kind]
        kind, params["mode"] = "set_source_visibility", mode
    elif kind == "set_source_visibility" and "mode" not in params:
        params["mode"] = "on" if params.pop("enabled", True) else "off"
    elif kind in ("toggle_studio_mode", "set_studio_mode"):
        if kind == "toggle_studio_mode":
            mode = "toggle"
        else:
            mode = "on" if params.pop("enabled", True) else "off"
        kind, params["mode"] = "set_studio_mode", mode
    else:
        groups = {
            "recording": ("toggle_record", "start_record", "stop_record"),
            "streaming": ("toggle_stream", "start_stream", "stop_stream"),
            "virtual_camera": ("toggle_virtual_camera", "start_virtual_camera", "stop_virtual_camera"),
            "replay_buffer": ("toggle_replay_buffer", "start_replay_buffer", "stop_replay_buffer"),
        }
        for replacement, variants in groups.items():
            if kind in variants:
                params["mode"] = ("toggle" if kind == variants[0]
                                  else "on" if kind == variants[1] else "off")
                kind = replacement
                break
    return ActionSpec(kind, params, action.delay_ms)
