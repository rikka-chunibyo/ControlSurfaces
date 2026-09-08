# ═══════════════════════════════════════════════════════════════════
# control_surfaces/surface.py
#
# ControlSurface — the shared base class both TriCasterSurface and
# LC11Surface build on. Owns the connection lifecycle, background
# reader thread, callback dispatch, LED state tracking, and the flat
# name-resolution logic. Every control -- input or output -- is
# addressed by a single canonical (or aliased) string name; there is
# no per-row or per-group sub-object to reach through.
#
# Subclasses provide the wire-protocol specifics by implementing:
#   _open()             open the physical connection
#   _close()             close it
#   _poll()               read whatever is available, decode it, and
#                          call the _emit_* helpers below
#   _write_led(name, on)  transmit the LED write for one control
# and by populating `controls: dict[str, Control]` before calling
# ControlSurface.__init__.
# ═══════════════════════════════════════════════════════════════════

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable

from .control   import Control
from .events    import ButtonEvent, DialEvent, TBarEvent, JoystickEvent

Event = ButtonEvent | DialEvent | TBarEvent | JoystickEvent


@dataclass(frozen=True)
class SurfaceState:
    """Read-only snapshot of current LED state and last known input values."""
    lit:       frozenset[str]
    dials:     dict[str, DialEvent]
    tbar:      TBarEvent | None
    joysticks: dict[str, JoystickEvent]


class ControlSurface:
    """
    Shared base class for control-surface devices.

    Basic usage (identical shape on every device that implements it)::

        with SomeSurface('/dev/ttyUSB0') as surface:

            surface.set('SOME_CONTROL')
            surface.set(['A', 'B'])
            surface.set_only('C')       # radio-button: one lit at a time
            surface.clear('A')
            surface.clear()             # whole surface off

            @surface.on_button
            def _(event):
                print(event.control, event.held)

            @surface.on('SOME_CONTROL')
            def _(event):
                ...                     # only fires for this one control

            surface.run()

    Parameters
    ----------
    port       : serial port string, e.g. '/dev/ttyUSB0' or 'COM5'
    baud       : baud rate (subclasses pass their device's fixed value)
    controls   : the full flat control catalogue for this device
    threadsafe : if True, callbacks are queued; call surface.poll() to
                 dispatch them from your own thread (useful for GUIs)
    """

    # ── T-bar endpoint detection -- override per subclass if needed ──
    #
    # Every device calls the same _emit_tbar() below with its raw
    # 0x00-0xFF byte; these two knobs are the only per-device
    # adjustment point for it.
    #
    # TBAR_ENDPOINT_TOLERANCE: how close to the extreme byte value
    #   counts as "at the endpoint." Real potentiometers rarely land on
    #   a byte-exact 0x00/0xFF, so a small tolerance (not 0) is the
    #   safe default -- an LED that never lights because the hardware
    #   reports 0x01 instead of 0x00 is a much easier bug to ship by
    #   accident than a tolerance band being slightly too generous.
    #
    # TBAR_INVERTED: set True if THIS device's hardware reports 0xFF at
    #   the physical top and 0x00 at the physical bottom (opposite of
    #   the validated default below). To tell which your device does:
    #   run example 3 (manual callback interactive) against it, push
    #   the T-bar to the physical top, and read the printed position.
    #   If it reads "100.0% (TOP)", the default is already correct --
    #   leave this False. If it reads "0.0% (BOTTOM)" while physically
    #   at the top, flip this one attribute to True and the position,
    #   at_top/at_bottom, and the auto_leds top/bottom LEDs all follow.
    TBAR_ENDPOINT_TOLERANCE = 2
    TBAR_INVERTED = False

    def __init__(
        self,
        port:       str,
        baud:       int,
        controls:   dict[str, Control],
        threadsafe: bool = False,
    ) -> None:
        self.port       = port
        self.baud       = baud
        self.controls   = controls
        self._threadsafe = threadsafe

        self._alias_lookup = self._build_alias_lookup()

        self._thread:  threading.Thread | None = None
        self._running  = False
        self._queue:   queue.Queue = queue.Queue()

        # ── callback registries ──────────────────────────────────
        self._button_cbs:   list[Callable] = []
        self._dial_cbs:     list[Callable] = []
        self._tbar_cbs:     list[Callable] = []
        self._joystick_cbs: list[Callable] = []
        self._named_cbs:    dict[str, list[Callable]] = {}

        # ── state tracking ───────────────────────────────────────
        self._lit:            set[str] = set()
        self._last_dials:     dict[str, DialEvent]     = {}
        self._last_tbar:      TBarEvent | None          = None
        self._last_joysticks: dict[str, JoystickEvent] = {}

        # Subclasses that support auto_leds=True set self.auto_leds
        # themselves (an AutoLEDs instance) after calling super().__init__;
        # it stays None here so surface.auto_leds is always a valid
        # attribute to check, even before a subclass has decided.
        self.auto_leds = None

    # ═══════════════════════════════════════════════════════════════
    #  Name resolution
    # ═══════════════════════════════════════════════════════════════

    def _build_alias_lookup(self) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for name, ctrl in self.controls.items():
            lookup[name.upper()] = name
            for alias in ctrl.aliases:
                lookup[alias.upper()] = name
        return lookup

    def _resolve(self, name: str) -> str:
        if not isinstance(name, str):
            raise TypeError(f"Control names must be strings, got {type(name).__name__!r}")
        key = self._alias_lookup.get(name.upper())
        if key is None:
            raise ValueError(
                f"Unknown control {name!r}. See surface.controls for valid names."
            )
        return key

    @staticmethod
    def _as_list(val) -> list:
        return val if isinstance(val, list) else [val]

    # ═══════════════════════════════════════════════════════════════
    #  Connection
    # ═══════════════════════════════════════════════════════════════

    def connect(self) -> None:
        """Open the connection and reset every LED to off."""
        self._open()
        self._lit.clear()
        self.all_off()

    def disconnect(self) -> None:
        """Stop the reader thread, reset LEDs, and close the connection."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

        try:
            self.all_off()
        except Exception:
            pass
        self._close()

    def __enter__(self) -> 'ControlSurface':
        self.connect()
        return self

    def __exit__(self, *_exc) -> None:
        self.disconnect()

    # ── subclass hooks (connection) ───────────────────────────────

    def _open(self) -> None:
        raise NotImplementedError

    def _close(self) -> None:
        raise NotImplementedError

    # ═══════════════════════════════════════════════════════════════
    #  LED control -- every LED-capable control lives in one flat
    #  namespace, regardless of which wire-level byte it happens to
    #  share with other controls.
    # ═══════════════════════════════════════════════════════════════

    def set(self, controls) -> None:
        """Turn on one or more controls' LEDs; others are unchanged."""
        for name in self._as_list(controls):
            resolved = self._resolve_led(name)
            self._lit.add(resolved)
            self._write_led(resolved, True)

    def clear(self, controls=None) -> None:
        """
        Turn off LEDs.
        clear()        -- every LED off
        clear('A')     -- just A off, others unchanged
        clear(['A','B']) -- A and B off, others unchanged
        """
        if controls is None:
            for name in list(self._lit):
                self._lit.discard(name)
                self._write_led(name, False)
        else:
            for name in self._as_list(controls):
                resolved = self._resolve_led(name)
                self._lit.discard(resolved)
                self._write_led(resolved, False)

    def set_only(self, controls) -> None:
        """Turn on the target control(s) and turn off everything else."""
        target = {self._resolve_led(n) for n in self._as_list(controls)}
        for name in list(self._lit - target):
            self._lit.discard(name)
            self._write_led(name, False)
        for name in target - self._lit:
            self._lit.add(name)
            self._write_led(name, True)

    def all_off(self) -> None:
        """Reset every LED on the device to off. Safe to call any time."""
        self.clear()

    def is_lit(self, control: str) -> bool:
        return self._resolve(control) in self._lit

    def _resolve_led(self, name: str) -> str:
        resolved = self._resolve(name)
        if not self.controls[resolved].has_led:
            raise ValueError(f"{resolved!r} has no LED and cannot be lit.")
        return resolved

    # ── subclass hook (LED write) ───────────────────────────────────

    def _write_led(self, name: str, on: bool) -> None:
        raise NotImplementedError

    # ═══════════════════════════════════════════════════════════════
    #  State snapshot
    # ═══════════════════════════════════════════════════════════════

    @property
    def state(self) -> SurfaceState:
        return SurfaceState(
            lit       = frozenset(self._lit),
            dials     = dict(self._last_dials),
            tbar      = self._last_tbar,
            joysticks = dict(self._last_joysticks),
        )

    # ═══════════════════════════════════════════════════════════════
    #  Callback registration
    # ═══════════════════════════════════════════════════════════════

    def on_button(self, fn: Callable) -> Callable:
        """Register a callback for button events on any control."""
        self._button_cbs.append(fn)
        return fn

    def on_dial(self, fn: Callable) -> Callable:
        """Register a callback for dial telemetry events on any dial."""
        self._dial_cbs.append(fn)
        return fn

    def on_tbar(self, fn: Callable) -> Callable:
        """Register a callback for T-bar position events."""
        self._tbar_cbs.append(fn)
        return fn

    def on_joystick(self, fn: Callable) -> Callable:
        """Register a callback for joystick telemetry events on any joystick."""
        self._joystick_cbs.append(fn)
        return fn

    def on(self, control: str, fn: Callable | None = None) -> Callable:
        """
        Register a callback scoped to exactly one control, whatever kind
        of event it produces (button, dial, T-bar, or joystick).

        Decorator style::

            @surface.on('LIVE_CAM_1')
            def _(event):
                ...

        Direct call style also works::

            surface.on('LIVE_CAM_1', my_callback)
        """
        resolved = self._resolve(control)

        def register(f: Callable) -> Callable:
            self._named_cbs.setdefault(resolved, []).append(f)
            return f

        if fn is None:
            return register
        return register(fn)

    # ═══════════════════════════════════════════════════════════════
    #  Execution
    # ═══════════════════════════════════════════════════════════════

    def start(self) -> None:
        """Start a background daemon thread. Returns immediately."""
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background thread and close the connection."""
        self.disconnect()

    def run(self) -> None:
        """Block on the reader loop. Returns on KeyboardInterrupt or stop()."""
        self._running = True
        try:
            self._loop()
        except KeyboardInterrupt:
            pass
        finally:
            self.disconnect()

    def poll(self) -> None:
        """
        Dispatch all queued events on the calling thread.
        Only meaningful when threadsafe=True; raises RuntimeError otherwise.
        """
        if not self._threadsafe:
            raise RuntimeError("poll() requires threadsafe=True")
        while True:
            try:
                cb, event = self._queue.get_nowait()
                cb(event)
            except queue.Empty:
                break

    def _loop(self) -> None:
        while self._running:
            self._poll()
            time.sleep(0.02)

    # ── subclass hook (reader) ─────────────────────────────────────

    def _poll(self) -> None:
        """Read whatever is available and call the _emit_* helpers below."""
        raise NotImplementedError

    # ═══════════════════════════════════════════════════════════════
    #  Testing / simulation
    # ═══════════════════════════════════════════════════════════════

    def simulate(self, event: Event) -> None:
        """Inject a fake event -- useful for unit testing without hardware."""
        if isinstance(event, ButtonEvent):
            self._dispatch_button(event)
        elif isinstance(event, DialEvent):
            self._last_dials[event.control] = event
            self._dispatch_dial(event)
        elif isinstance(event, TBarEvent):
            self._last_tbar = event
            self._dispatch_tbar(event)
        elif isinstance(event, JoystickEvent):
            self._last_joysticks[event.control] = event
            self._dispatch_joystick(event)
        else:
            raise TypeError(f"Unrecognised event type: {type(event)}")

    # ═══════════════════════════════════════════════════════════════
    #  Emit helpers -- called by subclasses from _poll()
    # ═══════════════════════════════════════════════════════════════

    def _emit_button(self, control: str, held: bool) -> None:
        self._dispatch_button(ButtonEvent(control=control, held=held))

    def _emit_dial(self, control: str, value: int) -> None:
        event = DialEvent(control=control, value=value)
        self._last_dials[control] = event
        self._dispatch_dial(event)

    def _emit_tbar(self, raw: int) -> None:
        # normalized: 0 = physical bottom, 255 = physical top, regardless
        # of which raw byte value this device's hardware actually uses
        # for which end -- see TBAR_INVERTED above.
        normalized = raw if self.TBAR_INVERTED else (255 - raw)
        position = round(normalized / 255.0, 4)
        tol = self.TBAR_ENDPOINT_TOLERANCE
        event = TBarEvent(
            control='TBAR', raw=raw, position=position,
            at_top=(normalized >= 255 - tol),
            at_bottom=(normalized <= tol),
        )
        self._last_tbar = event
        self._dispatch_tbar(event)

    def _emit_joystick(self, control: str, raw: str) -> None:
        try:
            value = int(raw, 16)
        except (TypeError, ValueError):
            value = None
        event = JoystickEvent(control=control, raw=raw, value=value)
        self._last_joysticks[control] = event
        self._dispatch_joystick(event)

    # ── dispatch internals ──────────────────────────────────────────

    def _dispatch_button(self, event: ButtonEvent) -> None:
        for cb in self._button_cbs:
            self._invoke(cb, event)
        for cb in self._named_cbs.get(event.control, ()):
            self._invoke(cb, event)

    def _dispatch_dial(self, event: DialEvent) -> None:
        for cb in self._dial_cbs:
            self._invoke(cb, event)
        for cb in self._named_cbs.get(event.control, ()):
            self._invoke(cb, event)

    def _dispatch_tbar(self, event: TBarEvent) -> None:
        for cb in self._tbar_cbs:
            self._invoke(cb, event)
        for cb in self._named_cbs.get(event.control, ()):
            self._invoke(cb, event)

    def _dispatch_joystick(self, event: JoystickEvent) -> None:
        for cb in self._joystick_cbs:
            self._invoke(cb, event)
        for cb in self._named_cbs.get(event.control, ()):
            self._invoke(cb, event)

    def _invoke(self, cb: Callable, event: Event) -> None:
        if self._threadsafe:
            self._queue.put((cb, event))
        else:
            cb(event)
