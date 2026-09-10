import unittest

from obscontrol.panels import (
    display_control_name, input_control_names, led_control_names, triggers_for_control,
)


class PanelMetadataTests(unittest.TestCase):
    def test_output_only_leds_are_not_mapping_inputs(self):
        self.assertIn("TBAR", input_control_names("lc11"))
        self.assertNotIn("TBAR_LED_TOP", input_control_names("lc11"))
        self.assertIn("TBAR_LED_TOP", led_control_names("lc11"))

    def test_lc11_ddr_and_text_bus_buttons_are_available_as_leds(self):
        leds = led_control_names("lc11")
        for row in ("EFFECTS", "LIVE", "PREVIEW"):
            for control in ("DDR1", "DDR2", "TXT"):
                with self.subTest(control=f"{row}_{control}"):
                    self.assertIn(f"{row}_{control}", leds)

    def test_led_selector_labels_keep_physical_row_context(self):
        self.assertEqual(display_control_name("LIVE_DDR1"), "Live row — DDR 1 [LIVE_DDR1]")
        self.assertEqual(display_control_name("FX_BUTTON"), "Transition — FX [FX_BUTTON]")
        self.assertEqual(display_control_name("TBAR_LED_TOP"), "Transition — T-bar LED top [TBAR_LED_TOP]")
        self.assertEqual(display_control_name("EXT_OVERLAY"), "Overlay — EXT [EXT_OVERLAY]")

    def test_triggers_follow_control_event_type(self):
        self.assertEqual(triggers_for_control("lc11", "TBAR"), ("change", "top", "bottom"))
        self.assertEqual(triggers_for_control("lc11", "TBAR_LED_TOP"), ())
