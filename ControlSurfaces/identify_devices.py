"""
identify_devices.py — figure out your two panels' real USB identity

Neither TriCasterVM nor the LC-11's source material records an actual
USB vendor/product ID -- both are just addressed as a bare serial port.
This script fills that gap: run it against your actual hardware and it
tells you what to put in control_surfaces/detect.py's KNOWN_USB_IDS /
KNOWN_DESCRIPTION_KEYWORDS tables, after which auto-detection becomes
instant (no port I/O) instead of falling back to a live protocol probe.

Usage
-----
    # 1. List every serial port the OS currently sees, with whatever
    #    VID/PID/description metadata is available. Easiest done with
    #    ONE panel connected at a time so it's obvious which line is
    #    which device.
    python identify_devices.py

    # 2. If a port's metadata is generic (e.g. a plain "USB-Serial
    #    Controller" that doesn't name either panel), confirm which
    #    protocol is actually on that port by opening it and listening.
    #    Press a ROW/SOURCE button (a LIVE/NEXT column on the TriCaster,
    #    or an EFFECTS/LIVE/PREVIEW column on the LC-11) while this runs
    #    -- see the note on row buttons below.
    python identify_devices.py --probe /dev/ttyUSB0
    python identify_devices.py --probe COM5 --seconds 3

Once you know which (vid, pid) or description string belongs to which
device, add it to control_surfaces/detect.py:

    KNOWN_USB_IDS = {
        (0x0403, 0x6001): TRICASTER,   # <- your real values here
        (0x10C4, 0xEA60): LC11,
    }

Why a row button, specifically
-------------------------------
The two protocols aren't just similar-looking -- for several channels
they're byte-identical on the wire. TriCaster's T-bar/dial/misc frames
("~4XX\\r", "~5XX\\r", "~3XX\\r", ...) are the exact same shape as the
LC-11's T-bar/dial/action-group frames, so moving just the T-bar or a
dial can't conclusively prove either device -- it rules out nothing.
The one channel where the two protocols are provably different is a
row/source button: the TriCaster sends it as a single complete frame, while the LC-11's hardware quirk splits it into two
separate writes (a 2-hex-digit frame immediately followed by a lone
trailing hex digit). --probe below only reports a device when it sees
a signal that's unique to it, so an inconclusive result after moving
only a T-bar or dial is expected -- try a row button instead.
"""

import argparse
import sys

from control_surfaces.detect import (
    list_serial_ports, _probe_tricaster, _probe_lc11,
)


def cmd_list() -> None:
    ports = list_serial_ports()
    if not ports:
        print("No serial ports found. Is the device plugged in and its "
              "driver installed?")
        return

    print(f"{len(ports)} serial port(s) found:\n")
    for p in ports:
        vid = f"0x{p.vid:04X}" if p.vid is not None else "?"
        pid = f"0x{p.pid:04X}" if p.pid is not None else "?"
        print(f"  device:       {p.device}")
        print(f"  vid:pid:      {vid}:{pid}")
        print(f"  description:  {p.description!r}")
        print(f"  manufacturer: {p.manufacturer!r}")
        print(f"  product:      {p.product!r}")
        print(f"  serial_number:{p.serial_number!r}")
        print(f"  hwid:         {p.hwid!r}")
        print()

    print("If vid/pid or description clearly identifies a device, add it to")
    print("KNOWN_USB_IDS / KNOWN_DESCRIPTION_KEYWORDS in control_surfaces/detect.py.")
    print("If it's generic (e.g. a bare FTDI/CH340/CP210x description), use")
    print("--probe <port> instead to confirm by protocol shape.")


def cmd_probe(port: str, seconds: float) -> None:
    print(f"Probing {port} for {seconds:.1f}s per protocol.")
    print("Press a ROW/SOURCE button on the panel now (a LIVE/NEXT column on")
    print("the TriCaster, or an EFFECTS/LIVE/PREVIEW column on the LC-11) --")
    print("that's the one channel the two protocols can't both produce.")
    print("(Moving just the T-bar or a dial will likely come back inconclusive")
    print("-- see the module docstring for why.)\n")

    is_tricaster = _probe_tricaster(port, seconds)
    is_lc11      = _probe_lc11(port, seconds)

    if is_tricaster and not is_lc11:
        print(f"  {port} looks like: TriCaster VM  (115200 baud, 0x7E-framed)")
    elif is_lc11 and not is_tricaster:
        print(f"  {port} looks like: LC-11  (9600 baud, ~/^ ASCII frames)")
    elif is_tricaster and is_lc11:
        print(f"  {port} matched BOTH shapes -- unexpected, double-check by hand.")
    else:
        print(f"  {port}: no bytes matched either protocol's shape in the window.")
        print("  Try again and make sure to move a control while it's listening,")
        print("  or increase --seconds.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--probe', metavar='PORT',
                     help='Open this port and identify it by protocol shape '
                          '(requires touching a control on the panel during the window).')
    ap.add_argument('--seconds', type=float, default=1.5,
                     help='How long to listen during --probe (default: 1.5s).')
    args = ap.parse_args()

    if args.probe:
        cmd_probe(args.probe, args.seconds)
    else:
        cmd_list()


if __name__ == '__main__':
    sys.exit(main())
