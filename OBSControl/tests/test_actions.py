import unittest

from obscontrol.actions import execute_action
from obscontrol.models import ActionSpec


class FakeObs:
    def __init__(self):
        self.calls = []
        self.monitor_type = "OBS_MONITORING_TYPE_NONE"
        self.volume_db = -6.0

    def call(self, request_type, data=None):
        self.calls.append((request_type, data))
        if request_type == "GetSceneItemId":
            return {"sceneItemId": 17}
        if request_type == "GetSceneItemEnabled":
            return {"sceneItemEnabled": False}
        if request_type == "GetStudioModeEnabled":
            return {"studioModeEnabled": True}
        if request_type == "GetCurrentPreviewScene":
            return {"currentPreviewSceneName": "Preview"}
        if request_type == "GetCurrentProgramScene":
            return {"currentProgramSceneName": "Program"}
        if request_type == "GetInputAudioMonitorType":
            return {"monitorType": self.monitor_type}
        if request_type == "GetInputVolume":
            return {"inputVolumeDb": self.volume_db, "inputVolumeMul": 0.5}
        return {}


class ActionTests(unittest.TestCase):
    def test_tbar_resolves_event_position_and_clamps(self):
        obs = FakeObs()
        execute_action(obs, ActionSpec("set_tbar_position", {
            "position": "$event.position", "release": "$event.at_endpoint",
        }), {"position": 1.25, "at_endpoint": True})
        self.assertEqual(obs.calls, [("SetTBarPosition", {"position": 1.0, "release": True})])

    def test_source_visibility(self):
        for kind, expected in (("show_source", True), ("hide_source", False)):
            with self.subTest(kind=kind):
                obs = FakeObs()
                execute_action(obs, ActionSpec(kind, {"scene": "Camera", "source": "Face"}), {})
                self.assertEqual(obs.calls[-1], (
                    "SetSceneItemEnabled",
                    {"sceneName": "Camera", "sceneItemId": 17, "sceneItemEnabled": expected},
                ))

    def test_toggle_visibility_reads_current_state(self):
        obs = FakeObs()
        execute_action(obs, ActionSpec("toggle_source_visibility", {"scene": "Camera", "source": "Face"}), {})
        self.assertEqual([call[0] for call in obs.calls], [
            "GetSceneItemId", "GetSceneItemEnabled", "SetSceneItemEnabled",
        ])
        self.assertIs(obs.calls[-1][1]["sceneItemEnabled"], True)

    def test_raw_request_accepts_json_data(self):
        obs = FakeObs()
        execute_action(obs, ActionSpec("raw_request", {
            "request_type": "GetSceneList", "request_data": '{"vendor": true}',
        }), {})
        self.assertEqual(obs.calls, [("GetSceneList", {"vendor": True})])

    def test_native_toggle_requests(self):
        requests = {
            "toggle_record": "ToggleRecord",
            "toggle_stream": "ToggleStream",
            "toggle_virtual_camera": "ToggleVirtualCam",
            "toggle_replay_buffer": "ToggleReplayBuffer",
        }
        for action, request in requests.items():
            with self.subTest(action=action):
                obs = FakeObs()
                execute_action(obs, ActionSpec(action), {})
                self.assertEqual(obs.calls, [(request, None)])

    def test_studio_mode_toggle_reads_then_inverts(self):
        obs = FakeObs()
        execute_action(obs, ActionSpec("toggle_studio_mode"), {})
        self.assertEqual(obs.calls, [
            ("GetStudioModeEnabled", None),
            ("SetStudioModeEnabled", {"studioModeEnabled": False}),
        ])

    def test_boolean_mode_is_part_of_one_action(self):
        obs = FakeObs()
        execute_action(obs, ActionSpec("set_mute", {"input": "Mic", "mode": "toggle"}), {})
        execute_action(obs, ActionSpec("set_mute", {"input": "Mic", "mode": "off"}), {})
        execute_action(obs, ActionSpec("recording", {"mode": "on"}), {})
        self.assertEqual(obs.calls, [
            ("ToggleInputMute", {"inputName": "Mic"}),
            ("SetInputMute", {"inputName": "Mic", "inputMuted": False}),
            ("StartRecord", None),
        ])

    def test_input_volume_changes_current_level_by_relative_dial_steps(self):
        obs = FakeObs()
        execute_action(obs, ActionSpec("set_input_volume", {
            "input": "Mic", "mode": "relative", "step_db": 1.5, "max_db": 0,
        }), {"delta": 2})
        self.assertEqual(obs.calls, [
            ("GetInputVolume", {"inputName": "Mic"}),
            ("SetInputVolume", {"inputName": "Mic", "inputVolumeDb": -3.0}),
        ])

    def test_legacy_dial_volume_mapping_automatically_becomes_relative(self):
        obs = FakeObs()
        execute_action(obs, ActionSpec("set_input_volume", {
            "input": "Mic", "volume": "$event.volume", "multiplier": 4,
        }), {"delta": 2})
        self.assertEqual(obs.calls[-1], (
            "SetInputVolume", {"inputName": "Mic", "inputVolumeDb": -4.0},
        ))

    def test_input_volume_respects_the_configured_maximum(self):
        obs = FakeObs(); obs.volume_db = -1.0
        execute_action(obs, ActionSpec("set_input_volume", {
            "input": "Mic", "mode": "relative", "step_db": 2, "min_db": -20, "max_db": 0,
        }), {"delta": 1})
        self.assertEqual(obs.calls[-1], (
            "SetInputVolume", {"inputName": "Mic", "inputVolumeDb": 0.0},
        ))

    def test_input_volume_respects_the_configured_minimum(self):
        obs = FakeObs(); obs.volume_db = -19.0
        execute_action(obs, ActionSpec("set_input_volume", {
            "input": "Mic", "mode": "relative", "step_db": 2, "min_db": -20, "max_db": 0,
        }), {"delta": -1})
        self.assertEqual(obs.calls[-1], (
            "SetInputVolume", {"inputName": "Mic", "inputVolumeDb": -20.0},
        ))

    def test_input_volume_ignores_the_first_dial_position_without_a_delta(self):
        obs = FakeObs()
        execute_action(obs, ActionSpec("set_input_volume", {
            "input": "Mic", "mode": "relative",
        }), {"delta": 0})
        self.assertEqual(obs.calls, [])

    def test_input_volume_is_limited_to_obs_range(self):
        obs = FakeObs()
        execute_action(obs, ActionSpec("set_input_volume", {
            "input": "Mic", "volume": 50,
        }), {})
        self.assertEqual(obs.calls, [(
            "SetInputVolume", {"inputName": "Mic", "inputVolumeMul": 20.0},
        )])

    def test_input_monitoring_toggle_enables_and_disables_monitor_only(self):
        obs = FakeObs()
        action = ActionSpec("set_input_monitoring", {"input": "Mic", "mode": "toggle"})
        execute_action(obs, action, {})
        self.assertEqual(obs.calls, [
            ("GetInputAudioMonitorType", {"inputName": "Mic"}),
            ("SetInputAudioMonitorType", {
                "inputName": "Mic", "monitorType": "OBS_MONITORING_TYPE_MONITOR_ONLY",
            }),
        ])
        obs.calls.clear(); obs.monitor_type = "OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT"
        execute_action(obs, action, {})
        self.assertEqual(obs.calls[-1], ("SetInputAudioMonitorType", {
            "inputName": "Mic", "monitorType": "OBS_MONITORING_TYPE_NONE",
        }))

    def test_input_monitoring_accepts_explicit_mode(self):
        obs = FakeObs()
        execute_action(obs, ActionSpec("set_input_monitoring", {
            "input": "Mic", "mode": "monitor and output",
        }), {})
        self.assertEqual(obs.calls, [(
            "SetInputAudioMonitorType", {
                "inputName": "Mic",
                "monitorType": "OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT",
            },
        )])

    def test_trigger_transition_selects_transition_first(self):
        obs = FakeObs()
        execute_action(obs, ActionSpec("trigger_transition", {
            "scene": "BRB", "transition": "Fade", "duration_ms": 450,
        }), {})
        self.assertEqual(obs.calls, [
            ("GetStudioModeEnabled", None),
            ("GetCurrentProgramScene", None),
            ("SetCurrentPreviewScene", {"sceneName": "BRB"}),
            ("SetCurrentSceneTransition", {"transitionName": "Fade"}),
            ("SetCurrentSceneTransitionDuration", {"transitionDuration": 450}),
            ("TriggerStudioModeTransition", None),
        ])

    def test_transition_current_preview_leaves_preview_unchanged(self):
        obs = FakeObs()
        execute_action(obs, ActionSpec("transition_preview", {"transition": "Cut"}), {})
        self.assertEqual(obs.calls, [
            ("GetStudioModeEnabled", None),
            ("GetCurrentPreviewScene", None),
            ("GetCurrentProgramScene", None),
            ("SetCurrentSceneTransition", {"transitionName": "Cut"}),
            ("TriggerStudioModeTransition", None),
        ])

    def test_unknown_action_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown action kind"):
            execute_action(FakeObs(), ActionSpec("explode"), {})
