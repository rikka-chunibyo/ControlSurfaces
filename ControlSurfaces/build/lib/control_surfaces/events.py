# ═══════════════════════════════════════════════════════════════════
# control_surfaces/events.py
#
# Typed event dataclasses emitted by every ControlSurface, regardless
# of which physical device produced them. A callback registered on
# one device works unmodified against the other — the event shapes
# are identical, only the `control` name differs.
# ═══════════════════════════════════════════════════════════════════

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .surface import ControlSurface


class ConnectionStatus(str, Enum):
    """Lifecycle states suitable for GUI status indicators."""

    DISCONNECTED = 'disconnected'
    CONNECTING = 'connecting'
    CONNECTED = 'connected'
    RECONNECTING = 'reconnecting'
    STOPPED = 'stopped'


@dataclass
class ButtonEvent:
    """Fired when any individually-addressable button is pressed or released."""
    control: str   # canonical control name, e.g. 'LIVE_CAM_1', 'FADE_ALL', 'TAKE'
    held:    bool  # True = pressed, False = released
    timestamp: float = field(default_factory=time.monotonic)
    device_type: str | None = None
    surface: 'ControlSurface | None' = None


@dataclass
class DialEvent:
    """Fired when a rotary dial reports a new absolute position."""
    control: str   # e.g. 'TRANSITION_SPEED' (TriCaster) or 'SPEED' (LC-11)
    value:   int   # raw absolute value reported by the hardware
    timestamp: float = field(default_factory=time.monotonic)
    device_type: str | None = None
    surface: 'ControlSurface | None' = None


@dataclass
class TBarEvent:
    """Fired on every T-bar / fader position change."""
    control:   str    # 'TBAR'
    raw:       int    # raw byte value 0x00-0xFF, as reported by the hardware
    position:  float  # 0.0 (physical bottom) - 1.0 (physical top)
    at_top:    bool   # True within ControlSurface.TBAR_ENDPOINT_TOLERANCE of the physical top
    at_bottom: bool   # True within ControlSurface.TBAR_ENDPOINT_TOLERANCE of the physical bottom
    timestamp: float = field(default_factory=time.monotonic)
    device_type: str | None = None
    surface: 'ControlSurface | None' = None


@dataclass
class JoystickEvent:
    """
    Fired when a joystick reports new telemetry.

    The LC-11's joystick telemetry payload has not been fully decoded
    into X/Y axes upstream (see lc11_protocol_map.py) -- `raw` always
    carries the untouched payload string; `value` is a best-effort hex
    parse of it and is None when the payload doesn't parse cleanly.
    """
    control: str        # 'JOYSTICK_A' | 'JOYSTICK_B'
    raw:     str         # untouched payload as reported by the hardware
    value:   int | None  # int(raw, 16) if that parses, else None
    timestamp: float = field(default_factory=time.monotonic)
    device_type: str | None = None
    surface: 'ControlSurface | None' = None


@dataclass(frozen=True)
class ConnectionEvent:
    """Fired whenever a surface changes lifecycle state."""

    status: ConnectionStatus
    attempt: int = 0
    timestamp: float = field(default_factory=time.monotonic)


@dataclass(frozen=True)
class SurfaceErrorEvent:
    """An I/O or user-callback failure reported without killing the app."""

    error: Exception
    operation: str
    fatal: bool
    timestamp: float = field(default_factory=time.monotonic)


def event_timestamp() -> float:
    """Return the monotonic clock used for all library event timestamps."""
    return time.monotonic()
