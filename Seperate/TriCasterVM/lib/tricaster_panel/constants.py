# ═══════════════════════════════════════════════════════════════════
# tricaster_panel/constants.py
#
# All hardware knowledge lives here.  Nothing else imports raw bytes
# or label strings directly.
#
# Serial: 115200 baud, 8N1
# Frame:  ~{ch}{val:02X}\r  (5 bytes: 0x7E  ch_byte  hex×2  0x0D)
# ═══════════════════════════════════════════════════════════════════

BAUD = 115200

# ── output channels (host → panel, LED control) ──────────────────
CH_LIVE = '2'   # LIVE row  (8 buttons)
CH_NEXT = '1'   # NEXT row  (8 buttons)
CH_MISC = '3'   # mini row buttons + fader LEDs  (shared channel)

# ── input channels (panel → host, events) ────────────────────────
CH_TBAR    = '4'
CH_SPEED   = '5'   # Transition Speed dial
CH_SELECT  = '6'   # Transition Select dial
CH_OVERLAY = '7'   # Overlay Select dial

# ── 8-button rows: button n → bitmask ────────────────────────────
#    rest=0xFF; clearing bit(8-n) lights button n
BTN8 = {n: 0xFF ^ (1 << (8 - n)) for n in range(1, 9)}

# ── LIVE / NEXT row labels (1-indexed) ───────────────────────────
ROW_LABELS = {
    1: 'CAM 1',
    2: 'CAM 2',
    3: 'CAM 3',
    4: 'VGA',
    5: 'VCR',
    6: 'PIC',
    7: 'BKG',
    8: 'BLK',
}
ROW_LABELS_INV = {v: k for k, v in ROW_LABELS.items()}

# ── mini row labels (1-indexed) ──────────────────────────────────
MINI_LABELS = {
    1: 'FADE OVERLAY',
    2: 'TAKE OVERLAY',
    3: 'FADE ALL',
    4: 'TAKE ALL',
}
MINI_LABELS_INV = {v: k for k, v in MINI_LABELS.items()}

# ── mini row: ch3 output bitmasks ────────────────────────────────
MINI_BITS = {
    1: 0x80,   # FADE OVERLAY
    2: 0x40,   # TAKE OVERLAY
    3: 0x20,   # FADE ALL
    4: 0x10,   # TAKE ALL
}

# ── fader labels and aliases ──────────────────────────────────────
FADER_LABELS = {
    1: 'TOP',
    2: 'BOTTOM',
}
FADER_ALIASES = {
    'top':    1,
    'max':    1,
    'bottom': 2,
    'min':    2,
}

# ── fader: ch3 output bitmasks ────────────────────────────────────
FADER_BITS = {
    1: 0x01,   # fader-top
    2: 0x04,   # fader-bottom
}

# ── ch3 input: bit → label (for decoding incoming button events) ──
CH3_INPUT_BITS = [
    (7, 'FADE OVERLAY'),
    (6, 'TAKE OVERLAY'),
    (5, 'FADE ALL'),
    (4, 'TAKE ALL'),
    (3, 'AUTO'),   # no output LED
    (2, 'TAKE'),   # first contact  } both fire together;
    (1, 'TAKE'),   # second contact } dedup collapses them
]

# ── ch3 input label → button number (all ch3 buttons, including no-LED ones)
#    1-4 have output LEDs;  5 (AUTO) and 6 (TAKE) do not.
CH3_BTN_LED = {
    'FADE OVERLAY': 1,
    'TAKE OVERLAY': 2,
    'FADE ALL':     3,
    'TAKE ALL':     4,
    'AUTO':         5,   # no output LED — event only
    'TAKE':         6,   # no output LED — event only
}

# ── button number → label, for event generation ───────────────────
CH3_EVENT_LABELS = {
    1: 'FADE OVERLAY',
    2: 'TAKE OVERLAY',
    3: 'FADE ALL',
    4: 'TAKE ALL',
    5: 'AUTO',
    6: 'TAKE',
}

# ── button number → row name emitted in ButtonEvent ───────────────
#    AUTO and TAKE are physically separate action buttons sharing the
#    ch3 wire; each gets its own row name so callers can filter cleanly.
CH3_EVENT_ROW = {
    1: 'MINI', 2: 'MINI', 3: 'MINI', 4: 'MINI',
    5: 'AUTO',
    6: 'TAKE',
}

# ── dial channel → canonical name ────────────────────────────────
DIAL_NAMES = {
    CH_SPEED:   'TRANSITION_SPEED',
    CH_SELECT:  'TRANSITION_SELECT',
    CH_OVERLAY: 'OVERLAY_SELECT',
}