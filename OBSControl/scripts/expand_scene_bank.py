"""Expand the saved LC-11 scene bank mappings and LEDs to numbered scenes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT.parent / "ControlSurfaces"))

from obscontrol.config import default_config_path, load_config, save_config
from obscontrol.models import ActionSpec, LedRule, Mapping, new_id


def expand(count: int = 6) -> tuple[Path, int, int]:
    path = default_config_path()
    config = load_config(path)
    panel = next((item for item in config.panels if item.device_type == "lc11"), None)
    if panel is None:
        raise RuntimeError("The saved configuration has no LC-11 panel.")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"config.before-scenes-1-{count}.{timestamp}.json")
    shutil.copy2(path, backup)

    def mapping_for(control: str, action_kind: str):
        return next((item for item in config.mappings
                     if item.panel_id == panel.id and item.control == control
                     and any(action.kind == action_kind for action in item.actions)), None)

    def rule_for(led: str, condition: str):
        return next((item for item in config.led_rules
                     if item.panel_id == panel.id and item.led == led
                     and item.condition == condition), None)

    for number in range(1, count + 1):
        scene = f"Scene {number}"

        preview_control = f"PREVIEW_{number}"
        preview = mapping_for(preview_control, "set_preview_scene")
        if preview is None:
            preview = Mapping(id=new_id(), panel_id=panel.id, control=preview_control)
            config.mappings.append(preview)
        preview.name = f"Select {scene}"
        preview.trigger = "press"
        preview.enabled = True
        preview.actions = [ActionSpec("set_preview_scene", {"scene": scene})]

        live_control = f"LIVE_{number}"
        live = mapping_for(live_control, "trigger_transition")
        if live is None:
            live = Mapping(id=new_id(), panel_id=panel.id, control=live_control)
            config.mappings.append(live)
        live.name = f"Fade to {scene}"
        live.trigger = "press"
        live.enabled = True
        live.actions = [ActionSpec("trigger_transition", {
            "scene": scene, "transition": "Fade",
        })]

        preview_rule = rule_for(preview_control, "preview_scene")
        if preview_rule is None:
            preview_rule = LedRule(id=new_id(), panel_id=panel.id, led=preview_control)
            config.led_rules.append(preview_rule)
        preview_rule.name = f"{scene} Preview"
        preview_rule.condition = "preview_scene"
        preview_rule.params = {"scene": scene}
        preview_rule.invert = False
        preview_rule.enabled = True

        live_rule = rule_for(live_control, "program_scene")
        if live_rule is None:
            live_rule = LedRule(id=new_id(), panel_id=panel.id, led=live_control)
            config.led_rules.append(live_rule)
        live_rule.name = f"{scene} Live"
        live_rule.condition = "program_scene"
        live_rule.params = {"scene": scene}
        live_rule.invert = False
        live_rule.enabled = True

    save_config(config, path)
    return backup, len(config.mappings), len(config.led_rules)


if __name__ == "__main__":
    backup_path, mappings, led_rules = expand()
    print(f"Backup: {backup_path}")
    print(f"Saved: {mappings} mappings, {led_rules} LED rules")
