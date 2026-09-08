# ═══════════════════════════════════════════════════════════════════
# tricaster_panel/panel.py
#
# Main public class.  Owns the serial connection, background reader
# thread, callback dispatch, and all four LED row objects.
# ═══════════════════════════════════════════════════════════════════

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import serial

from .constants import (
    BAUD,
    CH_LIVE, CH_NEXT, CH_TBAR, CH_MISC,
    ROW_LABELS, MINI_LABELS,
    CH3_INPUT_BITS, CH3_BTN_LED, CH3_EVENT_LABELS, CH3_EVENT_ROW,
    DIAL_NAMES,
)
from .protocol import send_frame, read_frames
from .leds import RowLEDs, MiniRowLEDs, FaderLEDs
from .events import ButtonEvent, TBarEvent, DialEvent


# ── state snapshot ────────────────────────────────────────────────

@dataclass(frozen=True)
class PanelState:
    """Read-only snapshot of current LED state and last known input values."""
    live:  frozenset
    next:  frozenset
    mini:  frozenset
    fader: frozenset
    tbar:  TBarEvent | None
    dials: dict


# ═══════════════════════════════════════════════════════════════════
#  TriCasterPanel
# ═══════════════════════════════════════════════════════════════════

class TriCasterPanel:
    """
    High-level interface to the TriCaster VM hardware panel.

    Basic usage::

        with TriCasterPanel('COM3', auto_leds=True) as panel:
            panel.run()   # blocks; Ctrl-C to exit

    Manual control::

        with TriCasterPanel('COM3') as panel:

            panel.live.set(1)
            panel.live.set('cam 2')
            panel.live.set([3, 'VGA'])
            panel.live.set_only(4)   # radio-button: one lit at a time
            panel.live.clear(1)
            panel.live.clear()

            panel.next.set([1, 2])
            panel.mini.set('fade overlay')
            panel.fader.set('top')
            panel.fader.set(2)       # 'bottom'
            panel.all_off()

            @panel.on_button
            def _(event):
                print(event.row, event.label, event.held)

            @panel.on_tbar
            def _(event):
                print(event.position)

            @panel.on_dial
            def _(event):
                print(event.dial, event.value)

            panel.run()

    Parameters
    ----------
    port      : serial port string, e.g. 'COM3' or '/dev/ttyUSB0'
    baud      : baud rate (default 115200)
    auto_leds : if True, wire default LED-follows-button behaviour
    threadsafe: if True, callbacks are queued; call panel.poll() to
                dispatch from your own thread (useful for GUIs)
    """

    def __init__(
        self,
        port:       str,
        baud:       int  = BAUD,
        auto_leds:  bool = False,
        threadsafe: bool = False,
    ) -> None:
        self._port       = port
        self._baud       = baud
        self._threadsafe = threadsafe
        self._ser:    serial.Serial | None  = None
        self._thread: threading.Thread | None = None
        self._running = False

        # ── LED rows ──────────────────────────────────────────────
        # Serial is injected on connect() so the rows can be created
        # and wired before the port is opened.
        self.live  = RowLEDs(None, CH_LIVE)
        self.next  = RowLEDs(None, CH_NEXT)
        self.mini  = MiniRowLEDs(None)
        self.fader = FaderLEDs(None)

        # Cross-link mini ↔ fader so they share ch3 correctly
        self.mini._link(self.fader)
        self.fader._link(self.mini)

        # ── callbacks ─────────────────────────────────────────────
        self._button_cbs: list[Callable] = []
        self._tbar_cbs:   list[Callable] = []
        self._dial_cbs:   list[Callable] = []

        # ── input state tracking (delta detection) ────────────────
        self._prev_live:  set[int] = set()
        self._prev_next:  set[int] = set()
        self._prev_mini:  set[int] = set()

        # ── last known input values ───────────────────────────────
        self._last_tbar:  TBarEvent | None    = None
        self._last_dials: dict[str, DialEvent] = {}

        # ── threadsafe event queue ────────────────────────────────
        self._queue: queue.Queue = queue.Queue()

        # ── auto LED plug-in ──────────────────────────────────────
        # Stored as panel.auto_leds so callers can call .exclude() on it.
        # None when auto_leds=False.
        self.auto_leds = None
        if auto_leds:
            from .auto_leds import AutoLEDs
            _al = AutoLEDs()
            _al.attach(self)
            self.auto_leds = _al

    # ═══════════════════════════════════════════════════════════════
    #  Connection
    # ═══════════════════════════════════════════════════════════════

    def connect(self) -> None:
        """Open the serial port and reset all LEDs."""
        self._ser = serial.Serial(self._port, self._baud, timeout=0.1)

        # Inject the live serial object into every LED row
        self.live._ser  = self._ser
        self.next._ser  = self._ser
        self.mini._ser  = self._ser
        self.fader._ser = self._ser

        self.all_off()

    def disconnect(self) -> None:
        """Stop the reader thread, reset LEDs, and close the port."""
        self._running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

        if self._ser and self._ser.is_open:
            try:
                self.all_off()
            except Exception:
                pass
            self._ser.close()

        self._ser = None

    def __enter__(self) -> TriCasterPanel:
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.disconnect()

    # ═══════════════════════════════════════════════════════════════
    #  LED helpers
    # ═══════════════════════════════════════════════════════════════

    def all_off(self) -> None:
        """Reset every LED on the panel to off.  Safe to call any time."""
        self.live.clear()
        self.next.clear()
        self.mini.clear()
        self.fader.clear()

    @property
    def state(self) -> PanelState:
        """Read-only snapshot of current LED state and last known input values."""
        return PanelState(
            live  = frozenset(self.live._state),
            next  = frozenset(self.next._state),
            mini  = frozenset(self.mini._state),
            fader = frozenset(self.fader._state),
            tbar  = self._last_tbar,
            dials = dict(self._last_dials),
        )

    # ═══════════════════════════════════════════════════════════════
    #  Callback registration
    # ═══════════════════════════════════════════════════════════════

    def on_button(self, fn: Callable) -> Callable:
        """Register a callback for button events on any row."""
        self._button_cbs.append(fn)
        return fn

    def on_live(self, fn: Callable) -> Callable:
        """Register a callback for LIVE row button events only."""
        def _filtered(event: ButtonEvent) -> None:
            if event.row == 'LIVE':
                fn(event)
        self._button_cbs.append(_filtered)
        return fn

    def on_next(self, fn: Callable) -> Callable:
        """Register a callback for NEXT row button events only."""
        def _filtered(event: ButtonEvent) -> None:
            if event.row == 'NEXT':
                fn(event)
        self._button_cbs.append(_filtered)
        return fn

    def on_mini(self, fn: Callable) -> Callable:
        """Register a callback for MINI row button events only."""
        def _filtered(event: ButtonEvent) -> None:
            if event.row == 'MINI':
                fn(event)
        self._button_cbs.append(_filtered)
        return fn

    def on_auto(self, fn: Callable) -> Callable:
        """Register a callback for the AUTO button only."""
        def _filtered(event: ButtonEvent) -> None:
            if event.row == 'AUTO':
                fn(event)
        self._button_cbs.append(_filtered)
        return fn

    def on_take(self, fn: Callable) -> Callable:
        """Register a callback for the TAKE button only."""
        def _filtered(event: ButtonEvent) -> None:
            if event.row == 'TAKE':
                fn(event)
        self._button_cbs.append(_filtered)
        return fn

    def on_tbar(self, fn: Callable) -> Callable:
        """Register a callback for T-bar position events."""
        self._tbar_cbs.append(fn)
        return fn

    def on_dial(self, fn: Callable) -> Callable:
        """Register a callback for dial events."""
        self._dial_cbs.append(fn)
        return fn

    # ═══════════════════════════════════════════════════════════════
    #  Execution
    # ═══════════════════════════════════════════════════════════════

    def start(self) -> None:
        """Start a background daemon thread.  Returns immediately."""
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background thread and close the port."""
        self.disconnect()

    def run(self) -> None:
        """
        Block on the reader loop.  Returns on KeyboardInterrupt or
        when stop() is called from another thread.
        """
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
            raise RuntimeError("poll() requires TriCasterPanel(threadsafe=True)")
        while True:
            try:
                cb, event = self._queue.get_nowait()
                cb(event)
            except queue.Empty:
                break

    # ═══════════════════════════════════════════════════════════════
    #  Testing / simulation
    # ═══════════════════════════════════════════════════════════════

    def simulate(self, event: ButtonEvent | TBarEvent | DialEvent) -> None:
        """
        Inject a fake event — useful for unit testing without hardware.

            panel.simulate(ButtonEvent(row='LIVE', button=1,
                                       label='CAM 1', held=True))
        """
        if isinstance(event, ButtonEvent):
            for cb in self._button_cbs:
                self._invoke(cb, event)
        elif isinstance(event, TBarEvent):
            self._last_tbar = event
            for cb in self._tbar_cbs:
                self._invoke(cb, event)
        elif isinstance(event, DialEvent):
            self._last_dials[event.dial] = event
            for cb in self._dial_cbs:
                self._invoke(cb, event)
        else:
            raise TypeError(f"Unrecognised event type: {type(event)}")

    # ═══════════════════════════════════════════════════════════════
    #  Internal reader loop
    # ═══════════════════════════════════════════════════════════════

    def _loop(self) -> None:
        prev: dict[str, int] = {}
        while self._running:
            for ch, val in read_frames(self._ser):
                if prev.get(ch) == val:
                    continue                # no change, skip
                prev[ch] = val
                self._dispatch(ch, val)
            time.sleep(0.02)

    def _dispatch(self, ch: str, val: int) -> None:
        if ch in (CH_LIVE, CH_NEXT):
            for event in self._decode_row8(ch, val):
                for cb in self._button_cbs:
                    self._invoke(cb, event)

        elif ch == CH_MISC:
            for event in self._decode_mini(val):
                for cb in self._button_cbs:
                    self._invoke(cb, event)

        elif ch == CH_TBAR:
            event = self._decode_tbar(val)
            self._last_tbar = event
            for cb in self._tbar_cbs:
                self._invoke(cb, event)

        elif ch in DIAL_NAMES:
            event = DialEvent(dial=DIAL_NAMES[ch], value=val)
            self._last_dials[event.dial] = event
            for cb in self._dial_cbs:
                self._invoke(cb, event)

    def _invoke(self, cb: Callable, event) -> None:
        if self._threadsafe:
            self._queue.put((cb, event))
        else:
            cb(event)

    # ═══════════════════════════════════════════════════════════════
    #  Frame decoders
    # ═══════════════════════════════════════════════════════════════

    def _decode_row8(self, ch: str, val: int) -> list[ButtonEvent]:
        """
        Decode a LIVE or NEXT frame into a list of pressed/released
        ButtonEvents by comparing with the previous frame.
        """
        row      = 'LIVE' if ch == CH_LIVE else 'NEXT'
        prev_set = self._prev_live if ch == CH_LIVE else self._prev_next

        # Determine which buttons are currently held
        if val == 0xFF:
            now: set[int] = set()
        else:
            now = {n for n in range(1, 9) if not (val >> (8 - n) & 1)}

        events: list[ButtonEvent] = []

        # Buttons newly pressed (in now but not in prev)
        for btn in sorted(now - prev_set):
            events.append(ButtonEvent(
                row=row, button=btn, label=ROW_LABELS[btn], held=True,
            ))

        # Buttons newly released (in prev but not in now)
        for btn in sorted(prev_set - now):
            events.append(ButtonEvent(
                row=row, button=btn, label=ROW_LABELS[btn], held=False,
            ))

        # Update tracking state
        if ch == CH_LIVE:
            self._prev_live = now
        else:
            self._prev_next = now

        return events

    def _decode_mini(self, val: int) -> list[ButtonEvent]:
        """
        Decode a ch3 input frame into ButtonEvents.

        Buttons 1-4 (FADE OVERLAY … TAKE ALL) emit row='MINI' and have
        output LEDs addressable via panel.mini.
        Button 5 (AUTO) emits row='AUTO', button 6 (TAKE) emits row='TAKE'.
        AUTO and TAKE have no LEDs; use on_auto / on_take to react to them.
        """
        if val in (0xFE, 0xFF):
            now: set[int] = set()
        else:
            seen_labels: set[str] = set()
            now = set()
            for bit, label in CH3_INPUT_BITS:
                if not (val & (1 << bit)) and label not in seen_labels:
                    seen_labels.add(label)
                    now.add(CH3_BTN_LED[label])

        events: list[ButtonEvent] = []

        for btn in sorted(now - self._prev_mini):
            events.append(ButtonEvent(
                row    = CH3_EVENT_ROW[btn],
                button = btn if btn <= 4 else 1,
                label  = CH3_EVENT_LABELS[btn],
                held   = True,
            ))

        for btn in sorted(self._prev_mini - now):
            events.append(ButtonEvent(
                row    = CH3_EVENT_ROW[btn],
                button = btn if btn <= 4 else 1,
                label  = CH3_EVENT_LABELS[btn],
                held   = False,
            ))

        self._prev_mini = now
        return events

    @staticmethod
    def _decode_tbar(val: int) -> TBarEvent:
        """
        Decode a T-bar frame.
        Hardware: 0x00 = physical top (max), 0xFF = physical bottom (min).
        position is normalised to 0.0 (bottom) – 1.0 (top).
        """
        position = (255 - val) / 255.0
        return TBarEvent(
            raw       = val,
            position  = round(position, 4),
            at_top    = (val == 0x00),
            at_bottom = (val == 0xFF),
        )