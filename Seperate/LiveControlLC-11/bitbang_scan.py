"""
LC-11 LED bit-bang scanner.

Two modes:

  FAST (default) - streams every candidate write frame with minimal delay.
  Watch the panel while it runs. When you see *something* flicker/light,
  note the approx time or the last index printed just before/after it,
  then re-run in SLOW mode over that narrow window to pin down the exact
  frame.

  SLOW - replays a specific index range with a real pause between each
  candidate (and prints it before sending, so you can watch->confirm->
  advance). Use this to zero in once fast mode gives you a rough location.

Every run appends to bitbang_log.jsonl (index, elapsed time, hex sent,
our best-guess label for what we were testing) so you always have a
written record to cross-reference against what you saw, even if you
weren't fast enough to write it down live.

Usage
-----
    # Fast sweep of everything:
    python bitbang_scan.py

    # Fast sweep, only the bus-row candidates:
    python bitbang_scan.py --group busrow

    # Fast sweep, only the T-bar sweep:
    python bitbang_scan.py --group tbar

    # Narrow window, slow, once you've spotted roughly where:
    python bitbang_scan.py --start 40 --end 55 --slow --delay 1.5

    # List candidates without sending anything (sanity check the plan):
    python bitbang_scan.py --dry-run
"""

import argparse
import json
import os
import time
import serial

DEFAULT_PORT = "COM5" if os.name == "nt" else "/dev/ttyUSB0"
LOG_PATH = "bitbang_log.jsonl"


# ─────────────────────────────────────────────────────────────────────────
# Candidate generation
# ─────────────────────────────────────────────────────────────────────────
# We mirror the READ-side frame shapes back at the device as WRITE
# candidates, since that's the pattern that worked for TriCaster's simple
# buttons. Each candidate is (label, raw_bytes_without_terminator).

BUS_ROW_PREFIX = {"EFFECTS": "F", "LIVE": "2", "PREVIEW": "1"}
BUS_ROW_COLUMN_BIT = {
    "1": 0x0800, "2": 0x0400, "3": 0x0200, "4": 0x0100,
    "5": 0x0080, "6": 0x0040, "EXT": 0x0020, "DDR1": 0x0010,
    "DDR2": 0x0008, "TXT": 0x0004, "BKG": 0x0002,
}

GROUP_TILDE_3 = {
    "TAKE": "F7", "AUTO": "FD", "FADE_ALL": "DF", "TAKE_ALL": "EF",
    "FADE_OVERLAY": "7F", "TAKE_OVERLAY": "BF",
}

GROUP_CARET_1 = {
    "FTB": "7F", "ALT": "BF", "EXT_OVERLAY": "DF",
    "DDR1_OVERLAY": "EF", "DDR2_OVERLAY": "F7", "TXT_OVERLAY": "FB",
}

GROUP_CARET_F = {
    "FADE": "77", "FX_BUTTON": "B7",
}


def gen_busrow_candidates():
    out = []
    for row, prefix in BUS_ROW_PREFIX.items():
        # baseline "all released" state for this row
        out.append((f"{row}_BASELINE", f"~{prefix}FFF".encode()))
        # all-on guess (every bit cleared)
        out.append((f"{row}_ALL_ON_GUESS", f"~{prefix}000".encode()))
        # single button lit, mirroring the read-side inverted mask
        for col, bit in BUS_ROW_COLUMN_BIT.items():
            word = (~bit) & 0x0FFF
            out.append((f"{row}_{col}", f"~{prefix}{word:03X}".encode()))
    return out


def gen_tilde3_candidates():
    return [(f"ACTION_{name}", f"~3{code}".encode())
            for name, code in GROUP_TILDE_3.items()]


def gen_caret1_candidates():
    return [(f"BTN_{name}", f"^1{code}".encode())
            for name, code in GROUP_CARET_1.items()]


def gen_caretf_candidates():
    return [(f"BTN_{name}", f"^F{code}".encode())
            for name, code in GROUP_CARET_F.items()]


def gen_tbar_candidates():
    # Sweep the T-bar's read-side position field as a write, coarse first.
    out = []
    for pos in range(0, 256, 16):
        out.append((f"TBAR_POS_{pos}", f"~4{pos:02X}".encode()))
    return out


def gen_raw_sweep_candidates(template, start, end):
    out = []
    for val in range(start, end):
        frame_str = template.format(val)
        out.append((f"SWEEP_{val:02X}", frame_str.encode()))
    return out


def gen_tbar_led_bit_candidates():
    # Every combination of the 3 bits in the ~3 group never claimed by a
    # known button (0x01, 0x02, 0x04), with all known bits (0x08 TAKE,
    # 0x10 TAKE_ALL, 0x20 FADE_ALL, 0x40 TAKE_OVERLAY, 0x80 FADE_OVERLAY)
    # held at baseline (set/off) so those LEDs stay dark and don't muddy
    # the read. 0x02 aliases AUTO on the read side (which has no LED), so
    # it's a real candidate for reuse here on the write side.
    out = []
    for low3 in range(8):  # 0..7, i.e. bits 0x01/0x02/0x04 in all combos
        val = 0xFF & ~low3 & 0xFF  # start at baseline, clear only the selected low bits
        bits_set = []
        if low3 & 0x01: bits_set.append("01")
        if low3 & 0x02: bits_set.append("02")
        if low3 & 0x04: bits_set.append("04")
        label = "TBAR_CLEAR_" + ("_".join(bits_set) if bits_set else "NONE")
        out.append((label, f"~3{val:02X}".encode()))
    return out


GROUPS = {
    "busrow": gen_busrow_candidates,
    "action": gen_tilde3_candidates,
    "overlay_btn": gen_caret1_candidates,
    "transition_btn": gen_caretf_candidates,
    "tbar": gen_tbar_candidates,
    "tbar_led_bits": gen_tbar_led_bit_candidates,
}


def build_candidates(selected_groups, sweep_template=None, sweep_start=0, sweep_end=256):
    candidates = []
    for name in selected_groups:
        candidates.extend(GROUPS[name]())
    if sweep_template:
        candidates.extend(gen_raw_sweep_candidates(sweep_template, sweep_start, sweep_end))
    return candidates


# ─────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", action="append", choices=list(GROUPS.keys()),
                     help="Limit to one or more groups (repeatable). Default: all (unless --sweep-template given, then none).")
    ap.add_argument("--sweep-template", default=None,
                     help="Brute-force a full byte range into a frame template, "
                          "e.g. '^1{:02X}' or '~3{:02X}'. {} is replaced with the byte, "
                          "hex uppercase, 2 digits.")
    ap.add_argument("--sweep-start", type=int, default=0)
    ap.add_argument("--sweep-end", type=int, default=256)
    ap.add_argument("--repeat", type=int, default=1,
                     help="Re-run the whole window this many times in a row "
                          "(re-opens the port fresh each time), to stress-test "
                          "whether a short group's first frame reliably lands.")
    ap.add_argument("--start", type=int, default=0, help="Start index (inclusive)")
    ap.add_argument("--end", type=int, default=None, help="End index (exclusive)")
    ap.add_argument("--slow", action="store_true", help="Pause between each candidate")
    ap.add_argument("--delay", type=float, default=None,
                     help="Seconds between candidates. Default: 0.12 fast, 2.0 slow.")
    ap.add_argument("--dry-run", action="store_true", help="List candidates, send nothing")
    ap.add_argument("--port", default=DEFAULT_PORT,
                     help=f"Serial port (default: {DEFAULT_PORT})")
    ap.add_argument("--reset-after", action="store_true", default=True,
                     help="Send baseline for any bus rows touched, at the end (default: on)")
    ap.add_argument("--no-reset-after", dest="reset_after", action="store_false")
    args = ap.parse_args()

    groups = args.group if args.group else ([] if args.sweep_template else list(GROUPS.keys()))
    candidates = build_candidates(groups, args.sweep_template, args.sweep_start, args.sweep_end)
    end = args.end if args.end is not None else len(candidates)
    window = candidates[args.start:end]

    delay = args.delay
    if delay is None:
        delay = 2.0 if args.slow else 0.12

    print(f"{len(candidates)} total candidates across groups: {groups}")
    print(f"Running indices [{args.start}:{end}) = {len(window)} candidates, delay={delay}s\n")

    if args.dry_run:
        for i, (label, payload) in enumerate(window, start=args.start):
            print(f"  [{i}] {label:30s} {payload!r}")
        return

    log = open(LOG_PATH, "a", buffering=1)

    for run_num in range(1, args.repeat + 1):
        if args.repeat > 1:
            print(f"\n=== RUN {run_num}/{args.repeat} ===")

        print(f"Opening {args.port}...")
        ser = serial.Serial(
            port=args.port, baudrate=9600, bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE, timeout=0.02,
        )
        ser.write(b"\x43\x00\x00\x00")
        time.sleep(0.1)
        ser.reset_input_buffer()
        # Priming write: the device appears to still be settling right after the
        # wake sequence, which silently dropped the very first real candidate in
        # a couple of short group runs (FTB, FADE both looked "no LED" until we
        # full-byte-swept them -- turned out to be a lost first frame, not a
        # missing LED). Send a harmless baseline frame and give it a beat before
        # the real sweep starts.
        ser.write(b"~FFFF\r")
        time.sleep(0.2)

        t0 = time.time()

        try:
            for i, (label, payload) in enumerate(window, start=args.start):
                frame = payload + b"\r"
                if args.slow:
                    input(f"  [{i}] {label:30s} {frame!r}  -- Enter to send, watch panel...")
                ser.write(frame)
                elapsed = time.time() - t0
                print(f"  [{i}] t={elapsed:6.2f}s  {label:30s} {frame!r}")

                log.write(json.dumps({
                    "run": run_num, "index": i, "elapsed_s": round(elapsed, 3),
                    "label": label, "hex": frame.hex(" "),
                }) + "\n")

                time.sleep(delay)
        except KeyboardInterrupt:
            print("\nStopped early.")
            ser.close()
            break
        finally:
            if args.reset_after:
                touched_rows = {label.split("_")[0] for label, _ in window
                                 if label.split("_")[0] in BUS_ROW_PREFIX}
                for row in touched_rows:
                    prefix = BUS_ROW_PREFIX[row]
                    frame = f"~{prefix}FFF".encode() + b"\r"
                    ser.write(frame)
                    print(f"  reset: {row} -> baseline  {frame!r}")
                    time.sleep(0.05)
            ser.close()

        if run_num < args.repeat:
            time.sleep(0.5)  # give the panel/device a moment between fresh port opens

    log.close()
    print("Log saved to", LOG_PATH)


if __name__ == "__main__":
    main()