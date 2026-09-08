import serial
import time

PORT = '/dev/ttyUSB0'
BAUD = 115200

# ═══════════════════════════════════════════════════════════════════
# TRICASTER VM PANEL — COMPLETE CONFIRMED HARDWARE MAP
#
# Serial: 115200 baud, 8N1
# Frame:  ~{ch}{val:02X}\r   (5 bytes: 0x7E  ch_byte  hex×2  0x0D)
#
# ── OUTPUT  (host → panel, LED control) ───────────────────────────
#
#   ch '2'  LIVE row   rest=0xFF   bit(8−n) clear = button n lit
#   ch '1'  NEXT row   rest=0xFF   bit(8−n) clear = button n lit
#
#           Btn  Bit  Label
#            1    7   CAM 1
#            2    6   CAM 2
#            3    5   CAM 3
#            4    4   VGA
#            5    3   VCR
#            6    2   PIC
#            7    1   BKG
#            8    0   BLK
#
#   ch '3'  misc LEDs   rest=0xFF (output)
#           Bit  Label              Note
#            7   FADE OVERLAY
#            6   TAKE OVERLAY
#            5   FADE ALL
#            4   TAKE ALL
#            3   AUTO               ✗  no backlight
#            2   fader-bottom
#            1   TAKE               ✗  no backlight
#            0   fader-top
#
# ── INPUT   (panel → host, events) ───────────────────────────────
#
#   ch '2'  LIVE row   rest=0xFF   bit(8−n) clear = button held
#   ch '1'  NEXT row   rest=0xFF   same layout
#
#   ch '3'  buttons     rest=0xFE  (bit 0 always 0 on input)
#           Bit  Label
#            7   FADE OVERLAY
#            6   TAKE OVERLAY
#            5   FADE ALL
#            4   TAKE ALL
#            3   AUTO
#            2   TAKE      ← first contact
#            1   TAKE      ← second contact (simultaneous with bit 2)
#
#   ch '4'  T-bar position
#           0x00 = physical TOP (max)    → fader-top LED
#           0xFF = physical BOTTOM (min) → fader-bottom LED
#           display %: (255 − raw) / 255 × 100
#
#   ch '5'  Transition Speed dial    (0x01–0x18, ~24 detents)
#   ch '6'  Transition Select dial   (0x01–0x07, 7 positions)
#   ch '7'  Overlay Select dial      (0x01–0x08, 8 positions)
#
# ═══════════════════════════════════════════════════════════════════

# ── row button labels (index 0 = button 1) ───────────────────────
ROW_LABELS = ['CAM 1', 'CAM 2', 'CAM 3', 'VGA', 'VCR', 'PIC', 'BKG', 'BLK']

# ── button n → bitmask for 8-button rows ─────────────────────────
BTN8 = {n: 0xFF ^ (1 << (8 - n)) for n in range(1, 9)}

# ── ch3 LED names → bitmask (OUTPUT only) ────────────────────────
CH3_LEDS = {
    'FADE OVERLAY': 0x80,
    'TAKE OVERLAY': 0x40,
    'FADE ALL':     0x20,
    'TAKE ALL':     0x10,
    # bit 3 = AUTO      — no backlight, omitted
    'fader-bottom': 0x04,
    # bit 1 = TAKE      — no backlight, omitted
    'fader-top':    0x01,
}

# ── ch3 INPUT bit → label (for decoding incoming events) ─────────
CH3_INPUT_BITS = [
    (7, 'FADE OVERLAY'),
    (6, 'TAKE OVERLAY'),
    (5, 'FADE ALL'),
    (4, 'TAKE ALL'),
    (3, 'AUTO'),
    (2, 'TAKE'),   # first contact  \  both labels same so
    (1, 'TAKE'),   # second contact /  dedup collapses them
]

# ── which ch3 INPUT buttons have a matching OUTPUT LED ───────────
CH3_BTN_LED = {
    'FADE OVERLAY': 'FADE OVERLAY',
    'TAKE OVERLAY': 'TAKE OVERLAY',
    'FADE ALL':     'FADE ALL',
    'TAKE ALL':     'TAKE ALL',
    # AUTO → no LED
    # TAKE → no LED
}


# ═══════════════════════════════════════════════════════════════════
#  API
# ═══════════════════════════════════════════════════════════════════

def tx(ser, ch: str, val: int):
    """Send a raw 5-byte frame."""
    ser.write(f"~{ch}{val:02X}\r".encode('ascii'))


def led8(ser, ch: str, buttons_on: list):
    """
    Light specific buttons on LIVE (ch='2') or NEXT (ch='1') row.
    buttons_on: list of button numbers 1–8.  Empty = all off.

        led8(ser, '2', [1])          # LIVE CAM 1 on
        led8(ser, '1', [3, 5])       # NEXT CAM 3 + VCR on
        led8(ser, '2', [])           # all off
    """
    val = 0xFF
    for n in buttons_on:
        val &= BTN8[n]
    tx(ser, ch, val)


def ch3(ser, *names):
    """
    Set ch3 LEDs by name.  No args = all off (sends 0xFF).

        ch3(ser)                                    # all off
        ch3(ser, 'fader-top')                       # T-bar top LED
        ch3(ser, 'fader-top', 'fader-bottom')       # both fader LEDs
        ch3(ser, 'FADE OVERLAY', 'TAKE ALL')        # two mini buttons

    Valid names: 'FADE OVERLAY', 'TAKE OVERLAY', 'FADE ALL', 'TAKE ALL',
                 'fader-bottom', 'fader-top'
    """
    val = 0xFF
    for name in names:
        mask = CH3_LEDS.get(name)
        if mask is None:
            raise ValueError(f"Unknown ch3 LED: {name!r}\nValid: {list(CH3_LEDS)}")
        val &= ~mask
    tx(ser, '3', val)


def all_off(ser):
    """Reset every panel LED to off."""
    led8(ser, '2', [])
    led8(ser, '1', [])
    ch3(ser)


# ── incoming event decoder ────────────────────────────────────────

def decode(ch: str, val: int) -> str:
    if ch in ('1', '2'):
        row = 'LIVE' if ch == '2' else 'NEXT'
        if val == 0xFF:
            return f'{row} — released'
        held = [ROW_LABELS[n - 1] for n in range(1, 9)
                if not (val >> (8 - n) & 1)]
        return f'{row} → {", ".join(held)}'

    if ch == '3':
        if val in (0xFE, 0xFF):
            return 'ch3 — released'
        seen = []
        for bit, label in CH3_INPUT_BITS:
            if not (val & (1 << bit)) and label not in seen:
                seen.append(label)
        return f'ch3 → {", ".join(seen)}'

    if ch == '4':
        if val == 0x00:
            return 'T-bar — TOP (100%)'
        if val == 0xFF:
            return 'T-bar — BOTTOM (0%)'
        pct = round((255 - val) / 255 * 100, 1)
        return f'T-bar {pct}%'

    if ch == '5':
        return f'Transition Speed  pos={val}'
    if ch == '6':
        return f'Transition Select  pos={val}'
    if ch == '7':
        return f'Overlay Select  pos={val}'

    return f'ch{ch} 0x{val:02X}'


def drain(ser):
    """Read all pending bytes and return list of (ch, val) pairs."""
    if not ser.in_waiting:
        return []
    raw = ser.read(ser.in_waiting)
    msgs = []
    i = 0
    while i <= len(raw) - 5:
        if raw[i] == 0x7E and raw[i + 4] == 0x0D:
            try:
                ch  = chr(raw[i + 1])
                val = int(chr(raw[i + 2]) + chr(raw[i + 3]), 16)
                msgs.append((ch, val))
            except (ValueError, UnicodeDecodeError):
                pass
            i += 5
        else:
            i += 1
    return msgs


# ═══════════════════════════════════════════════════════════════════
#  CONNECT
# ═══════════════════════════════════════════════════════════════════

try:
    ser = serial.Serial(PORT, BAUD, timeout=0.1)
    print(f'Connected on {PORT}  ({BAUD} baud)\n')
except Exception as e:
    print(f'Error: {e}'); exit()

all_off(ser)
time.sleep(0.4)


# ═══════════════════════════════════════════════════════════════════
#  DEMO SEQUENCE  — exercises every confirmed LED
# ═══════════════════════════════════════════════════════════════════

def pause(t=0.10):
    time.sleep(t)

print('── LIVE row  (CAM1 → BLK) ───────────────────────────')
for n in range(1, 9):
    led8(ser, '2', [n]); pause()
led8(ser, '2', list(range(1, 9))); pause(0.35)
led8(ser, '2', []); pause(0.2)

print('── NEXT row  (CAM1 → BLK) ───────────────────────────')
for n in range(1, 9):
    led8(ser, '1', [n]); pause()
led8(ser, '1', list(range(1, 9))); pause(0.35)
led8(ser, '1', []); pause(0.2)

print('── Mini row  (FADE OVR → TAKE ALL) ──────────────────')
for name in ['FADE OVERLAY', 'TAKE OVERLAY', 'FADE ALL', 'TAKE ALL']:
    ch3(ser, name); pause(0.15)
ch3(ser, 'FADE OVERLAY', 'TAKE OVERLAY', 'FADE ALL', 'TAKE ALL')
pause(0.4); ch3(ser); pause(0.2)

print('── Fader LEDs ────────────────────────────────────────')
ch3(ser, 'fader-top');                         pause(0.4)
ch3(ser, 'fader-bottom');                      pause(0.4)
ch3(ser, 'fader-top', 'fader-bottom');         pause(0.4)
ch3(ser);                                      pause(0.2)

print('── All LEDs ──────────────────────────────────────────')
led8(ser, '2', list(range(1, 9)))
led8(ser, '1', list(range(1, 9)))
ch3(ser, 'FADE OVERLAY', 'TAKE OVERLAY', 'FADE ALL', 'TAKE ALL',
         'fader-top', 'fader-bottom')
pause(0.8); all_off(ser); pause(0.2)

print('Done.\n')


# ═══════════════════════════════════════════════════════════════════
#  INTERACTIVE MONITOR
#  Buttons light while held.  T-bar endpoint LEDs track position.
# ═══════════════════════════════════════════════════════════════════

print('Interactive  (Ctrl-C to quit)')
print('  Hold any button → LED lights while pressed')
print('  T-bar to top → fader-top LED,  bottom → fader-bottom LED\n')
print(f"  {'CH':<3} {'HEX':>4}  Event")
print('  ' + '─' * 46)

prev       = {}
mini_leds  = set()   # mini-row LEDs lit by held buttons
fader_leds = set()   # fader-top / fader-bottom lit by T-bar position

def push_ch3():
    ch3(ser, *(mini_leds | fader_leds))

try:
    while True:
        for ch, val in drain(ser):
            if prev.get(ch) == val:
                continue
            prev[ch] = val
            print(f"  {ch}   0x{val:02X}  {decode(ch, val)}")

            if ch == '2':
                if val == 0xFF:
                    led8(ser, '2', [])
                else:
                    held = [n for n in range(1, 9) if not (val >> (8 - n) & 1)]
                    led8(ser, '2', held)

            elif ch == '1':
                if val == 0xFF:
                    led8(ser, '1', [])
                else:
                    held = [n for n in range(1, 9) if not (val >> (8 - n) & 1)]
                    led8(ser, '1', held)

            elif ch == '3':
                mini_leds.clear()
                if val not in (0xFE, 0xFF):
                    for bit, label in CH3_INPUT_BITS:
                        if not (val & (1 << bit)):
                            led = CH3_BTN_LED.get(label)
                            if led:
                                mini_leds.add(led)
                push_ch3()

            elif ch == '4':
                fader_leds.clear()
                if val == 0x00:
                    fader_leds.add('fader-top')
                elif val == 0xFF:
                    fader_leds.add('fader-bottom')
                push_ch3()

        time.sleep(0.02)

except KeyboardInterrupt:
    all_off(ser)
    ser.close()
    print('\nDone.')
