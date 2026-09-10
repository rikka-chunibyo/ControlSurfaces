# ═══════════════════════════════════════════════════════════════════
# control_surfaces/auto_leds.py
#
# Default plug-in behaviour, generic across every ControlSurface:
#
#   • Button with an LED, pressed  → its LED turns on
#   • Button with an LED, released → its LED turns off
#   • T-bar at top    → TBAR_LED_TOP on,    TBAR_LED_BOTTOM off
#   • T-bar at bottom → TBAR_LED_BOTTOM on, TBAR_LED_TOP off
#   • T-bar mid       → both off
#
# This works unmodified on any device because control naming for the
# T-bar's endpoint LEDs ('TBAR_LED_TOP' / 'TBAR_LED_BOTTOM') is one of
# the few things deliberately kept consistent across TriCasterVM and
# the LC-11 -- everything else is free to be named however each
# device's own hardware naturally suggests.
#
# Attaches as ordinary callbacks; user-registered callbacks stack on
# top without conflict.
#
# To take over a control (or a whole row) entirely, call exclude()
# before registering your own handler:
#
#   with TriCasterSurface(PORT, auto_leds=True) as surface:
#       surface.auto_leds.exclude('NEXT')   # matches NEXT_CAM_1, NEXT_VGA, ...
#
#       @surface.on_button
#       def _(event):
#           if event.control.startswith('NEXT_'):
#               ...                          # your logic runs uncontested
#
# exclude() accepts exact control names ('LIVE_CAM_1') or row-style
# prefixes ('LIVE', 'NEXT', 'EFFECTS', 'PREVIEW') that match every
# control beginning with that prefix, plus 'TBAR' for the T-bar LEDs.
# Both exclude() and include() return self for chaining.
# ═══════════════════════════════════════════════════════════════════

from __future__ import annotations
from typing import TYPE_CHECKING

from .events import ButtonEvent, TBarEvent

if TYPE_CHECKING:
    from .surface import ControlSurface


class AutoLEDs:

    def __init__(self) -> None:
        self._surface:  'ControlSurface | None' = None
        self._excluded: set[str] = set()

    def attach(self, surface: 'ControlSurface') -> None:
        self._surface = surface
        surface.on_button(self._on_button)
        surface.on_tbar(self._on_tbar)

    # ── override control ──────────────────────────────────────────

    def exclude(self, *names: str) -> 'AutoLEDs':
        for n in names:
            self._excluded.add(n.upper())
        return self

    def include(self, *names: str) -> 'AutoLEDs':
        for n in names:
            self._excluded.discard(n.upper())
        return self

    def _is_excluded(self, control: str) -> bool:
        key = control.upper()
        if key in self._excluded:
            return True
        return any(key.startswith(prefix + '_') for prefix in self._excluded)

    # ── handlers ─────────────────────────────────────────────────

    def _on_button(self, event: ButtonEvent) -> None:
        if self._is_excluded(event.control):
            return
        ctrl = self._surface.controls.get(event.control)
        if ctrl is None or not ctrl.has_led:
            return   # e.g. AUTO / TAKE / dial clicks -- no LED to drive
        if event.held:
            self._surface.set(event.control)
        else:
            self._surface.clear(event.control)

    def _on_tbar(self, event: TBarEvent) -> None:
        if self._is_excluded('TBAR'):
            return
        has_top    = 'TBAR_LED_TOP'    in self._surface.controls
        has_bottom = 'TBAR_LED_BOTTOM' in self._surface.controls
        if not has_top and not has_bottom:
            return
        if has_top:
            self._surface.clear('TBAR_LED_TOP')
        if has_bottom:
            self._surface.clear('TBAR_LED_BOTTOM')
        if event.at_top and has_top:
            self._surface.set('TBAR_LED_TOP')
        elif event.at_bottom and has_bottom:
            self._surface.set('TBAR_LED_BOTTOM')
