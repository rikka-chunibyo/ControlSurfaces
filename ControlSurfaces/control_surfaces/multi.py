# ═══════════════════════════════════════════════════════════════════
# control_surfaces/multi.py
#
# MultiSurface -- bundles several ControlSurface instances (typically
# one TriCaster + one LC-11, plugged in simultaneously) behind one
# object, so a macro app can listen for and react to input from either
# device without hand-managing two connections, two thread lifecycles,
# and two callback registries.
#
# ── Why this doesn't merge into one flat control namespace ───────────
# Several controls are IDENTICALLY NAMED on both devices -- TBAR, TAKE,
# AUTO, FADE_ALL, TAKE_ALL, FADE_OVERLAY, TAKE_OVERLAY, TBAR_LED_TOP,
# TBAR_LED_BOTTOM all exist on both TriCasterSurface and LC11Surface.
# Collapsing everything into one shared name -> Control dict would mean
# "TBAR" secretly refers to whichever device happened to be added last,
# and a macro bound to "TBAR" could silently react to the wrong
# physical device. MultiSurface keeps each device's own catalogue
# intact and instead tags every event with which device it came from,
# so "the TriCaster's T-bar" and "the LC-11's T-bar" are never
# ambiguous -- and per-device methods (.set(), .clear(), state, LEDs)
# are reached through the individual surfaces, exactly as before.
# ═══════════════════════════════════════════════════════════════════

from __future__ import annotations

import time
from typing import Callable, Iterator

from .surface import ControlSurface, Event

DEVICE_ATTR = 'device_type'   # attribute name added to every event


class MultiSurface:
    """
    Bundle multiple ControlSurface instances behind one addressable
    object, so both can be connected, run, and listened to at once.

        surfaces = auto_connect_all(auto_leds=True)   # {device_type: surface}
        hub = MultiSurface(surfaces)

        with hub:
            @hub.on_button
            def _(event):
                # event.device_type is TRICASTER or LC11, event.surface
                # is that underlying ControlSurface -- always tell which
                # physical panel an event came from, even for controls
                # that share a name across both devices (TBAR, TAKE, ...)
                print(event.device_type, event.control, event.held)

            @hub.on(TRICASTER, 'LIVE_CAM_1')
            def _(event):
                ...   # scoped to one control on one specific device

            hub.tricaster.set('LIVE_CAM_1')   # per-device methods still
            hub.lc11.set('LIVE_1')            # go through the surface itself

            hub.run()

    Or build one directly from a dict of already-open surfaces::

        hub = MultiSurface({
            TRICASTER: TriCasterSurface('COM3', auto_leds=True),
            LC11:      LC11Surface('COM5', auto_leds=True),
        })
    """

    def __init__(self, surfaces: dict[str, ControlSurface]) -> None:
        if not surfaces:
            raise ValueError("MultiSurface needs at least one surface.")
        self.surfaces = dict(surfaces)

        self._button_cbs:   list[Callable] = []
        self._dial_cbs:     list[Callable] = []
        self._tbar_cbs:     list[Callable] = []
        self._joystick_cbs: list[Callable] = []
        self._named_cbs:    dict[tuple[str, str], list[Callable]] = {}

        for device_type, surface in self.surfaces.items():
            surface.on_button(self._make_forwarder(device_type, surface, self._button_cbs))
            surface.on_dial(self._make_forwarder(device_type, surface, self._dial_cbs))
            surface.on_tbar(self._make_forwarder(device_type, surface, self._tbar_cbs))
            surface.on_joystick(self._make_forwarder(device_type, surface, self._joystick_cbs))

    # ═══════════════════════════════════════════════════════════════
    #  Per-device access
    # ═══════════════════════════════════════════════════════════════

    def __getitem__(self, device_type: str) -> ControlSurface:
        return self.surfaces[device_type]

    def __iter__(self) -> Iterator[ControlSurface]:
        return iter(self.surfaces.values())

    def __contains__(self, device_type: str) -> bool:
        return device_type in self.surfaces

    @property
    def tricaster(self) -> ControlSurface | None:
        """Shortcut for surfaces.get(TRICASTER); None if not connected."""
        from .detect import TRICASTER
        return self.surfaces.get(TRICASTER)

    @property
    def lc11(self) -> ControlSurface | None:
        """Shortcut for surfaces.get(LC11); None if not connected."""
        from .detect import LC11
        return self.surfaces.get(LC11)

    # ═══════════════════════════════════════════════════════════════
    #  Event forwarding -- tags every event with its source device
    #  before handing it to hub-level callbacks
    # ═══════════════════════════════════════════════════════════════

    def _make_forwarder(self, device_type: str, surface: ControlSurface, cb_list: list) -> Callable:
        def forward(event: Event) -> None:
            event.device_type = device_type
            event.surface = surface
            for cb in cb_list:
                cb(event)
            for cb in self._named_cbs.get((device_type, event.control), ()):
                cb(event)
        return forward

    def on_button(self, fn: Callable) -> Callable:
        """Register a callback for button events on any control, on any device."""
        self._button_cbs.append(fn)
        return fn

    def on_dial(self, fn: Callable) -> Callable:
        """Register a callback for dial telemetry events, on any device."""
        self._dial_cbs.append(fn)
        return fn

    def on_tbar(self, fn: Callable) -> Callable:
        """Register a callback for T-bar events, on any device."""
        self._tbar_cbs.append(fn)
        return fn

    def on_joystick(self, fn: Callable) -> Callable:
        """Register a callback for joystick telemetry events, on any device."""
        self._joystick_cbs.append(fn)
        return fn

    def on(self, device_type: str, control: str, fn: Callable | None = None) -> Callable:
        """
        Register a callback scoped to exactly one control on exactly one
        device -- required for names that collide across devices (TBAR,
        TAKE, AUTO, ...): hub.on(TRICASTER, 'TBAR') and hub.on(LC11, 'TBAR')
        are two independent subscriptions.

            @hub.on(TRICASTER, 'LIVE_CAM_1')
            def _(event):
                ...

            hub.on(LC11, 'LIVE_1', my_callback)
        """
        if device_type not in self.surfaces:
            raise ValueError(
                f"No {device_type!r} device in this MultiSurface. "
                f"Connected: {sorted(self.surfaces)}"
            )
        resolved = self.surfaces[device_type]._resolve(control)

        def register(f: Callable) -> Callable:
            self._named_cbs.setdefault((device_type, resolved), []).append(f)
            return f

        if fn is None:
            return register
        return register(fn)

    # ═══════════════════════════════════════════════════════════════
    #  Lifecycle -- every surface at once
    # ═══════════════════════════════════════════════════════════════

    def connect(self) -> None:
        for surface in self.surfaces.values():
            surface.connect()

    def disconnect(self) -> None:
        for surface in self.surfaces.values():
            try:
                surface.disconnect()
            except Exception:
                pass   # keep closing the rest even if one fails

    def __enter__(self) -> 'MultiSurface':
        self.connect()
        return self

    def __exit__(self, *_exc) -> None:
        self.disconnect()

    def start(self) -> None:
        """Start every surface's background reader thread. Returns immediately."""
        for surface in self.surfaces.values():
            surface.start()

    def stop(self) -> None:
        self.disconnect()

    def run(self) -> None:
        """
        Block until Ctrl-C, dispatching events from every connected
        device. Equivalent to calling start() on every surface and then
        waiting -- unlike a single ControlSurface.run(), this doesn't
        block inside any one surface's own read loop, since several
        devices need their reader threads running concurrently.
        """
        self.start()
        try:
            while True:
                for surface in self.surfaces.values():
                    if surface._thread and not surface._thread.is_alive():
                        return   # a device's reader died -- stop cleanly
                time.sleep(0.05)
        except KeyboardInterrupt:
            pass
        finally:
            self.disconnect()

    def all_off(self) -> None:
        """Reset every LED on every connected device."""
        for surface in self.surfaces.values():
            surface.all_off()
