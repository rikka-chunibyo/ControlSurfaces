import unittest

from obscontrol.engine import ControllerEngine
from obscontrol.models import AppConfig, LedRule, ObsState


class FakePanels:
    def __init__(self):
        self.desired = None

    def sync_leds(self, desired):
        self.desired = desired


class FeedbackTests(unittest.TestCase):
    def test_independent_rules_combine_and_support_rich_state(self):
        config = AppConfig(led_rules=[
            LedRule(panel_id="p", led="FADE", condition="recording"),
            LedRule(panel_id="p", led="FX_BUTTON", condition="source_visible",
                    params={"scene": "Main", "source": "Logo"}),
            LedRule(panel_id="p", led="TAKE_ALL", condition="input_muted",
                    params={"input": "Mic"}, invert=True),
        ])
        engine = ControllerEngine(config)
        fake = FakePanels(); engine.panels = fake
        engine.state = ObsState(recording=True, input_mutes=(("Mic", False),),
                                scene_items=(("Main", "Logo", True),))
        try:
            engine._sync_feedback()
        finally:
            engine._executor.shutdown(wait=False, cancel_futures=True)
        self.assertEqual(fake.desired, {
            "p": {"FADE", "FX_BUTTON", "TAKE_ALL"},
        })
