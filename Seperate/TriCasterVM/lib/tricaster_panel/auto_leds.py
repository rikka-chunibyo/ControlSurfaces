# ═══════════════════════════════════════════════════════════════════
# tricaster_panel/auto_leds.py
#
# Default plug-in behaviour — mirrors the interactive section of the
# original example script:
#
#   • Button pressed  → its LED turns on
#   • Button released → its LED turns off
#   • T-bar at top    → fader top LED on,  bottom off
#   • T-bar at bottom → fader bottom LED on, top off
#   • T-bar mid       → both fader LEDs off
#
# Attaches as ordinary callbacks; user-registered callbacks stack on
# top without conflict.
#
# To take over a row entirely, call exclude() before registering your
# own handler — AutoLEDs will skip that row completely so your logic
# runs uncontested:
#
#   with TriCasterPanel(PORT, auto_leds=True) as panel:
#       panel.auto_leds.exclude('next')   # auto won't touch NEXT
#
#       @panel.on_next
#       def _(event):
#           ...                           # your toggle / radio logic here
#
# Valid row names for exclude / include: 'LIVE', 'NEXT', 'MINI', 'TBAR'
# (case-insensitive).  Both methods return self for chaining.
# ═══════════════════════════════════════════════════════════════════

from __future__ import annotations
from typing import TYPE_CHECKING

from .events import ButtonEvent, TBarEvent

if TYPE_CHECKING:
    from .panel import TriCasterPanel


class AutoLEDs:

    def __init__(self) -> None:
        self._panel:    TriCasterPanel | None = None
        self._excluded: set[str]              = set()

    def attach(self, panel: TriCasterPanel) -> None:
        self._panel = panel
        panel.on_button(self._on_button)
        panel.on_tbar(self._on_tbar)

    # ── override control ──────────────────────────────────────────

    def exclude(self, *rows: str) -> 'AutoLEDs':
        """
        Stop AutoLEDs from managing the named row(s).

        AutoLEDs will silently skip any event whose row matches an
        excluded name, so user-registered callbacks run uncontested.

        Parameters
        ----------
        *rows : 'LIVE', 'NEXT', 'MINI', or 'TBAR' (case-insensitive)

        Returns self for chaining::

            panel.auto_leds.exclude('next', 'mini')
        """
        for r in rows:
            self._excluded.add(r.upper())
        return self

    def include(self, *rows: str) -> 'AutoLEDs':
        """
        Re-enable AutoLEDs management for previously excluded row(s).

        Returns self for chaining.
        """
        for r in rows:
            self._excluded.discard(r.upper())
        return self

    # ── handlers ─────────────────────────────────────────────────

    def _on_button(self, event: ButtonEvent) -> None:
        if event.row in self._excluded:
            return
        p   = self._panel
        row = {'LIVE': p.live, 'NEXT': p.next, 'MINI': p.mini}.get(event.row)
        if row is None:
            return  # AUTO and TAKE have no LED row — nothing to do
        if event.held:
            row.set(event.button)
        else:
            row.clear(event.button)

    def _on_tbar(self, event: TBarEvent) -> None:
        if 'TBAR' in self._excluded:
            return
        p = self._panel
        p.fader.clear()
        if event.at_top:
            p.fader.set('top')
        elif event.at_bottom:
            p.fader.set('bottom')