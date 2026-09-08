# ═══════════════════════════════════════════════════════════════════
# control_surfaces/led_bank.py
#
# Generic state-tracking writer for a group of LED bits that happen to
# share one wire-level byte (or wider word). Both TriCasterVM and the
# LC-11 have this pattern: several unrelated-looking bits get OR'd/
# AND'd into a single transmitted value, so lighting one LED means
# "read the last value we sent, flip one bit, resend the whole word" --
# never a single-purpose frame.
#
# This lives at the wire-protocol layer only. Callers of ControlSurface
# never see a LEDBank directly or need to know which controls happen to
# share one -- that bookkeeping is exactly the kind of wire-format
# artifact the flat control-name API is designed to hide.
# ═══════════════════════════════════════════════════════════════════

from __future__ import annotations

import threading
from typing import Callable


class LEDBank:
    """
    Tracks on/off state for a set of named LED bits that must be
    written together as one value.

    Parameters
    ----------
    write : callable(int) -> None
        Transmits the current combined word for this bank.
    bits : dict[str, int]
        control name -> bit value (power of two) within the word.
    baseline : int
        The word's value when every tracked LED is off. Almost always
        "all bits set" (0xFF / 0xFFF) since both devices use active-low
        LED encoding, but kept configurable since one observed group
        (LC-11's '^F') has a baseline that isn't all-ones.
    active_low : bool
        True  -> lighting a bit means *clearing* it from baseline.
        False -> lighting a bit means *setting* it (not currently used
                 by either device, but kept for completeness/future
                 hardware).
    """

    def __init__(
        self,
        write:      Callable[[int], None],
        bits:       dict[str, int],
        baseline:   int  = 0xFF,
        active_low: bool = True,
    ) -> None:
        self._write      = write
        self._bits        = bits
        self._baseline    = baseline
        self._active_low  = active_low
        self._on: set[str] = set()
        self._lock = threading.RLock()

    def set(self, name: str) -> None:
        with self._lock:
            target = self._on | {name}
            self._push(target)
            self._on = target

    def clear(self, name: str) -> None:
        with self._lock:
            target = self._on - {name}
            self._push(target)
            self._on = target

    def clear_all(self) -> None:
        with self._lock:
            self._push(set())
            self._on.clear()

    def is_on(self, name: str) -> bool:
        with self._lock:
            return name in self._on

    @property
    def lit(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._on)

    def _push(self, names: set[str]) -> None:
        val = self._baseline
        for name in names:
            bit = self._bits[name]
            if self._active_low:
                val &= ~bit
            else:
                val |= bit
        self._write(val & 0xFFFF)
