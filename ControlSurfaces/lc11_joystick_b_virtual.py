#!/usr/bin/env python3
"""
lc11_joystick_b_virtual.py  (Windows)
───────────────────────────────────────────────────────────────────────
Maps the LC-11's JOYSTICK_B to a virtual game controller axis on
Windows, and maps the joystick's click (pushing it straight down) to a
Shift keypress.

HOW IT WORKS
    This only talks to the public control_surfaces library API — no
    reaching into devices/lc11.py's wire-protocol internals. JOYSTICK_B
    shows up as two event types on the same control name:
      - a ButtonEvent   -> fires when you click the stick down/up
      - a JoystickEvent -> fires on stick movement, with a single
                            library-provided `.value` (int | None)

    surface.on('JOYSTICK_B') catches both and forwards them:
      - JoystickEvent -> left stick X/Y on a virtual Xbox 360 controller
        (via vgamepad, which talks to the ViGEmBus driver — this is
        what actually makes Windows see a real game controller)
      - ButtonEvent   -> Shift key press/release (via the `keyboard`
        library — a virtual gamepad button wouldn't act as an actual
        Shift keypress in other apps, so this is kept separate)

NOTE ON AXES
    JoystickEvent.value is a single scalar (int(raw, 16)), so an
    earlier version of this script drove X only and left Y fixed —
    which is why only left/right worked and up/down didn't.

    To get both axes, this version splits JoystickEvent.raw — the
    untouched hex payload string, itself a public field on the
    library's own JoystickEvent dataclass, not something pulled from
    devices/lc11.py's internals — into two halves: first half -> X,
    second half -> Y. The library's docstring is explicit that this
    payload hasn't been decoded into confirmed X/Y fields upstream, so
    this split is a best-effort guess, not a documented layout.

    Run with --debug and waggle the stick through all four directions
    while watching the printed raw/x/y values. If up/down feels
    swapped, inverted, or dead, that confirms the split guess is wrong
    for your unit — adjust split_axes() below (e.g. swap which half is
    X vs Y, or try a different split point) until movement matches.

    Each axis self-calibrates independently: it tracks the min/max
    seen at runtime and rescales to the full axis range live, so it
    settles in after a few seconds of moving the stick to its corners.

REQUIREMENTS
    1. Install the ViGEmBus driver (one-time, does the actual "create a
       virtual controller" work at the OS level):
           https://github.com/ViGEm/ViGEmBus/releases
    2. pip install vgamepad keyboard pyserial
    3. The control_surfaces package (from control_surfaces.zip)
       importable, e.g. run this from the folder containing
       control_surfaces/, or `pip install -e .` it first.
    4. Run your terminal as Administrator. The `keyboard` library needs
       elevated privileges on Windows to send key events reliably.

USAGE
    python lc11_joystick_b_virtual.py                   # auto-detect LC-11
    python lc11_joystick_b_virtual.py --port COM5
    python lc11_joystick_b_virtual.py --debug            # print .value as it arrives
    python lc11_joystick_b_virtual.py --key right shift  # bind a different key
"""

from __future__ import annotations

import argparse
import sys

try:
    import vgamepad as vg
except ImportError:
    sys.exit(
        "Missing dependency 'vgamepad'. Install it with:\n"
        "    pip install vgamepad\n"
        "and make sure the ViGEmBus driver is installed:\n"
        "    https://github.com/ViGEm/ViGEmBus/releases"
    )

try:
    import keyboard
except ImportError:
    sys.exit("Missing dependency 'keyboard'. Install it with:\n    pip install keyboard")

from control_surfaces import ButtonEvent, JoystickEvent, LC11Surface, auto_connect

AXIS_MIN = -32768
AXIS_MAX = 32767
AXIS_MID = 0


class AxisCalibrator:
    """
    Tracks the observed min/max of JoystickEvent.value and rescales the
    current reading into [AXIS_MIN, AXIS_MAX] on the fly. Starts
    centered and widens its range as new extremes are seen, so it
    settles into something sane within a few seconds of moving the
    stick to its corners without needing a hardcoded value range.
    """

    def __init__(self) -> None:
        self._lo: int | None = None
        self._hi: int | None = None

    def scale(self, value: int) -> int:
        if self._lo is None or value < self._lo:
            self._lo = value
        if self._hi is None or value > self._hi:
            self._hi = value

        if self._hi == self._lo:
            return AXIS_MID

        span = self._hi - self._lo
        normalized = (value - self._lo) / span          # 0.0 .. 1.0
        return round(AXIS_MIN + normalized * (AXIS_MAX - AXIS_MIN))


def split_axes(raw: str) -> tuple[int, int]:
    """
    Best-effort split of JOYSTICK_B's raw hex payload into (x_raw, y_raw).
    See the module docstring's NOTE ON AXES — this is a guess (first
    half = X, second half = Y), meant to be confirmed/corrected with
    --debug, not a documented protocol detail.
    """
    raw = raw.strip()
    try:
        if len(raw) >= 2 and len(raw) % 2 == 0:
            mid = len(raw) // 2
            return int(raw[:mid], 16), int(raw[mid:], 16)
        return int(raw, 16), int(raw, 16)   # odd-length fallback: same value on both axes
    except ValueError:
        return 0, 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", help="Serial port for the LC-11, e.g. COM5. Auto-detects if omitted.")
    parser.add_argument("--key", default="shift", help="Key JOYSTICK_B's click maps to (keyboard lib name).")
    parser.add_argument("--debug", action="store_true", help="Print JOYSTICK_B telemetry as it arrives.")
    args = parser.parse_args()

    gamepad = vg.VX360Gamepad()
    x_cal = AxisCalibrator()
    y_cal = AxisCalibrator()

    print("Virtual Xbox 360 controller created via ViGEmBus.")
    print(f"JOYSTICK_B click -> '{args.key}' key")
    print("Ctrl-C to quit.\n")

    surface = LC11Surface(args.port) if args.port else auto_connect(auto_leds=False)
    if not isinstance(surface, LC11Surface):
        sys.exit(f"auto_connect() found a {type(surface).__name__}, not an LC-11. Pass --port explicitly.")

    with surface:

        @surface.on("JOYSTICK_B")
        def _(event):
            if isinstance(event, ButtonEvent):
                if event.held:
                    keyboard.press(args.key)
                else:
                    keyboard.release(args.key)
                if args.debug:
                    print(f"  [click] {'DOWN' if event.held else 'up'}")

            elif isinstance(event, JoystickEvent):
                if event.value is None:
                    return
                x_raw, y_raw = split_axes(event.raw)
                x = x_cal.scale(x_raw)
                y = y_cal.scale(y_raw)
                gamepad.left_joystick(x_value=x, y_value=y)
                gamepad.update()
                if args.debug:
                    print(f"  [move]  raw={event.raw!r}  x_raw={x_raw} y_raw={y_raw}  ->  x={x} y={y}")

        try:
            surface.run()
        finally:
            keyboard.release(args.key)   # don't leave the key stuck down on exit
            gamepad.reset()
            gamepad.update()


if __name__ == "__main__":
    main()