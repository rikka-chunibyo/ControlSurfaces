# ═══════════════════════════════════════════════════════════════════
# control_surfaces/control.py
#
# Metadata describing one individually-addressable control.
#
# Every control on either device -- button, dial, joystick, T-bar, or
# LED -- gets exactly one Control entry in a device's catalogue
# (`surface.controls`). There is no nested "row" or "group" object to
# go through; the catalogue is a flat dict keyed by canonical name.
# ═══════════════════════════════════════════════════════════════════

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Flag, auto


class Emits(Flag):
    """What kind of event(s) a control can produce. A control may combine
    flags -- e.g. the LC-11's dials emit both DIAL (telemetry) and BUTTON
    (click) events under the same control name."""
    NONE     = 0
    BUTTON   = auto()
    DIAL     = auto()
    TBAR     = auto()
    JOYSTICK = auto()


@dataclass(frozen=True)
class Control:
    """
    Read-only metadata for one control.

    Parameters
    ----------
    name    : canonical, code-facing identifier (e.g. 'LIVE_CAM_1').
              Always upper-case, underscore-separated.
    emits   : Emits flag(s) describing what event type(s) this control
              produces as an input. Emits.NONE for output-only controls
              (e.g. TBAR_LED_TOP has no matching input button).
    has_led : True if this control has an addressable output LED.
    aliases : optional case-insensitive alternate names accepted by
              set()/clear()/on() -- e.g. 'top' for 'TBAR_LED_TOP'.
    """
    name:    str
    emits:   Emits = Emits.NONE
    has_led: bool  = False
    aliases: tuple[str, ...] = field(default_factory=tuple)
