import unittest

from control_surfaces.devices.lc11 import LC11Surface
from control_surfaces.devices.tricaster import TriCasterSurface


class BufferedSerial:
    def __init__(self):
        self.data = bytearray()

    @property
    def in_waiting(self):
        return len(self.data)

    def feed(self, data: bytes):
        self.data.extend(data)

    def read(self, size: int):
        result = bytes(self.data[:size])
        del self.data[:size]
        return result


class TriCasterFramingTests(unittest.TestCase):
    def setUp(self):
        self.surface = TriCasterSurface('TEST')
        self.serial = BufferedSerial()
        self.surface._ser = self.serial

    def test_frame_survives_arbitrary_read_boundary(self):
        self.serial.feed(b'~4')
        self.assertEqual(self.surface._read_frames(), [])
        self.serial.feed(b'7F\r')
        self.assertEqual(self.surface._read_frames(), [('4', 0x7F)])

    def test_noise_and_multiple_frames_resynchronise(self):
        self.serial.feed(b'junk~4GG\r~201\r~5FE\r')
        self.assertEqual(
            self.surface._read_frames(),
            [('2', 0x01), ('5', 0xFE)],
        )


class LC11FramingTests(unittest.TestCase):
    def setUp(self):
        self.surface = LC11Surface('TEST')
        self.serial = BufferedSerial()
        self.surface._ser = self.serial

    def test_split_bus_row_survives_read_boundary(self):
        self.serial.feed(b'~FFF\r')
        self.assertEqual(self.surface._read_messages(), [])
        self.serial.feed(b'7\r~47F\r')
        self.assertEqual(self.surface._read_messages(), ['~FFF7', '~47F'])

    def test_bad_row_continuation_does_not_consume_next_frame(self):
        self.serial.feed(b'~FFF\r~47F\r')
        self.assertEqual(self.surface._read_messages(), ['~47F'])

    def test_tbar_requires_exact_byte_payload(self):
        seen = []
        self.surface.on_tbar(seen.append)
        self.surface._dispatch('~4FFF')
        self.assertEqual(seen, [])

    def test_auto_button_emits_press_and_release(self):
        seen = []
        self.surface.on_button(lambda event: seen.append((event.control, event.held)))
        self.surface._dispatch('~3FD')
        self.surface._dispatch('~3FF')
        self.assertEqual(seen, [('AUTO', True), ('AUTO', False)])

    def test_isolated_endpoint_spikes_are_suppressed(self):
        seen = []
        self.surface.on_tbar(lambda event: seen.append(event.raw))
        self.surface._emit_confirmed_tbar(0xFF)
        self.surface._emit_confirmed_tbar(0xBE)
        self.surface._emit_confirmed_tbar(0xFF)
        self.surface._emit_confirmed_tbar(0xFD)
        self.assertEqual(seen, [0xBE, 0xFD])

    def test_single_stationary_endpoint_is_delivered_after_settle(self):
        seen = []
        self.surface.on_tbar(lambda event: seen.append(event.raw))
        self.surface._emit_confirmed_tbar(0xFF)
        self.assertEqual(seen, [])
        self.surface._pending_endpoint_since -= 1.0
        self.surface._flush_pending_tbar()
        self.assertEqual(seen, [0xFF])


if __name__ == '__main__':
    unittest.main()
