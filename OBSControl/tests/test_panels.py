import unittest

from obscontrol.panels import input_control_names, led_control_names, triggers_for_control


class PanelMetadataTests(unittest.TestCase):
    def test_output_only_leds_are_not_mapping_inputs(self):
        self.assertIn("TBAR", input_control_names("lc11"))
        self.assertNotIn("TBAR_LED_TOP", input_control_names("lc11"))
        self.assertIn("TBAR_LED_TOP", led_control_names("lc11"))

    def test_triggers_follow_control_event_type(self):
        self.assertEqual(triggers_for_control("lc11", "TBAR"), ("change", "top", "bottom"))
        self.assertEqual(triggers_for_control("lc11", "TBAR_LED_TOP"), ())
