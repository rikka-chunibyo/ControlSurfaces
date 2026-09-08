# ═══════════════════════════════════════════════════════════════════
# control_surfaces/detect.py
#
# Auto-identification of which physical device (TriCaster VM panel or
# LiveControl LC-11) is sitting on a given serial port, so callers
# don't have to pass a device class by hand.
#
# Three signals are tried, cheapest/most-reliable first:
#
#   1. USB vendor/product ID   -- exact (vid, pid) match against
#      KNOWN_USB_IDS. Fast and unambiguous *if* the table has been
#      populated for your hardware (see note below).
#
#   2. USB descriptor strings  -- substring match against each port's
#      description/manufacturer/product text (e.g. a descriptor that
#      contains "TriCaster" or "LiveControl"). Useful when a vendor
#      flashes a custom product string onto an otherwise generic
#      USB-serial chip.
#
#   3. Learned serial-number cache -- both panels sit behind generic
#      FTDI FT232R bridges, so vid:pid is identical for both and can't
#      tell them apart (signal 1 is a no-op here). The USB serial
#      number *is* unique per physical adapter, but it's a property of
#      one specific dongle, not of "TriCaster-ness" or "LC11-ness" --
#      so instead of hand-maintaining a table of serials, this module
#      *learns* the mapping automatically the first time signal 4
#      succeeds for a given serial number, and persists it to disk.
#      From then on, that same adapter is identified instantly with no
#      port I/O, and if it's ever replaced, the new serial simply
#      isn't in the cache yet and falls through to signal 4 again.
#
#   4. Protocol probe          -- open the port, listen briefly, and
#      classify whatever bytes show up by their wire shape. Neither
#      device volunteers data unprompted, so this only succeeds if a
#      control is actively moved while it's listening. It's the
#      fallback of last resort -- but note that whenever it *does*
#      succeed, the result is written into the serial-number cache
#      (signal 3), so a given physical adapter only ever needs to be
#      touched once, not on every reconnect.
#
# ── Why (1) and (2) start out empty ──────────────────────────────────
# Neither TriCasterVM nor the LC-11's source material (raw.py,
# bitbang_scan.py, .gitattributes, etc.) records an actual USB VID/PID
# for either panel -- both are just addressed as a bare serial port
# ('/dev/ttyUSB0', 'COM5'). Plenty of real-world panels like this sit
# behind a generic FTDI/CH340/CP210x USB-serial bridge, which means
# the OS-level VID/PID may not even distinguish the two devices from
# each other (or from unrelated USB-serial gadgets) -- only the
# descriptor *string*, if the vendor bothered to customize it, would.
#
# KNOWN_USB_IDS and KNOWN_DESCRIPTION_KEYWORDS are therefore left as a
# starting point, not a finished lookup table. Run list_serial_ports()
# with each panel connected (one at a time is easiest) to see exactly
# what your OS reports for vid/pid/description/manufacturer/product,
# then add the real values to the tables below. Once populated,
# detection becomes a single fast, non-invasive lookup with no port
# I/O at all -- the protocol probe only ever runs as a fallback.
# ═══════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import serial
from serial.tools import list_ports

if TYPE_CHECKING:
    from .surface import ControlSurface
    from .multi import MultiSurface

TRICASTER = 'tricaster'
LC11      = 'lc11'

# ── signal 3: serial numbers learned from a successful protocol probe,
#    persisted here so each physical adapter only needs to be touched
#    once, ever -- not once per plug-in. Override via cache_path= on
#    identify_port / detect_devices / auto_connect if you'd rather keep
#    this somewhere else (e.g. alongside a packaged app).
DEFAULT_CACHE_PATH = Path.home() / '.control_surfaces' / 'device_cache.json'

# ── signal 1: exact USB (vid, pid) -> device key ─────────────────────
# Fill in once you know your hardware's real values, e.g.:
#   KNOWN_USB_IDS = {(0x0403, 0x6001): TRICASTER, (0x10C4, 0xEA60): LC11}
KNOWN_USB_IDS: dict[tuple[int, int], str] = {}

# ── signal 2: case-insensitive substrings checked against each port's
#    description / manufacturer / product strings ────────────────────
KNOWN_DESCRIPTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    TRICASTER: ('tricaster',),
    LC11:      ('livecontrol', 'lc-11', 'lc11', 'newtek'),
}


@dataclass(frozen=True)
class DeviceMatch:
    """One identified device sitting on one serial port."""
    port:        str
    device_type: str   # TRICASTER | LC11
    method:      str   # 'usb_id' | 'description' | 'protocol_probe'

    def open(self, **kwargs) -> 'ControlSurface':
        """Instantiate the right surface class for this match. Doesn't
        connect -- use as a context manager or call .connect() next."""
        return _CLASS_FOR_TYPE[self.device_type](self.port, **kwargs)


class DeviceDetectionError(Exception):
    """Base class for auto-detection failures."""


class NoDeviceFoundError(DeviceDetectionError):
    """No serial port could be identified as either known device."""


class AmbiguousDeviceError(DeviceDetectionError):
    """More than one candidate port was identified; caller must
    disambiguate by passing an explicit port=."""
    def __init__(self, matches: list[DeviceMatch]) -> None:
        self.matches = matches
        ports = ', '.join(f'{m.port} ({m.device_type} via {m.method})' for m in matches)
        super().__init__(
            f"Multiple candidate devices found: {ports}. "
            f"Pass port=<one of these> to disambiguate, or use "
            f"auto_connect_all() to open every detected device at once."
        )


class UnknownDeviceError(DeviceDetectionError):
    """An explicitly-given port didn't match either known device."""


# ═══════════════════════════════════════════════════════════════════
#  Port enumeration
# ═══════════════════════════════════════════════════════════════════

def list_serial_ports():
    """
    Debug helper: return every serial port the OS currently sees, with
    whatever identifying metadata it has (vid, pid, description,
    manufacturer, product, serial_number).

    Handy for populating KNOWN_USB_IDS / KNOWN_DESCRIPTION_KEYWORDS --
    plug in one panel at a time and see what shows up::

        >>> for p in list_serial_ports():
        ...     print(p.device, hex(p.vid or 0), hex(p.pid or 0), p.description)
    """
    return list(list_ports.comports())


# ═══════════════════════════════════════════════════════════════════
#  Signals 1 & 2: USB metadata (no port I/O)
# ═══════════════════════════════════════════════════════════════════

def _match_usb_id(port_info) -> str | None:
    if port_info.vid is None or port_info.pid is None:
        return None
    return KNOWN_USB_IDS.get((port_info.vid, port_info.pid))


def _match_description(port_info) -> str | None:
    haystack = ' '.join(filter(None, (
        port_info.description, port_info.manufacturer, port_info.product,
    ))).lower()
    if not haystack:
        return None
    for device_type, keywords in KNOWN_DESCRIPTION_KEYWORDS.items():
        if any(kw in haystack for kw in keywords):
            return device_type
    return None


# ═══════════════════════════════════════════════════════════════════
#  Signal 3: learned serial-number cache (no port I/O)
# ═══════════════════════════════════════════════════════════════════

def _load_serial_cache(cache_path: Path) -> dict[str, str]:
    try:
        return json.loads(cache_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_serial_cache(cache_path: Path, cache: dict[str, str]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=2, sort_keys=True))


def _match_serial_cache(port_info, cache: dict[str, str]) -> str | None:
    if not port_info.serial_number:
        return None
    return cache.get(port_info.serial_number)


def _learn_serial(cache_path: Path, serial_number: str | None, device_type: str) -> None:
    """Record a probe result against its adapter's serial number, if it
    has one, so future plug-ins skip the probe entirely."""
    if not serial_number:
        return   # nothing stable to key on -- can't learn this one
    cache = _load_serial_cache(cache_path)
    if cache.get(serial_number) == device_type:
        return   # already known, avoid a needless disk write
    cache[serial_number] = device_type
    _save_serial_cache(cache_path, cache)


def forget_cached_devices(cache_path: Path = DEFAULT_CACHE_PATH) -> None:
    """Clear the learned serial-number cache, e.g. after swapping an
    adapter and wanting a clean re-learn rather than waiting for the
    old entry to simply age out (it won't -- stale entries are only
    ever harmless because a *different* serial just misses the cache)."""
    _save_serial_cache(cache_path, {})


# ═══════════════════════════════════════════════════════════════════
#  Signal 4: protocol probe (opens the port briefly)
# ═══════════════════════════════════════════════════════════════════
#
# Neither device has a synchronous "identify yourself" command -- both
# only speak when a control changes. So this probe listens passively
# for a short window and classifies *whatever arrives* by its wire
# shape rather than by asking a question and waiting for an answer.
# If nothing arrives (panel untouched, no ambient telemetry), the
# probe is inconclusive -- it does not guess.

_HEX_DIGITS = set('0123456789ABCDEFabcdef')


def _split_frames(raw: bytes) -> list[str]:
    """
    Split raw bytes into \\r-delimited ASCII tokens. Both protocols are
    exclusively \\r-terminated printable ASCII on the wire (TriCaster's
    '~{ch}{val:02X}\\r' is itself valid ASCII+CR), so one tokenizer
    covers both; non-ASCII noise is dropped rather than raising.
    """
    text = raw.decode('ascii', errors='ignore')
    return [t for t in (tok.strip() for tok in text.split('\r')) if t]


def _is_lc11_split_row_pair(token: str, next_token: str | None) -> bool:
    """
    The LC-11's bus-row frames (EFFECTS/LIVE/PREVIEW) are a HARDWARE
    QUIRK: 3 hex digits sent as two separate \\r-terminated writes --
    "~{F|2|1}{2 hex digits}" immediately followed by a lone trailing
    hex digit (see lc11.py's _read_messages). A TriCaster never emits
    a continuation write like this -- every one of its frames is a
    single complete 5-byte unit -- so this exact two-frame shape is an
    unambiguous LC-11 signature.
    """
    return (
        len(token) == 4 and token[0] == '~' and token[1] in ('F', '2', '1')
        and token[2] in _HEX_DIGITS and token[3] in _HEX_DIGITS
        and next_token is not None and len(next_token) == 1 and next_token in _HEX_DIGITS
    )


def _looks_like_lc11(raw: bytes) -> bool:
    """
    Positively LC-11 if either signal appears:

      - a '^'-prefixed frame -- TriCaster's protocol has no caret-
        prefixed frames at all (see tricaster.py's _send_frame, which
        only ever writes '~'), so this alone is conclusive; or
      - the split bus-row two-frame pattern above, also conclusive.

    Plain single "~{ch}{2 hex}\\r" frames (T-bar, dial telemetry, the
    ~3 action group) are deliberately NOT treated as LC-11 evidence
    here: TriCaster's T-bar/dial/misc channels produce byte-identical
    frames for the same shape (e.g. LC-11's T-bar message and
    TriCaster's ch4 message are both literally "~4XX\\r"), so on their
    own they don't distinguish anything -- see _looks_like_tricaster.
    """
    tokens = _split_frames(raw)
    for i, token in enumerate(tokens):
        if token[0] == '^':
            return True
        next_token = tokens[i + 1] if i + 1 < len(tokens) else None
        if _is_lc11_split_row_pair(token, next_token):
            return True
    return False


def _looks_like_tricaster(raw: bytes) -> bool:
    """
    Positively TriCaster if a well-formed "~{ch}{2 hex digits}\\r"
    frame appears that is NOT the first half of an LC-11 split
    bus-row pair (see _looks_like_lc11).

    Genuine limitation, not a bug: this shape is byte-identical on
    both protocols for ch in ('3','4','5','6','7') -- moving just a
    T-bar or dial can't conclusively prove either device on its own.
    The one channel that IS provably distinguishable is a ROW button
    (LIVE/NEXT column): TriCaster sends it as one complete frame,
    LC-11 as a split pair, so only one of _looks_like_tricaster /
    _looks_like_lc11 will ever fire for it. Calibrate by pressing a
    row/source button, not just moving the T-bar or a dial.
    """
    tokens = _split_frames(raw)
    for i, token in enumerate(tokens):
        if len(token) != 4 or token[0] != '~':
            continue
        if token[2] not in _HEX_DIGITS or token[3] not in _HEX_DIGITS:
            continue
        next_token = tokens[i + 1] if i + 1 < len(tokens) else None
        if _is_lc11_split_row_pair(token, next_token):
            continue   # this is LC-11's split-row first half, not TriCaster
        return True
    return False


def _probe_tricaster(port: str, listen_s: float) -> bool:
    try:
        ser = serial.Serial(port, 115200, timeout=listen_s)
    except (serial.SerialException, OSError):
        return False
    try:
        time.sleep(listen_s)
        raw = ser.read(ser.in_waiting or 1)
        return _looks_like_tricaster(raw)
    finally:
        ser.close()


def _probe_lc11(port: str, listen_s: float) -> bool:
    try:
        ser = serial.Serial(
            port=port, baudrate=9600, bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
            timeout=listen_s,
        )
    except (serial.SerialException, OSError):
        return False
    try:
        ser.write(b'\x43\x00\x00\x00')   # LC-11 wake-up sequence
        time.sleep(0.1)
        ser.reset_input_buffer()
        time.sleep(listen_s)
        raw = ser.read(ser.in_waiting or 1)
        return _looks_like_lc11(raw)
    finally:
        ser.close()


def _probe_protocol(port: str, listen_s: float = 0.4) -> str | None:
    """
    Try both known protocols against one port. Order doesn't matter --
    each probe opens/closes the port itself and only classifies bytes
    that positively match its own frame shape, so a device that stays
    silent during the window simply yields False rather than a false
    positive for the other protocol.
    """
    if _probe_tricaster(port, listen_s):
        return TRICASTER
    if _probe_lc11(port, listen_s):
        return LC11
    return None


def _probe_many(ports: list[str], listen_s: float = 0.4) -> dict[str, str | None]:
    """
    Probe several ports at once instead of one after another.

    _probe_protocol on a single port only catches a control move that
    happens to land inside *that port's* ~2*listen_s window. With
    several unidentified ports that's impractical to time by hand --
    you can't know which port is "listening" at any given moment. This
    runs one _probe_protocol call per port concurrently, so a control
    moved on any panel at any point during the whole call gets caught,
    regardless of which port it's on.
    """
    if not ports:
        return {}
    with ThreadPoolExecutor(max_workers=len(ports)) as pool:
        results = pool.map(lambda p: _probe_protocol(p, listen_s), ports)
    return dict(zip(ports, results))


# ═══════════════════════════════════════════════════════════════════
#  Public API
# ═══════════════════════════════════════════════════════════════════

def identify_port(
    port: str,
    probe_timeout: float = 0.4,
    cache_path: Path = DEFAULT_CACHE_PATH,
) -> str | None:
    """
    Identify the device on one specific serial port: USB metadata,
    then the learned serial-number cache, then (only if genuinely
    unknown) a live protocol probe -- whose result gets cached by
    serial number for next time. Returns TRICASTER, LC11, or None.
    """
    port_info = next((p for p in list_ports.comports() if p.device == port), None)

    if port_info is not None:
        matched = _match_usb_id(port_info) or _match_description(port_info)
        if matched:
            return matched
        cached = _match_serial_cache(port_info, _load_serial_cache(cache_path))
        if cached:
            return cached

    probed = _probe_protocol(port, probe_timeout)
    if probed and port_info is not None:
        _learn_serial(cache_path, port_info.serial_number, probed)
    return probed


def detect_devices(
    probe_timeout: float = 0.4,
    cache_path: Path = DEFAULT_CACHE_PATH,
) -> list[DeviceMatch]:
    """
    Scan every serial port currently visible to the OS and return a
    DeviceMatch for each one identified as TriCaster VM or LC-11.
    Ports that can't be identified by any signal are omitted.

    Checks USB metadata, then the learned serial-number cache, before
    falling back to a live protocol probe for whatever's left -- so a
    physical adapter only ever needs a control moved on it once, the
    first time it's seen. Any still-unresolved ports (e.g. both panels
    on their first-ever run) are probed *concurrently*, not one after
    another, so it's safe to have several devices connected at once:
    move a control on each panel at any point while this call is
    running and it'll be caught, regardless of which port it's on.
    Every probe success is written back to the cache.
    """
    resolved: dict[str, DeviceMatch] = {}
    unresolved: list = []   # list of port_info for ports needing a probe
    serial_cache = _load_serial_cache(cache_path)

    for port_info in list_ports.comports():
        device_type = _match_usb_id(port_info)
        method = 'usb_id'
        if device_type is None:
            device_type = _match_description(port_info)
            method = 'description'
        if device_type is None:
            device_type = _match_serial_cache(port_info, serial_cache)
            method = 'serial_cache'
        if device_type is not None:
            resolved[port_info.device] = DeviceMatch(port_info.device, device_type, method)
        else:
            unresolved.append(port_info)

    if unresolved:
        probed = _probe_many([p.device for p in unresolved], probe_timeout)
        for port_info in unresolved:
            device_type = probed.get(port_info.device)
            if device_type is not None:
                _learn_serial(cache_path, port_info.serial_number, device_type)
                resolved[port_info.device] = DeviceMatch(port_info.device, device_type, 'protocol_probe')

    # preserve OS enumeration order
    return [resolved[p.device] for p in list_ports.comports() if p.device in resolved]


def auto_connect(
    port: str | None = None,
    probe_timeout: float = 0.4,
    cache_path: Path = DEFAULT_CACHE_PATH,
    **kwargs,
) -> 'ControlSurface':
    """
    Convenience entry point: identify and instantiate the right
    surface class without the caller naming a device up front.

        surface = auto_connect()                    # scan everything
        surface = auto_connect(port='/dev/ttyUSB0')  # identify this one port
        surface = auto_connect(auto_leds=True)       # kwargs pass through

    Returns an *unconnected* surface (matching TriCasterSurface/
    LC11Surface's own constructor behaviour) -- use it as a context
    manager or call .connect() next.

    The first time a given physical adapter is seen, identifying it
    may require a control to be moved during the probe window (see
    identify_port). After that it's remembered by USB serial number
    (see cache_path, default ~/.control_surfaces/device_cache.json)
    and every later call is instant with no interaction needed.

    Raises
    ------
    UnknownDeviceError   -- an explicit port= didn't match either device.
    NoDeviceFoundError    -- port=None and nothing on the system matched.
    AmbiguousDeviceError -- port=None and more than one port matched;
                            pass port= explicitly to pick one.
    """
    if port is not None:
        device_type = identify_port(port, probe_timeout, cache_path)
        if device_type is None:
            raise UnknownDeviceError(
                f"Couldn't identify a known device on {port!r}. "
                f"If it's connected but silent (panel untouched), try "
                f"moving a control during detection, or check "
                f"list_serial_ports() and register its VID/PID or "
                f"description in detect.KNOWN_USB_IDS / "
                f"KNOWN_DESCRIPTION_KEYWORDS."
            )
        return _CLASS_FOR_TYPE[device_type](port, **kwargs)

    matches = detect_devices(probe_timeout, cache_path)
    if not matches:
        raise NoDeviceFoundError(
            "No TriCaster VM or LC-11 found on any serial port. "
            "Check the connection, or pass port=<port> explicitly if "
            "auto-detection can't see it (see list_serial_ports())."
        )
    if len(matches) > 1:
        raise AmbiguousDeviceError(matches)

    return matches[0].open(**kwargs)


def auto_connect_all(
    probe_timeout: float = 0.4,
    cache_path: Path = DEFAULT_CACHE_PATH,
    **kwargs,
) -> dict[str, 'ControlSurface']:
    """
    Identify and instantiate every known device currently connected --
    use this instead of auto_connect() whenever more than one panel
    may be plugged in at once. auto_connect() intentionally refuses to
    guess in that situation (AmbiguousDeviceError) since it can only
    hand back a single surface; this hands back all of them.

        surfaces = auto_connect_all()
        tricaster = surfaces[TRICASTER]
        lc11      = surfaces[LC11]

    Returns *unconnected* surfaces (call .connect() on each, or use
    each as a context manager) keyed by device_type. kwargs are passed
    to every surface's constructor identically; if per-device kwargs
    are needed, call detect_devices() and .open() each DeviceMatch
    yourself instead.

    Note: keyed by device_type, so this assumes at most one TriCaster
    and one LC-11 connected at a time. If you might have two of the
    *same* device type plugged in simultaneously, use detect_devices()
    directly and open() each match by port instead.

    Raises
    ------
    NoDeviceFoundError -- nothing on the system matched a known device.
    """
    matches = detect_devices(probe_timeout, cache_path)
    if not matches:
        raise NoDeviceFoundError(
            "No TriCaster VM or LC-11 found on any serial port. "
            "Check the connections, or pass port=<port> to auto_connect() "
            "if detection can't see a device (see list_serial_ports())."
        )
    return {m.device_type: m.open(**kwargs) for m in matches}


def auto_connect_hub(
    probe_timeout: float = 0.4,
    cache_path: Path = DEFAULT_CACHE_PATH,
    **kwargs,
) -> 'MultiSurface':
    """
    Identify every known device currently connected and bundle them
    into one MultiSurface -- the one-call version of
    MultiSurface(auto_connect_all()), for a macro app that wants both
    panels addressable through a single object from the start:

        with auto_connect_hub(auto_leds=True) as hub:
            @hub.on_button
            def _(event):
                print(event.device_type, event.control, event.held)
            hub.run()

    Raises
    ------
    NoDeviceFoundError -- nothing on the system matched a known device.
    """
    from .multi import MultiSurface
    return MultiSurface(auto_connect_all(probe_timeout, cache_path, **kwargs))


# Populated at the bottom to avoid a circular import at module load time
# (tricaster.py / lc11.py don't import detect.py, so this is safe, but
# keeping the surface classes' own imports first makes that ordering
# explicit rather than accidental).
from .devices.tricaster import TriCasterSurface
from .devices.lc11      import LC11Surface

_CLASS_FOR_TYPE = {
    TRICASTER: TriCasterSurface,
    LC11:      LC11Surface,
}
