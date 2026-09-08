# ═══════════════════════════════════════════════════════════════════
# tricaster_panel/protocol.py
#
# Raw serial framing.  No labels, no logic — bytes only.
# Frame format: ~{ch}{val:02X}\r
#   0x7E  ch_byte  hex_hi  hex_lo  0x0D   (5 bytes total)
# ═══════════════════════════════════════════════════════════════════


def send_frame(ser, ch: str, val: int) -> None:
    """Encode and transmit a single 5-byte frame."""
    ser.write(f"~{ch}{val:02X}\r".encode('ascii'))


def read_frames(ser) -> list[tuple[str, int]]:
    """
    Read all bytes currently in the serial buffer and return every
    complete, well-formed frame as a (ch, val) pair.

    Malformed or partial frames are silently skipped; the parser
    advances one byte at a time so a corrupt frame cannot swallow
    the next valid one.
    """
    if not ser.in_waiting:
        return []

    raw = ser.read(ser.in_waiting)
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
