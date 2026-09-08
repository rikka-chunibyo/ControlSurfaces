import unittest
import threading

from control_surfaces import ConnectionStatus
from control_surfaces.control import Control, Emits
from control_surfaces.led_bank import LEDBank
from control_surfaces.surface import ControlSurface


class DummySurface(ControlSurface):
    def __init__(self, *, threadsafe=False, reconnect=False,
                 reconnect_interval=1.0):
        controls = {'A': Control('A', Emits.BUTTON, True)}
        super().__init__(
            'TEST', 1, controls, threadsafe=threadsafe,
            reconnect=reconnect, reconnect_interval=reconnect_interval,
            poll_interval=0.001,
        )
        self.writes = []
        self.closed = False
        self.open_count = 0

    def _open(self):
        self.closed = False
        self.open_count += 1

    def _close(self):
        self.closed = True

    def _poll(self):
        pass

    def _write_led(self, name, on):
        self.writes.append((name, on))


class SurfaceLifecycleTests(unittest.TestCase):
    def test_connect_forces_hardware_outputs_off(self):
        surface = DummySurface()
        statuses = []
        surface.on_connection(lambda event: statuses.append(event.status))
        surface.connect()
        self.assertEqual(surface.writes, [('A', False)])
        self.assertTrue(surface.is_connected)
        self.assertEqual(surface.status, ConnectionStatus.CONNECTED)
        self.assertEqual(
            statuses,
            [ConnectionStatus.CONNECTING, ConnectionStatus.CONNECTED],
        )
        surface.disconnect()

    def test_state_includes_runtime_status(self):
        surface = DummySurface()
        self.assertFalse(surface.state.connected)
        surface.connect()
        self.assertTrue(surface.state.connected)
        self.assertEqual(surface.state.status, ConnectionStatus.CONNECTED)
        surface.disconnect()

    def test_callback_failure_does_not_skip_following_callback(self):
        surface = DummySurface()
        seen = []
        errors = []

        def fail(_event):
            raise ValueError('broken app callback')

        surface.on_button(fail)
        surface.on_button(lambda event: seen.append(event.control))
        surface.on_error(errors.append)
        surface._emit_button('A', True)
        self.assertEqual(seen, ['A'])
        self.assertEqual(errors[0].operation, 'callback')
        self.assertFalse(errors[0].fatal)

    def test_threadsafe_callbacks_are_dispatched_by_poll(self):
        surface = DummySurface(threadsafe=True)
        seen = []
        surface.on_button(lambda event: seen.append(event.control))
        surface._emit_button('A', True)
        self.assertEqual(seen, [])
        surface.poll()
        self.assertEqual(seen, ['A'])

    def test_continuous_callbacks_coalesce_to_latest_value(self):
        surface = DummySurface(threadsafe=True)
        seen = []
        surface.on_tbar(lambda event: seen.append(event.raw))
        surface._emit_tbar(10)
        surface._emit_tbar(20)
        surface._emit_tbar(30)
        self.assertEqual(surface.pending_callbacks, 1)
        surface.poll()
        self.assertEqual(seen, [30])

    def test_button_callbacks_remain_ordered_and_lossless(self):
        surface = DummySurface(threadsafe=True)
        seen = []
        surface.on_button(lambda event: seen.append(event.held))
        surface._emit_button('A', True)
        surface._emit_button('A', False)
        surface.poll()
        self.assertEqual(seen, [True, False])

    def test_reconnect_recovers_reader_after_io_error(self):
        class FlakySurface(DummySurface):
            def __init__(self):
                super().__init__(reconnect=True, reconnect_interval=0.005)
                self.should_fail = True

            def _poll(self):
                if self.should_fail:
                    self.should_fail = False
                    raise OSError('unplugged')

        surface = FlakySurface()
        reconnected = threading.Event()
        errors = []
        surface.on_error(errors.append)
        surface.on_connection(
            lambda event: reconnected.set()
            if event.status == ConnectionStatus.CONNECTED and event.attempt == 1
            else None
        )
        surface.connect()
        surface.start()
        self.assertTrue(reconnected.wait(0.5))
        self.assertGreaterEqual(surface.open_count, 2)
        self.assertEqual(errors[0].operation, 'read')
        self.assertTrue(surface.is_running)
        surface.disconnect()

    def test_led_methods_accept_any_non_string_iterable(self):
        surface = DummySurface()
        surface.connect()
        surface.set(('A',))
        self.assertTrue(surface.is_lit('A'))
        surface.clear({'A'})
        self.assertFalse(surface.is_lit('A'))
        surface.disconnect()

    def test_remove_callback(self):
        surface = DummySurface()
        seen = []
        callback = lambda event: seen.append(event.control)
        surface.on_button(callback)
        self.assertTrue(surface.remove_callback(callback))
        self.assertFalse(surface.remove_callback(callback))
        surface._emit_button('A', True)
        self.assertEqual(seen, [])


class LEDBankTests(unittest.TestCase):
    def test_failed_write_does_not_corrupt_tracked_state(self):
        def fail(_value):
            raise OSError('device removed')

        bank = LEDBank(fail, {'A': 1})
        with self.assertRaises(OSError):
            bank.set('A')
        self.assertEqual(bank.lit, frozenset())


if __name__ == '__main__':
    unittest.main()
