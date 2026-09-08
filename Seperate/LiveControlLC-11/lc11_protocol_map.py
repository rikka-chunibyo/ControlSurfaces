"""
NewTek LiveControl LC-11 — full reverse-engineered protocol map.

This is the SOURCE OF TRUTH for every input we've decoded so far.
Nothing here is organized by "how the hardware groups things" beyond what's
strictly required to disambiguate wire codes (prefix char + group id).
Every entry maps straight to one human label. LEDs (outputs) are not yet
mapped — see the bottom of this file.

Wire format recap
------------------
- ASCII, \\r-delimited frames, 9600 8N1.
- Wake-up: 0x43 0x00 0x00 0x00
- A frame's first character is the PREFIX ('~' or '^').
- The next character is the GROUP ID within that prefix (a single hex/ascii
  digit). Group id values are NOT unique across prefixes — e.g. '~1xxx' is
  the PREVIEW bus row while '^1xx' is the transition/overlay button group.
  They only mean the same thing as each other by coincidence of the digit;
  treat (prefix, group_id) as one combined key, never the group id alone.
- Continuous/telemetry frames report a live value (dial position, joystick
  position, T-bar position).
- Click/discrete frames report a bitmask byte where a press means one bit
  CLEARED from the group's "all released" baseline byte.
"""

# ─────────────────────────────────────────────────────────────────────────
# BUS ROWS  (EFFECTS / LIVE / PREVIEW) — prefix '~', group id = row nibble
# ─────────────────────────────────────────────────────────────────────────
# Frame shape: '~' + row_nibble + 3 hex digits (12-bit inverted button mask)
# Row nibble: F = EFFECTS, 2 = LIVE, 1 = PREVIEW
# Full "all released" payload per row: FFF (EFFECTS), 2FFF, 1FFF
#
# NOTE: the 11 columns are IDENTICAL across all three rows. Each row is its
# own fully independent set of 11 controls — a press of column 7 on EFFECTS
# has nothing to do with column 7 on LIVE or PREVIEW. We keep the row as
# part of the label ONLY because these three rows are the one place on this
# device where "same column across repeated rows" is a real, meaningful
# relationship (unlike the coincidental digit reuse elsewhere).

BUS_ROW_PREFIX_TO_ROW = {
    "F": "EFFECTS",
    "2": "LIVE",
    "1": "PREVIEW",
}

BUS_ROW_COLUMN_BIT_TO_LABEL = {
    0x0800: "1",
    0x0400: "2",
    0x0200: "3",
    0x0100: "4",
    0x0080: "5",
    0x0040: "6",
    0x0020: "EXT",
    0x0010: "DDR1",
    0x0008: "DDR2",
    0x0004: "TXT",
    0x0002: "BKG",
}

# Fully expanded: (row, column_label) -> control name, for anyone who wants
# a flat individually-addressable name instead of a (row, column) tuple.
BUS_ROW_CONTROLS = {
    f"{row}_{col}": (row, col)
    for row in BUS_ROW_PREFIX_TO_ROW.values()
    for col in BUS_ROW_COLUMN_BIT_TO_LABEL.values()
}
# e.g. BUS_ROW_CONTROLS["PREVIEW_TXT"] == ("PREVIEW", "TXT")
#      (physically missing its spring right now, per hardware notes — code
#      doesn't need to know that, it'll just never fire until fixed)


# ─────────────────────────────────────────────────────────────────────────
# DIALS — telemetry, prefix '~', group ids 8/9/5/6/7 (continuous position)
# ─────────────────────────────────────────────────────────────────────────
DIAL_TELEMETRY_GROUP_TO_LABEL = {
    "8": "SPEED",       # transition group knob
    "9": "FX",          # transition group knob
    "5": "DDR1_DIAL",   # overlay group knob
    "6": "DDR2_DIAL",   # overlay group knob
    "7": "TXT_DIAL",    # overlay group knob
}

# ─────────────────────────────────────────────────────────────────────────
# DIALS — click, prefix '^', group id '2'. Baseline (released) = FF
# ─────────────────────────────────────────────────────────────────────────
DIAL_CLICK_CODE_TO_LABEL = {
    "7F": "SPEED",
    "BF": "FX",
    "DF": "DDR1_DIAL",
    "EF": "DDR2_DIAL",
    "F7": "TXT_DIAL",
}

# ─────────────────────────────────────────────────────────────────────────
# JOYSTICKS — telemetry, prefix '^', group ids 5 (A) / 7 (B)
# ─────────────────────────────────────────────────────────────────────────
JOYSTICK_TELEMETRY_GROUP_TO_LABEL = {
    "5": "JOYSTICK_A",
    "7": "JOYSTICK_B",
}

# ─────────────────────────────────────────────────────────────────────────
# JOYSTICKS + TRANSITION FADE/FX — click, prefix '^', group id 'F'.
# Baseline (released) = F7
# NOTE: joystick clicks and the two transition FADE/FX buttons happen to
# share this one wire group. Purely coincidental — kept flat below.
# ─────────────────────────────────────────────────────────────────────────
GROUP_CARET_F_CODE_TO_LABEL = {
    "77": "FADE",         # transition group button
    "B7": "FX_BUTTON",    # transition group button (distinct from FX dial)
    "E7": "JOYSTICK_A",   # joystick A click
    "F3": "JOYSTICK_B",   # joystick B click
}

# ─────────────────────────────────────────────────────────────────────────
# TRANSITION / OVERLAY BUTTON GROUP — prefix '^', group id '1'.
# Baseline (released) = FF
# ─────────────────────────────────────────────────────────────────────────
GROUP_CARET_1_CODE_TO_LABEL = {
    "7F": "FTB",
    "BF": "ALT",
    "DF": "EXT_OVERLAY",
    "EF": "DDR1_OVERLAY",
    "F7": "DDR2_OVERLAY",
    "FB": "TXT_OVERLAY",
}

# ─────────────────────────────────────────────────────────────────────────
# T-BAR — telemetry, prefix '~', group id '4'
# ─────────────────────────────────────────────────────────────────────────
# Frame: '~4' + hex position (0-255). No label table needed, single control.
TBAR_LABEL = "TBAR"

# ─────────────────────────────────────────────────────────────────────────
# ACTION / FADE-ALL / TAKE-ALL GROUP — prefix '~', group id '3'.
# Baseline (released) = FF
# ─────────────────────────────────────────────────────────────────────────
GROUP_TILDE_3_CODE_TO_LABEL = {
    "F7": "TAKE",
    "FD": "AUTO",
    "DF": "FADE_ALL",
    "EF": "TAKE_ALL",
    "7F": "FADE_OVERLAY",
    "BF": "TAKE_OVERLAY",
}

# ─────────────────────────────────────────────────────────────────────────
# FLAT MASTER LIST — every individually addressable input control, by name.
# This is the shape the new ControlSurfaces lib should expose: no groups,
# no hierarchy, just names. Bus row controls keep their row prefix since
# that's a real repeated-3x relationship; everything else is one flat name.
# ─────────────────────────────────────────────────────────────────────────
ALL_INPUT_LABELS = sorted(set(
    list(BUS_ROW_CONTROLS.keys()) + [
        "SPEED", "FX", "DDR1_DIAL", "DDR2_DIAL", "TXT_DIAL",
        "JOYSTICK_A", "JOYSTICK_B",
        "FADE", "FX_BUTTON", "FTB", "ALT",
        "EXT_OVERLAY", "DDR1_OVERLAY", "DDR2_OVERLAY", "TXT_OVERLAY",
        "TAKE", "AUTO", "FADE_ALL", "TAKE_ALL",
        "FADE_OVERLAY", "TAKE_OVERLAY",
        "TBAR",
    ]
))

# ─────────────────────────────────────────────────────────────────────────
# LEDs / OUTPUTS — NOT YET MAPPED.
# Hardest part on TriCasterVM too. Every physical light on this panel
# (all 33 bus-row buttons x their live/lit states, FTB/Alt, overlay row
# buttons, etc.) still needs its write-side protocol captured empirically
# via led_probe.py, the same trial-and-error approach that worked (eventually)
# for TriCasterVM.
#
# Controls confirmed to have NO LED on TriCasterVM, expected to hold here
# too (momentary action buttons, not state indicators) -- excluded from the
# probe list so we don't burn cycles on them:
NO_LED_CONTROLS = {"AUTO", "TAKE"}  # confirmed no LED response, matches TriCaster

# CONFIRMED (2026-07-28, via bitbang_scan.py --group busrow): write format
# mirrors the read format exactly. To light column `col` on row `row`,
# send '~' + row_prefix + hex(12-bit word with only that column's bit
# cleared, 3 hex digits) + '\r'. Baseline ('~{prefix}FFF') = all off for
# that row. This is now considered SOLVED for all 33 bus-row buttons.
LED_MAP = {
    f"{row}_{col}": True  # True = confirmed working, mirrors BUS_ROW_COLUMN_BIT_TO_LABEL
    for row in BUS_ROW_PREFIX_TO_ROW.values()
    for col in BUS_ROW_COLUMN_BIT_TO_LABEL.values()
}

# CONFIRMED (round 2, mirrored write code = read click code):
for _confirmed in (
    "FADE_ALL", "TAKE_ALL", "FADE_OVERLAY", "TAKE_OVERLAY",
    "ALT", "EXT_OVERLAY", "DDR1_OVERLAY", "DDR2_OVERLAY", "TXT_OVERLAY",
    "FX_BUTTON",
    # CONFIRMED (round 3, via full 0x00-0xFF sweep): both are also mirrored
    # write codes (^17F / ^F77) -- the initial single-frame test looked like
    # "no LED" only because it was the very first write after the wake-up
    # sequence and got dropped by the device before it settled. Full sweep
    # showed a clean bit-0x80 toggle boundary at 0x7F/0x80, matching the
    # exact same single-bit-at-baseline model as every other button here.
    "FTB", "FADE",
):
    LED_MAP[_confirmed] = True
del _confirmed

# CONFIRMED (round 4, via bitbang_scan.py --group tbar_led_bits): the T-bar
# has exactly 2 LEDs (top/bottom), NOT a segment display. Both live as
# individual bits within the SAME shared byte as FADE_ALL/TAKE_ALL/
# FADE_OVERLAY/TAKE_OVERLAY (the '~3' group) -- confirmed isolated via a
# targeted 3-bit sub-sweep that held all known bits at baseline throughout.
#   TBAR_LED_TOP    -> bit 0x01  (write '~3FE' to light, alone)
#   TBAR_LED_BOTTOM -> bit 0x04  (write '~3FB' to light, alone)
#   bit 0x02 confirmed dead for LEDs -- it's the read-side click code for
#   AUTO, which (like TAKE) has no LED. Aliased address, no visible effect.
#
# IMPORTANT for the future driver: because these 8 controls (6 known
# buttons + 2 T-bar LEDs, with bit 0x02 unused) all share ONE write byte,
# you cannot address any of them with an isolated frame the way bus-row
# buttons work -- writing '~3FE' to light TBAR_LED_TOP will also clear
# (turn OFF) any of the other 5 LEDs in this byte that were previously on.
# The driver needs to track this byte's current state and flip one bit at
# a time, OR-ing/AND-ing against the last known value, not just replaying
# single-purpose frames like we did during discovery.
LED_MAP["TBAR_LED_TOP"] = True
LED_MAP["TBAR_LED_BOTTOM"] = True

# Still unmapped: SPEED/FX/DDR1_DIAL/DDR2_DIAL/TXT_DIAL knob rings and
# JOYSTICK_A/B -- confirmed by inspection to have no LEDs, not tested via
# probe (per hardware, these controls simply don't light up).
CONFIRMED_NO_LED_BY_INSPECTION = {
    "SPEED", "FX", "DDR1_DIAL", "DDR2_DIAL", "TXT_DIAL",
    "JOYSTICK_A", "JOYSTICK_B",
}
NO_LED_CONTROLS |= CONFIRMED_NO_LED_BY_INSPECTION

# ─────────────────────────────────────────────────────────────────────────
# LED discovery is now COMPLETE. Every control on the panel is accounted
# for: it either has a confirmed LED write code (LED_MAP), is confirmed to
# have no LED (NO_LED_CONTROLS), or -- for TBAR_LED_TOP/BOTTOM -- exists
# only as an output with no corresponding input control.
# ─────────────────────────────────────────────────────────────────────────