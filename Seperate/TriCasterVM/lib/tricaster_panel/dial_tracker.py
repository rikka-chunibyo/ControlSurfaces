# ═══════════════════════════════════════════════════════════════════
# tricaster_panel/dial_tracker.py
#
# Seamless infinite-scroll handler for hardware dials that report
# raw 0–255 positions and wrap at both ends.
#
# Hardware reality:
#   Turning right past 255 → next report is 0
#   Turning left  past 0   → next report is 255
#
# DialTracker corrects for wrap-around by checking whether the raw
# delta exceeds half the range (128).  If it does, the value crossed
# the 0/255 boundary in the opposite direction; the sign-flipped
# correction reconstructs the true small delta.
#
# The result is a *signed, unbounded integer* that grows when the
# dial turns right and shrinks when it turns left — no clamping,
# no limits in either direction.
#
# Typical use::
#
#   tracker = DialTracker()
#
#   @panel.on_dial
#   def _(event: DialEvent):
#       if event.dial == 'TRANSITION_SPEED':
#           delta = tracker.update(event.value)
#           print(f"delta={delta:+d}  position={tracker.position}")
#
# Callback variant::
#
#   tracker = DialTracker()
#
#   @tracker.on_change
#   def _(delta, position):
#       ...
#
#   @panel.on_dial
#   def _(event: DialEvent):
#       if event.dial == 'TRANSITION_SPEED':
#           tracker.update(event.value)   # fires on_change automatically
#
# Thread safety:
#   update() is called from the panel's reader thread; position is
#   read from the show/UI thread.  Python's GIL makes the int
#   assignment atomic, so no locking is needed for this common pattern.
# ═══════════════════════════════════════════════════════════════════

from __future__ import annotations
from typing import Callable


class DialTracker:
    """
    Converts a wrapping 0–255 hardware-dial position into a signed,
    unbounded running total.

    Parameters
    ----------
    initial : int
        Starting value for :attr:`position` (default 0).

    Attributes
    ----------
    position : int
        Accumulated signed integer.  Grows positively when the dial
        is turned right/up; shrinks when turned left/down.  Never
        clamped — :attr:`position` can reach any integer value.

    Wrap detection
    ~~~~~~~~~~~~~~
    The dial hardware emits 0–255 and wraps at both ends.  A naive
    subtraction would see a jump of ~255 when the dial crosses a
    boundary.  DialTracker applies a signed 8-bit correction: if the
    raw delta exceeds 128 in either direction it must have wrapped, so
    the full-range complement is applied.  The corrected delta is
    always a small signed value (typically ±1–4 per detent).

    Examples
    --------
    Right-turn crossing 255→0::

        tracker = DialTracker()
        tracker.update(254)   # → 0   (first call, no delta)
        tracker.update(255)   # → +1
        tracker.update(0)     # raw delta = 0-255 = -255 → +256-255 = +1 ✓
        tracker.update(1)     # → +1
        assert tracker.position == 3

    Left-turn crossing 0→255::

        tracker = DialTracker()
        tracker.update(1)     # → 0
        tracker.update(0)     # → -1
        tracker.update(255)   # raw delta = 255-0 = +255 → 255-256 = -1 ✓
        tracker.update(254)   # → -1
        assert tracker.position == -3
    """

    _RANGE: int = 256   # 8-bit full range
    _HALF:  int = 128   # wrap-detection threshold

    def __init__(self, initial: int = 0) -> None:
        self._last:      int | None                        = None
        self._position:  int                               = initial
        self._callbacks: list[Callable[[int, int], None]] = []

    # ── public API ────────────────────────────────────────────────

    def update(self, raw: int) -> int:
        """
        Feed a new raw dial value and return the signed delta.

        On the very first call there is no previous position to
        compare against, so 0 is returned and the tracker is
        initialised to *raw* as its baseline.

        Parameters
        ----------
        raw : int
            Raw 0–255 position emitted by the hardware dial.

        Returns
        -------
        int
            Signed detent change for this step.
            Positive = turned right / up / increase.
            Negative = turned left / down / decrease.
            0 on the first call (no baseline yet).

        Side effects
        ------------
        Updates :attr:`position` and fires all :meth:`on_change`
        callbacks (in registration order) when *delta* is non-zero.
        """
        if self._last is None:
            self._last = raw
            return 0

        delta = raw - self._last

        # Signed 8-bit wrap correction:
        #   raw delta > +128 → dial wrapped rightward (255→0): subtract 256
        #   raw delta < -128 → dial wrapped leftward  (0→255): add    256
        if delta > self._HALF:
            delta -= self._RANGE
        elif delta < -self._HALF:
            delta += self._RANGE

        self._last      = raw
        self._position += delta

        if delta and self._callbacks:
            for cb in self._callbacks:
                cb(delta, self._position)

        return delta

    @property
    def position(self) -> int:
        """Accumulated signed position (unbounded, never clamped)."""
        return self._position

    def reset(self, position: int = 0) -> None:
        """
        Reset the accumulated position and forget the last raw value.

        The next :meth:`update` call after a reset will return 0 (the
        tracker treats it as the first sample again).

        Parameters
        ----------
        position : int
            New starting value for :attr:`position` (default 0).
        """
        self._position = position
        self._last     = None

    def on_change(self, fn: Callable[[int, int], None]) -> Callable:
        """
        Register a callback that fires after every non-zero :meth:`update`.

        The callback receives ``(delta: int, position: int)`` where
        *delta* is the corrected step just applied and *position* is
        the new accumulated total.

        Returns the callback unchanged so it can be used as a decorator::

            tracker = DialTracker()

            @tracker.on_change
            def _(delta, position):
                print(f"dial moved {delta:+d}, now at {position}")

            @panel.on_dial
            def _(event: DialEvent):
                if event.dial == 'TRANSITION_SPEED':
                    tracker.update(event.value)
        """
        self._callbacks.append(fn)
        return fn
