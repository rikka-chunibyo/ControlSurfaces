import unittest
from unittest.mock import patch

from control_surfaces.detect import (
    DeviceMatch, LC11, detect_devices, find_port_by_serial,
)


class Port:
    def __init__(self, device, serial_number=None, description=None):
        self.device = device
        self.serial_number = serial_number
        self.description = description
        self.manufacturer = None
        self.product = None
        self.vid = None
        self.pid = None


class DetectionTests(unittest.TestCase):
    def test_find_port_by_stable_serial(self):
        ports = [Port('COM8', 'PANEL-1', 'USB Serial')]
        with patch('control_surfaces.detect.list_ports.comports', return_value=ports):
            self.assertEqual(find_port_by_serial('PANEL-1'), 'COM8')
            self.assertIsNone(find_port_by_serial('missing'))

    def test_match_exposes_metadata_for_app_configuration(self):
        port = Port('COM8', 'PANEL-1', 'NewTek LiveControl LC-11')
        with patch('control_surfaces.detect.list_ports.comports', return_value=[port]):
            matches = detect_devices()
        self.assertEqual(matches, [DeviceMatch(
            'COM8', LC11, 'description', 'PANEL-1',
            'NewTek LiveControl LC-11',
        )])
        self.assertEqual(matches[0].stable_id, 'PANEL-1')
