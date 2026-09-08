# ═══════════════════════════════════════════════════════════════════
# control_surfaces/devices/lc11.py
#
# LC11Surface -- ControlSurfaces driver for the NewTek LiveControl
# LC-11 control surface. Built from lc11_protocol_map.py, the fuller
# reverse-engineered "source of truth" -- not from the earlier, partial
# lc11driver.py.
#
# Wire protocol summary (ASCII, \r-delimited, 9600 8N1):
#   Wake-up: 0x43 0x00 0x00 0x00
#   A frame's first char is its PREFIX ('~' or '^'); the next char is
#   its GROUP ID. (prefix, group_id) is the only reliable key -- group
#   ids repeat across prefixes by coincidence (e.g. '~1' = PREVIEW bus
#   row, '^1' = the overlay button group; unrelated).
#
#   ── bus rows: EFFECTS / LIVE / PREVIEW, prefix '~', group F/2/1 ──
#   3 hex digits, 12-bit inverted mask, 11 columns used. HARDWARE
#   QUIRK: transmitted as two separate \r-terminated writes ("~FXX"
#   then the final hex digit alone) -- reassembled before parsing.
#   These are the one place row identity is kept in the control name
#   (LIVE_1, PREVIEW_TXT, ...): the 11 columns really do repeat
#   identically across all three rows, a real relationship, not a
#   wire-format coincidence.
#
#   ── dials: '~8/9/5/6/7' telemetry + '^2' click, baseline FF ──
#   ── joysticks: '^5/7' telemetry + bits within the '^F' group ──
#   ── '^F' group: FADE, FX_BUTTON (LED) + joystick clicks (no LED),
#      baseline 0xF7 (not all-ones -- confirmed via full sweep) ──
#   ── '^1' group: FTB/ALT/EXT_OVERLAY/DDR1_OVERLAY/DDR2_OVERLAY/
#      TXT_OVERLAY, all LED, baseline 0xFF ──
#   ── '~3' group: TAKE/AUTO (no LED) + FADE_ALL/TAKE_ALL/
#      FADE_OVERLAY/TAKE_OVERLAY (LED) + TBAR_LED_TOP/BOTTOM
#      (output only, no matching input bit), baseline 0xFF ──
#   ── T-bar: '~4', single hex byte, input only ──
#
# Every group above that carries more than one control shares its byte
# only because of how the hardware happens to wire it -- exactly the
# "physically and functionally unrelated controls sharing a wire
# prefix" pattern this library exists to hide. Each control gets its
# own flat name; nothing about ^F/^1/~3 grouping is visible outside
# this file.
# ═══════════════════════════════════════════════════════════════════

from __future__ import annotations

import time
import serial

from ..control    import Control, Emits
from ..led_bank   import LEDBank
from ..surface    import ControlSurface
from ..auto_leds  import AutoLEDs

BAUD          = 9600
WAKE_SEQUENCE = b'\x43\x00\x00\x00'

# ── bus rows: EFFECTS / LIVE / PREVIEW (11 identical columns) ───────
BUS_ROW_PREFIX_TO_ROW = {'F': 'EFFECTS', '2': 'LIVE', '1': 'PREVIEW'}
BUS_ROW_ROW_TO_PREFIX = {v: k for k, v in BUS_ROW_PREFIX_TO_ROW.items()}
BUS_ROW_COLUMNS = ['1', '2', '3', '4', '5', '6', 'EXT', 'DDR1', 'DDR2', 'TXT', 'BKG']
BUS_ROW_COLUMN_BIT = dict(zip(
    BUS_ROW_COLUMNS,
    [0x0800, 0x0400, 0x0200, 0x0100, 0x0080, 0x0040, 0x0020, 0x0010, 0x0008, 0x0004, 0x0002],
))
BUS_ROW_BASELINE = 0x0FFF

# ── dials: telemetry group -> name, click code -> name ──────────────
DIAL_TELEMETRY_GROUP_TO_NAME = {'8': 'SPEED', '9': 'FX', '5': 'DDR1_DIAL', '6': 'DDR2_DIAL', '7': 'TXT_DIAL'}
DIAL_CLICK_BITS = {'SPEED': 0x80, 'FX': 0x40, 'DDR1_DIAL': 0x20, 'DDR2_DIAL': 0x10, 'TXT_DIAL': 0x08}
DIAL_CLICK_BASELINE = 0xFF

# ── joysticks: telemetry group -> name ───────────────────────────────
JOYSTICK_TELEMETRY_GROUP_TO_NAME = {'5': 'JOYSTICK_A', '7': 'JOYSTICK_B'}

# ── '^F' group: FADE / FX_BUTTON (LED) + joystick clicks (no LED) ───
GROUP_CARET_F_BITS     = {'FADE': 0x80, 'FX_BUTTON': 0x40, 'JOYSTICK_A': 0x10, 'JOYSTICK_B': 0x04}
GROUP_CARET_F_LED_BITS = {'FADE': 0x80, 'FX_BUTTON': 0x40}
GROUP_CARET_F_BASELINE = 0xF7   # not all-ones -- confirmed empirically

# ── '^1' group: overlay/transition buttons, all LED ──────────────────
GROUP_CARET_1_BITS = {
    'FTB': 0x80, 'ALT': 0x40, 'EXT_OVERLAY': 0x20,
    'DDR1_OVERLAY': 0x10, 'DDR2_OVERLAY': 0x08, 'TXT_OVERLAY': 0x04,
}
GROUP_CARET_1_BASELINE = 0xFF

# ── '~3' group: action buttons + T-bar endpoint LEDs ──────────────────
GROUP_TILDE_3_READ_BITS = {
    'TAKE': 0x08, 'AUTO': 0x02,
    'FADE_ALL': 0x20, 'TAKE_ALL': 0x10,
    'FADE_OVERLAY': 0x80, 'TAKE_OVERLAY': 0x40,
}
GROUP_TILDE_3_LED_BITS = {
    'FADE_ALL': 0x20, 'TAKE_ALL': 0x10,
    'FADE_OVERLAY': 0x80, 'TAKE_OVERLAY': 0x40,
    'TBAR_LED_TOP': 0x01, 'TBAR_LED_BOTTOM': 0x04,
}
GROUP_TILDE_3_BASELINE = 0xFF

NO_LED_CONTROLS = {
    'AUTO', 'TAKE',
    'SPEED', 'FX', 'DDR1_DIAL', 'DDR2_DIAL', 'TXT_DIAL',
    'JOYSTICK_A', 'JOYSTICK_B',
}


def _build_controls() -> dict[str, Control]:
    controls: dict[str, Control] = {}

    for row in BUS_ROW_PREFIX_TO_ROW.values():
        for col in BUS_ROW_COLUMNS:
            name = f'{row}_{col}'
            controls[name] = Control(name=name, emits=Emits.BUTTON, has_led=True)

    for name in DIAL_TELEMETRY_GROUP_TO_NAME.values():
        controls[name] = Control(name=name, emits=Emits.DIAL | Emits.BUTTON, has_led=False)

    for name in JOYSTICK_TELEMETRY_GROUP_TO_NAME.values():
        controls[name] = Control(name=name, emits=Emits.JOYSTICK | Emits.BUTTON, has_led=False)

    for name in ('FADE', 'FX_BUTTON'):
        controls[name] = Control(name=name, emits=Emits.BUTTON, has_led=True)

    for name in GROUP_CARET_1_BITS:
        controls[name] = Control(name=name, emits=Emits.BUTTON, has_led=True)

    for name in ('FADE_ALL', 'TAKE_ALL', 'FADE_OVERLAY', 'TAKE_OVERLAY'):
        controls[name] = Control(name=name, emits=Emits.BUTTON, has_led=True)
    for name in ('TAKE', 'AUTO'):
        controls[name] = Control(name=name, emits=Emits.BUTTON, has_led=False)

    controls['TBAR'] = Control(name='TBAR', emits=Emits.TBAR, has_led=False)
    controls['TBAR_LED_TOP'] = Control(
        name='TBAR_LED_TOP', emits=Emits.NONE, has_led=True, aliases=('top', 'max'),
    )
    controls['TBAR_LED_BOTTOM'] = Control(
        name='TBAR_LED_BOTTOM', emits=Emits.NONE, has_led=True, aliases=('bottom', 'min'),
    )

    return controls


class LC11Surface(ControlSurface):
    """
    ControlSurfaces driver for the NewTek LiveControl LC-11.

        with LC11Surface('/dev/ttyUSB0', auto_leds=True) as surface:
            surface.run()

        with LC11Surface('/dev/ttyUSB0') as surface:
            surface.set('LIVE_1')
            surface.set(['EFFECTS_TXT', 'PREVIEW_BKG'])
            surface.set_only('LIVE_DDR1')
            surface.clear('LIVE_1')

            @surface.on_button
            def _(event):
                print(event.control, event.held)

            @surface.on_dial
            def _(event):
                print(event.control, event.value)

            surface.run()
    """

    # If the T-bar's physical top/bottom come out swapped on your unit
    # (see ControlSurface.TBAR_INVERTED in surface.py for the 10-second
    # test to check), flip this one line -- position, at_top/at_bottom,
    # and the auto_leds TBAR_LED_TOP/BOTTOM behaviour all follow it.
    TBAR_INVERTED = False

    def __init__(
        self,
        port:       str,
        baud:       int  = BAUD,
        auto_leds:  bool = False,
        threadsafe: bool = False,
    ) -> None:
        super().__init__(port, baud, _build_controls(), threadsafe=threadsafe)

        self._ser: serial.Serial | None = None
        self._buffer = ""

        # ── LED banks ─────────────────────────────────────────────
        self._bus_row_banks = {
            row: LEDBank(
                lambda v, p=prefix: self._send(f'~{p}{v:03X}'),
                BUS_ROW_COLUMN_BIT,
                baseline=BUS_ROW_BASELINE,
            )
            for row, prefix in BUS_ROW_ROW_TO_PREFIX.items()
        }
        self._caret_f_bank = LEDBank(
            lambda v: self._send(f'^F{v:02X}'), GROUP_CARET_F_LED_BITS, baseline=GROUP_CARET_F_BASELINE,
        )
        self._caret_1_bank = LEDBank(
            lambda v: self._send(f'^1{v:02X}'), GROUP_CARET_1_BITS, baseline=GROUP_CARET_1_BASELINE,
        )
        self._tilde_3_bank = LEDBank(
            lambda v: self._send(f'~3{v:02X}'), GROUP_TILDE_3_LED_BITS, baseline=GROUP_TILDE_3_BASELINE,
        )

        self._bank_for: dict[str, tuple[LEDBank, str]] = {}
        for row, bank in self._bus_row_banks.items():
            for col in BUS_ROW_COLUMNS:
                self._bank_for[f'{row}_{col}'] = (bank, col)
        for name in GROUP_CARET_F_LED_BITS:
            self._bank_for[name] = (self._caret_f_bank, name)
        for name in GROUP_CARET_1_BITS:
            self._bank_for[name] = (self._caret_1_bank, name)
        for name in GROUP_TILDE_3_LED_BITS:
            self._bank_for[name] = (self._tilde_3_bank, name)

        # ── input-side delta tracking ────────────────────────────
        self._prev_bus_row: dict[str, set[str]] = {row: set() for row in BUS_ROW_PREFIX_TO_ROW.values()}
        self._prev_group: dict[str, set[str]] = {'^2': set(), '^F': set(), '^1': set(), '~3': set()}

        # ── auto LED plug-in ─────────────────────────────────────
        self.auto_leds = None
        if auto_leds:
            self.auto_leds = AutoLEDs()
            self.auto_leds.attach(self)

    # ═══════════════════════════════════════════════════════════════
    #  Connection
    # ═══════════════════════════════════════════════════════════════

    def _open(self) -> None:
        self._ser = serial.Serial(
            port=self.port, baudrate=self.baud, bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE, timeout=0.01,
        )
        self._ser.write(WAKE_SEQUENCE)
        time.sleep(0.1)
        self._ser.reset_input_buffer()
        self._buffer = ""

    def _close(self) -> None:
        if self._ser and self._ser.is_open:
            self._ser.close()
        self._ser = None

    # ═══════════════════════════════════════════════════════════════
    #  Framing
    # ═══════════════════════════════════════════════════════════════

    def _send(self, payload: str) -> None:
        self._ser.write((payload + '\r').encode('ascii'))

    def _read_messages(self) -> list[str]:
        """
        Read raw bytes and split on \\r, reassembling the LC-11's
        split bus-row frames ("~FXX" + its final hex digit as a
        separate \\r-terminated write) before returning complete
        messages.
        """
        if self._ser and self._ser.in_waiting:
            self._buffer += self._ser.read(self._ser.in_waiting).decode('ascii', errors='ignore')

        messages: list[str] = []
        while '\r' in self._buffer:
            idx     = self._buffer.index('\r')
            message = self._buffer[:idx].strip()
            rest    = self._buffer[idx + 1:]

            if not message:
                self._buffer = rest
                continue

            if len(message) == 4 and message[0] == '~' and message[1] in ('F', '2', '1'):
                if '\r' not in rest:
                    break   # final digit hasn't arrived yet -- wait for more bytes
                idx2  = rest.index('\r')
                extra = rest[:idx2].strip()
                self._buffer = rest[idx2 + 1:]
                message = message + extra
            else:
                self._buffer = rest

            messages.append(message)

        return messages

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
        for message in self._read_messages():
            self._dispatch(message)

    def _dispatch(self, message: str) -> None:
        prefix = message[0]
        group  = message[1]
        payload = message[2:]

        # ── bus rows ───────────────────────────────────────────────
        if prefix == '~' and group in BUS_ROW_PREFIX_TO_ROW:
            self._decode_bus_row(BUS_ROW_PREFIX_TO_ROW[group], payload)

        # ── dial telemetry ────────────────────────────────────────
        elif prefix == '~' and group in DIAL_TELEMETRY_GROUP_TO_NAME:
            try:
                value = int(payload, 16)
            except ValueError:
                return
            self._emit_dial(DIAL_TELEMETRY_GROUP_TO_NAME[group], value)

        # ── T-bar ──────────────────────────────────────────────────
        elif prefix == '~' and group == '4':
            try:
                value = int(payload, 16)
            except ValueError:
                return
            self._emit_tbar(value)

        # ── action group (TAKE/AUTO/FADE_ALL/TAKE_ALL/overlay fade-take) ──
        elif prefix == '~' and group == '3':
            self._decode_group('~3', payload, GROUP_TILDE_3_READ_BITS, GROUP_TILDE_3_BASELINE)

        # ── joystick telemetry ────────────────────────────────────
        elif prefix == '^' and group in JOYSTICK_TELEMETRY_GROUP_TO_NAME:
            self._emit_joystick(JOYSTICK_TELEMETRY_GROUP_TO_NAME[group], payload)

        # ── dial click ─────────────────────────────────────────────
        elif prefix == '^' and group == '2':
            self._decode_group('^2', payload, DIAL_CLICK_BITS, DIAL_CLICK_BASELINE)

        # ── FADE / FX_BUTTON / joystick clicks ────────────────────
        elif prefix == '^' and group == 'F':
            self._decode_group('^F', payload, GROUP_CARET_F_BITS, GROUP_CARET_F_BASELINE)

        # ── FTB / ALT / overlay buttons ───────────────────────────
        elif prefix == '^' and group == '1':
            self._decode_group('^1', payload, GROUP_CARET_1_BITS, GROUP_CARET_1_BASELINE)

        # else: unrecognised frame -- silently ignored, matching the
        # original driver's UNPARSED_DIAGNOSTIC handling (nothing to
        # emit for a message we can't map to a known control).

    def _decode_bus_row(self, row: str, payload: str) -> None:
        try:
            word = int(payload, 16)
        except ValueError:
            return

        now: set[str] = set()
        for col, bit in BUS_ROW_COLUMN_BIT.items():
            if not (word & bit):
                now.add(col)

        prev = self._prev_bus_row[row]
        for col in sorted(now - prev):
            self._emit_button(f'{row}_{col}', True)
        for col in sorted(prev - now):
            self._emit_button(f'{row}_{col}', False)
        self._prev_bus_row[row] = now

    def _decode_group(self, key: str, payload: str, bits: dict[str, int], baseline: int) -> None:
        try:
            val = int(payload, 16)
        except ValueError:
            return

        now: set[str] = set()
        for name, bit in bits.items():
            if not (val & bit) and (baseline & bit):
                now.add(name)

        prev = self._prev_group[key]
        for name in sorted(now - prev):
            self._emit_button(name, True)
        for name in sorted(prev - now):
            self._emit_button(name, False)
        self._prev_group[key] = now
