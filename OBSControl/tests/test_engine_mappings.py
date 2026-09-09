import time
import unittest

from control_surfaces import ButtonEvent, DialEvent

from obscontrol.engine import ControllerEngine
from obscontrol.models import ActionSpec, AppConfig, Mapping


class FakeObs:
    connected = True

    def __init__(self):
        self.calls = []

    def call(self, request_type, data=None):
        self.calls.append((request_type, data))
        if request_type == "GetStudioModeEnabled":
            return {"studioModeEnabled": True}
        if request_type == "GetCurrentPreviewScene":
            return {"currentPreviewSceneName": "Scene 2"}
        if request_type == "GetCurrentProgramScene":
            return {"currentProgramSceneName": "Scene 1"}
        return {}


class MappingDispatchTests(unittest.TestCase):
    def test_auto_press_dispatches_saved_fade_mapping_once(self):
        mapping = Mapping(
            id="auto", panel_id="panel", control="AUTO", trigger="press",
            actions=[ActionSpec("transition_preview", {"transition": "Fade"})],
        )
        engine = ControllerEngine(AppConfig(mappings=[mapping]))
        fake = FakeObs(); engine.obs = fake
        try:
            engine._on_panel_event("panel", ButtonEvent("AUTO", True))
            engine._on_panel_event("panel", ButtonEvent("AUTO", False))
            deadline = time.monotonic() + 1
            while not any(call[0] == "TriggerStudioModeTransition" for call in fake.calls):
                if time.monotonic() >= deadline:
                    self.fail("AUTO mapping did not reach OBS")
                time.sleep(0.005)
        finally:
            engine._executor.shutdown(wait=True, cancel_futures=True)
        self.assertEqual(
            [call for call in fake.calls if call[0] == "TriggerStudioModeTransition"],
            [("TriggerStudioModeTransition", None)],
        )

    def test_dial_change_resolves_normalized_volume(self):
        mapping = Mapping(
            id="volume", panel_id="panel", control="SPEED", trigger="change",
            actions=[ActionSpec("set_input_volume", {
                "input": "Mic", "volume": "$event.volume",
            })],
        )
        engine = ControllerEngine(AppConfig(mappings=[mapping]))
        fake = FakeObs(); engine.obs = fake
        try:
            engine._on_panel_event("panel", DialEvent("SPEED", 128))
            deadline = time.monotonic() + 1
            while not any(call[0] == "SetInputVolume" for call in fake.calls):
                if time.monotonic() >= deadline:
                    self.fail("Dial mapping did not set input volume")
                time.sleep(0.005)
        finally:
            engine._executor.shutdown(wait=True, cancel_futures=True)
        self.assertEqual(fake.calls[-1], (
            "SetInputVolume", {"inputName": "Mic", "inputVolumeMul": 128 / 255},
        ))
