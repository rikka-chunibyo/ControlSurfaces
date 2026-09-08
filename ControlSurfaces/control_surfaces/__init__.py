# ═══════════════════════════════════════════════════════════════════
# control_surfaces/__init__.py
#
# Public API. Every control on every supported device -- TriCaster VM
# and LiveControl LC-11 -- is addressed the same way: a flat,
# individually-addressable name through a ControlSurface subclass.
# ═══════════════════════════════════════════════════════════════════

from .control      import Control, Emits
from .events       import ButtonEvent, DialEvent, TBarEvent, JoystickEvent
from .surface      import ControlSurface, SurfaceState
from .auto_leds    import AutoLEDs
from .dial_tracker import DialTracker
from .devices      import TriCasterSurface, LC11Surface
from .multi        import MultiSurface
from .detect       import (
    detect_devices, auto_connect, auto_connect_all, auto_connect_hub,
    identify_port, list_serial_ports, forget_cached_devices,
    DeviceMatch,
    DeviceDetectionError, NoDeviceFoundError, AmbiguousDeviceError, UnknownDeviceError,
    TRICASTER, LC11,
)

__all__ = [
    # devices
    'TriCasterSurface', 'LC11Surface',
    # shared base / state
    'ControlSurface', 'SurfaceState', 'Control', 'Emits',
    # multi-device
    'MultiSurface',
    # events
    'ButtonEvent', 'DialEvent', 'TBarEvent', 'JoystickEvent',
    # plug-ins / helpers
    'AutoLEDs', 'DialTracker',
    # auto-detection
    'detect_devices', 'auto_connect', 'auto_connect_all', 'auto_connect_hub',
    'identify_port', 'list_serial_ports', 'forget_cached_devices',
    'DeviceMatch', 'DeviceDetectionError', 'NoDeviceFoundError',
    'AmbiguousDeviceError', 'UnknownDeviceError', 'TRICASTER', 'LC11',
]
