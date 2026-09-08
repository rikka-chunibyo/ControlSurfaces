# ═══════════════════════════════════════════════════════════════════
# tricaster_panel/leds.py
#
# LED state managers.  All four row classes share the same public
# API:  set / clear / set_only — each accepting int, str, or a
# list of either, case-insensitive.
#
# State is tracked internally so callers never have to manage byte
# masks.  MiniRowLEDs and FaderLEDs share ch3 but each owns the
# bits for its own buttons; _push() on either always writes the
# correct combined byte.
# ═══════════════════════════════════════════════════════════════════

from __future__ import annotations

from .protocol import send_frame
from .constants import (
    CH_LIVE, CH_NEXT, CH_MISC,
    BTN8,
    ROW_LABELS, ROW_LABELS_INV,
    MINI_LABELS, MINI_LABELS_INV, MINI_BITS,
    FADER_LABELS, FADER_ALIASES, FADER_BITS,
)


# ── helpers ───────────────────────────────────────────────────────

def _as_list(val) -> list:
    """Wrap a scalar in a list; pass a list through unchanged."""
    if isinstance(val, list):
        return val
    return [val]


# ═══════════════════════════════════════════════════════════════════
#  RowLEDs — LIVE or NEXT (8 buttons, dedicated channel)
# ═══════════════════════════════════════════════════════════════════

class RowLEDs:

    def __init__(self, ser, channel: str):
        self._ser     = ser
        self._ch      = channel
        self._state: set[int] = set()

    # ── public API ────────────────────────────────────────────────

    def set(self, buttons) -> None:
        """Turn on one or more buttons; others are unchanged."""
        self._state.update(self._resolve(buttons))
        self._push()

    def clear(self, buttons=None) -> None:
        """
        Turn off buttons.
        clear()      — whole row off
        clear(1)     — button 1 off, others unchanged
        clear([1,3]) — buttons 1 and 3 off, others unchanged
        """
        if buttons is None:
            self._state.clear()
        else:
            self._state.difference_update(self._resolve(buttons))
        self._push()

    def set_only(self, buttons) -> None:
        """Turn on target buttons and turn off everything else."""
        self._state = set(self._resolve(buttons))
        self._push()

    # ── internals ────────────────────────────────────────────────

    def _resolve(self, buttons) -> list[int]:
        """
        Normalise any mix of ints and strings to a list of button
        numbers.  Strings are matched case-insensitively.
        """
        results = []
        for item in _as_list(buttons):
            if isinstance(item, int):
                if item not in ROW_LABELS:
                    valid = list(ROW_LABELS.keys())
                    raise ValueError(f"Button {item!r} out of range. Valid: {valid}")
                results.append(item)
            elif isinstance(item, str):
                key = item.upper()
                if key not in ROW_LABELS_INV:
                    valid = list(ROW_LABELS_INV.keys())
                    raise ValueError(f"Unknown button label {item!r}. Valid: {valid}")
                results.append(ROW_LABELS_INV[key])
            else:
                raise TypeError(f"Expected int or str, got {type(item).__name__!r}")
        return results

    def _push(self) -> None:
        val = 0xFF
        for btn in self._state:
            val &= BTN8[btn]
        send_frame(self._ser, self._ch, val)


# ═══════════════════════════════════════════════════════════════════
#  MiniRowLEDs — 4 named buttons sharing ch3 with FaderLEDs
# ═══════════════════════════════════════════════════════════════════

class MiniRowLEDs:

    def __init__(self, ser):
        self._ser     = ser
        self._state: set[int] = set()
        self._fader: FaderLEDs | None = None

    def _link(self, fader: FaderLEDs) -> None:
        """Called once by TriCasterPanel to set up the shared-channel cross-reference."""
        self._fader = fader

    # ── public API ────────────────────────────────────────────────

    def set(self, buttons) -> None:
        self._state.update(self._resolve(buttons))
        self._push()

    def clear(self, buttons=None) -> None:
        if buttons is None:
            self._state.clear()
        else:
            self._state.difference_update(self._resolve(buttons))
        self._push()

    def set_only(self, buttons) -> None:
        self._state = set(self._resolve(buttons))
        self._push()

    # ── internals ────────────────────────────────────────────────

    def _resolve(self, buttons) -> list[int]:
        results = []
        for item in _as_list(buttons):
            if isinstance(item, int):
                if item not in MINI_LABELS:
                    valid = list(MINI_LABELS.keys())
                    raise ValueError(f"Mini button {item!r} out of range. Valid: {valid}")
                results.append(item)
            elif isinstance(item, str):
                key = item.upper()
                if key not in MINI_LABELS_INV:
                    valid = list(MINI_LABELS_INV.keys())
                    raise ValueError(f"Unknown mini button {item!r}. Valid: {valid}")
                results.append(MINI_LABELS_INV[key])
            else:
                raise TypeError(f"Expected int or str, got {type(item).__name__!r}")
        return results

    def _push(self) -> None:
        """Write the combined mini + fader state to ch3."""
        val = 0xFF
        for btn in self._state:
            val &= ~MINI_BITS[btn]
        if self._fader:
            for btn in self._fader._state:
                val &= ~FADER_BITS[btn]
        send_frame(self._ser, CH_MISC, val)


# ═══════════════════════════════════════════════════════════════════
#  FaderLEDs — top / bottom indicator sharing ch3 with MiniRowLEDs
# ═══════════════════════════════════════════════════════════════════

class FaderLEDs:

    def __init__(self, ser):
        self._ser     = ser
        self._state: set[int] = set()
        self._mini: MiniRowLEDs | None = None

    def _link(self, mini: MiniRowLEDs) -> None:
        self._mini = mini

    # ── public API ────────────────────────────────────────────────

    def set(self, buttons) -> None:
        """
        set(1) / set('top') / set('max')     → top LED on
        set(2) / set('bottom') / set('min')  → bottom LED on
        set([1, 2])                           → both on
        """
        self._state.update(self._resolve(buttons))
        self._push()

    def clear(self, buttons=None) -> None:
        if buttons is None:
            self._state.clear()
        else:
            self._state.difference_update(self._resolve(buttons))
        self._push()

    def set_only(self, buttons) -> None:
        self._state = set(self._resolve(buttons))
        self._push()

    # ── internals ────────────────────────────────────────────────

    def _resolve(self, buttons) -> list[int]:
        results = []
        for item in _as_list(buttons):
            if isinstance(item, int):
                if item not in FADER_LABELS:
                    raise ValueError(f"Fader button {item!r} out of range. Valid: 1 (top), 2 (bottom)")
                results.append(item)
            elif isinstance(item, str):
                key = item.lower()
                if key not in FADER_ALIASES:
                    raise ValueError(f"Unknown fader label {item!r}. Valid: top, max, bottom, min")
                results.append(FADER_ALIASES[key])
            else:
                raise TypeError(f"Expected int or str, got {type(item).__name__!r}")
        return results

    def _push(self) -> None:
        """Write the combined mini + fader state to ch3."""
        val = 0xFF
        if self._mini:
            for btn in self._mini._state:
                val &= ~MINI_BITS[btn]
        for btn in self._state:
            val &= ~FADER_BITS[btn]
        send_frame(self._ser, CH_MISC, val)
