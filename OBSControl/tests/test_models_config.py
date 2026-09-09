from pathlib import Path
import tempfile
import unittest

from obscontrol.config import load_config, save_config
from obscontrol.models import (
    ActionSpec,
    AppConfig,
    LedRule,
    Mapping,
    ObsSettings,
    PanelConfig,
)


class ConfigurationTests(unittest.TestCase):
    def test_configuration_round_trip(self):
        original = AppConfig(
            obs=ObsSettings(host="obs.local", port=4456, password="test", use_local_obs_config=False),
            panels=[PanelConfig(id="panel", name="LC-11", port="COM5")],
            mappings=[Mapping(
                id="mapping",
                name="Take",
                panel_id="panel",
                control="AUTO",
                actions=[ActionSpec("trigger_transition", delay_ms=25)],
            )],
            led_rules=[LedRule(id="led", name="Connected", panel_id="panel",
                               led="FADE", condition="obs_connected")],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings" / "config.json"
            save_config(original, path)
            self.assertEqual(load_config(path).to_dict(), original.to_dict())

    def test_missing_configuration_uses_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(Path(directory) / "missing.json")
        self.assertEqual(config.obs.port, 4455)
        self.assertEqual(config.panels, [])
        self.assertEqual(config.mappings, [])

    def test_legacy_feedback_and_actions_are_migrated(self):
        config = AppConfig.from_dict({
            "mappings": [{
                "id": "m", "name": "Mute", "panel_id": "p", "control": "FADE",
                "actions": [{"kind": "toggle_mute", "params": {"input": "Mic"}}],
                "feedback": {"kind": "input_muted", "params": {"input": "Mic"}},
            }],
        })
        self.assertEqual(config.mappings[0].actions[0].kind, "set_mute")
        self.assertEqual(config.mappings[0].actions[0].params["mode"], "toggle")
        self.assertEqual(config.led_rules[0].led, "FADE")
        self.assertEqual(config.led_rules[0].condition, "input_muted")
