# ═══════════════════════════════════════════════════════════════════
# control_surfaces/devices/tricaster.py
#
# TriCasterSurface -- ControlSurfaces driver for the TriCaster VM
# hardware panel.
#
# Wire protocol (unchanged from the original tricaster_panel library,
# which already had this fully solved):
#   Serial: 115200 baud, 8N1
#   Frame:  ~{ch}{val:02X}\r   (5 bytes: 0x7E ch_byte hex×2 0x0D)
#
#   ch '2'  LIVE row    (8 buttons, dedicated channel, output+input)
#   ch '1'  NEXT row    (8 buttons, dedicated channel, output+input)
#   ch '3'  shared byte: FADE_OVERLAY / TAKE_OVERLAY / FADE_ALL /
#           TAKE_ALL / AUTO / TAKE (input only, x2 contacts) on the
#           read side; FADE_OVERLAY / TAKE_OVERLAY / FADE_ALL /
#           TAKE_ALL / TBAR_LED_TOP / TBAR_LED_BOTTOM on the write side
#   ch '4'  T-bar position (input only)
#   ch '5'  Transition Speed dial (input only)
#   ch '6'  Transition Select dial (input only)
#   ch '7'  Overlay Select dial (input only)
#
# LIVE and NEXT are the one TriCaster relationship kept in its control
# names (LIVE_CAM_1, NEXT_CAM_1, ...): both rows repeat the exact same
# 8 source buttons, so the row is a real, meaningful part of the
# identity of the control -- exactly the same reasoning that keeps
# EFFECTS/LIVE/PREVIEW in the LC-11's row-button names. Everything
# else that used to be lumped together only because it shares ch3's
# byte (mini-row buttons, T-bar endpoint LEDs) is fully flattened:
# each gets its own plain name and no group to go through.
# ═══════════════════════════════════════════════════════════════════

from __future__ import annotations

import serial

from ..control    import Control, Emits
from ..led_bank   import LEDBank
from ..surface    import ControlSurface
from ..auto_leds  import AutoLEDs

BAUD = 115200

# ── row buttons: LIVE / NEXT (8 columns, identical set, own channel) ──
CH_LIVE = '2'
CH_NEXT = '1'
CH_MISC = '3'
CH_TBAR = '4'

ROW_CHANNELS = {'LIVE': CH_LIVE, 'NEXT': CH_NEXT}

ROW_COLUMNS = ['CAM_1', 'CAM_2', 'CAM_3', 'VGA', 'VCR', 'PIC', 'BKG', 'BLK']
# bit(8-n) cleared lights column n (1-indexed, MSB-first)
ROW_COLUMN_BIT = {col: 1 << (8 - n) for n, col in enumerate(ROW_COLUMNS, start=1)}

# ── ch3 shared byte: read-side bit -> control name (AUTO/TAKE dedup) ──
CH3_INPUT_BITS = [
    (7, 'FADE_OVERLAY'),
    (6, 'TAKE_OVERLAY'),
    (5, 'FADE_ALL'),
    (4, 'TAKE_ALL'),
    (3, 'AUTO'),
    (2, 'TAKE'),   # first contact  }  both fire together;
    (1, 'TAKE'),   # second contact }  dedup collapses them
]

# ── ch3 shared byte: write-side control name -> bit ──
CH3_LED_BITS = {
    'FADE_OVERLAY':   0x80,
    'TAKE_OVERLAY':   0x40,
    'FADE_ALL':       0x20,
    'TAKE_ALL':       0x10,
    'TBAR_LED_BOTTOM': 0x04,
    'TBAR_LED_TOP':    0x01,
}

# ── dial channel -> canonical name (position telemetry only) ──
DIAL_CHANNELS = {
    '5': 'TRANSITION_SPEED',
    '6': 'TRANSITION_SELECT',
    '7': 'OVERLAY_SELECT',
}


def _build_controls() -> dict[str, Control]:
    controls: dict[str, Control] = {}

    for row in ROW_CHANNELS:
        for col in ROW_COLUMNS:
            name = f'{row}_{col}'
            controls[name] = Control(name=name, emits=Emits.BUTTON, has_led=True)

    for name in ('FADE_OVERLAY', 'TAKE_OVERLAY', 'FADE_ALL', 'TAKE_ALL'):
        controls[name] = Control(name=name, emits=Emits.BUTTON, has_led=True)
    for name in ('AUTO', 'TAKE'):
        controls[name] = Control(name=name, emits=Emits.BUTTON, has_led=False)

    controls['TBAR'] = Control(name='TBAR', emits=Emits.TBAR, has_led=False)
    controls['TBAR_LED_TOP'] = Control(
        name='TBAR_LED_TOP', emits=Emits.NONE, has_led=True,
        aliases=('top', 'max'),
    )
    controls['TBAR_LED_BOTTOM'] = Control(
        name='TBAR_LED_BOTTOM', emits=Emits.NONE, has_led=True,
        aliases=('bottom', 'min'),
    )

    for name in DIAL_CHANNELS.values():
        controls[name] = Control(name=name, emits=Emits.DIAL, has_led=False)

    return controls


class TriCasterSurface(ControlSurface):
    """
    ControlSurfaces driver for the TriCaster VM hardware panel.

        with TriCasterSurface('/dev/ttyUSB0', auto_leds=True) as surface:
            surface.run()

        with TriCasterSurface('/dev/ttyUSB0') as surface:
            surface.set('LIVE_CAM_1')
            surface.set(['LIVE_CAM_3', 'NEXT_VGA'])
            surface.set_only('LIVE_BLK')
            surface.clear('LIVE_CAM_1')

            @surface.on_button
            def _(event):
                print(event.control, event.held)

            @surface.on_tbar
            def _(event):
                print(event.position)

            surface.run()
    """

    def __init__(
        self,
        port:       str,
        baud:       int  = BAUD,
        auto_leds:  bool = False,
        threadsafe: bool = False,
    ) -> None:
        super().__init__(port, baud, _build_controls(), threadsafe=threadsafe)

        self._ser: serial.Serial | None = None

        # ── LED banks: LIVE row, NEXT row, and the ch3 shared byte ──
        self._banks = {
            'LIVE': LEDBank(lambda v: self._send_frame(CH_LIVE, v), ROW_COLUMN_BIT),
            'NEXT': LEDBank(lambda v: self._send_frame(CH_NEXT, v), ROW_COLUMN_BIT),
            'MISC': LEDBank(lambda v: self._send_frame(CH_MISC, v), CH3_LED_BITS),
        }
        self._bank_for: dict[str, tuple[LEDBank, str]] = {}
        for row in ROW_CHANNELS:
            bank = self._banks[row]
            for col in ROW_COLUMNS:
                self._bank_for[f'{row}_{col}'] = (bank, col)
        for name in CH3_LED_BITS:
            self._bank_for[name] = (self._banks['MISC'], name)

        # ── input-side delta tracking ──────────────────────────────
        self._prev_row: dict[str, set[str]] = {'LIVE': set(), 'NEXT': set()}
        self._prev_misc: set[str] = set()

        # ── auto LED plug-in ─────────────────────────────────────────
        self.auto_leds = None
        if auto_leds:
            self.auto_leds = AutoLEDs()
            self.auto_leds.attach(self)

    # ═══════════════════════════════════════════════════════════════
    #  Connection
    # ═══════════════════════════════════════════════════════════════

    def _open(self) -> None:
        self._ser = serial.Serial(self.port, self.baud, timeout=0.1)

    def _close(self) -> None:
        if self._ser and self._ser.is_open:
            self._ser.close()
        self._ser = None

    # ═══════════════════════════════════════════════════════════════
    #  Framing
    # ═══════════════════════════════════════════════════════════════

    def _send_frame(self, ch: str, val: int) -> None:
        self._ser.write(f"~{ch}{val:02X}\r".encode('ascii'))

    def _read_frames(self) -> list[tuple[str, int]]:
        if not self._ser or not self._ser.in_waiting:
            return []
        raw = self._ser.read(self._ser.in_waiting)
        frames: list[tuple[str, int]] = []
        i = 0
        while i <= len(raw) - 5:
            if raw[i] == 0x7E and raw[i + 4] == 0x0D:
                try:
                    ch  = chr(raw[i + 1])
                    val = int(chr(raw[i + 2]) + chr(raw[i + 3]), 16)
                    frames.append((ch, val))
                except (ValueError, UnicodeDecodeError):
                    pass
                i += 5
            else:
                i += 1
        return frames

    # ═══════════════════════════════════════════════════════════════
    #  LED write
    # ═══════════════════════════════════════════════════════════════

    def _write_led(self, name: str, on: bool) -> None:
        bank, key = self._bank_for[name]
        bank.set(key) if on else bank.clear(key)

    # ═══════════════════════════════════════════════════════════════
    #  Reader
    # ═══════════════════════════════════════════════════════════════

    def _poll(self) -> None:
        for ch, val in self._read_frames():
            if ch in (CH_LIVE, CH_NEXT):
                self._decode_row(ch, val)
            elif ch == CH_MISC:
                self._decode_misc(val)
            elif ch == CH_TBAR:
                self._emit_tbar(val)
            elif ch in DIAL_CHANNELS:
                self._emit_dial(DIAL_CHANNELS[ch], val)

    def _decode_row(self, ch: str, val: int) -> None:
        row = 'LIVE' if ch == CH_LIVE else 'NEXT'
        now: set[str] = set()
        if val != 0xFF:
            for n, col in enumerate(ROW_COLUMNS, start=1):
                if not (val >> (8 - n) & 1):
                    now.add(col)

        prev = self._prev_row[row]
        for col in sorted(now - prev):
            self._emit_button(f'{row}_{col}', True)
        for col in sorted(prev - now):
            self._emit_button(f'{row}_{col}', False)
        self._prev_row[row] = now

    def _decode_misc(self, val: int) -> None:
        now: set[str] = set()
        if val not in (0xFE, 0xFF):
            for bit, name in CH3_INPUT_BITS:
                if not (val & (1 << bit)):
                    now.add(name)

        for name in sorted(now - self._prev_misc):
            self._emit_button(name, True)
        for name in sorted(self._prev_misc - now):
            self._emit_button(name, False)
        self._prev_misc = now
