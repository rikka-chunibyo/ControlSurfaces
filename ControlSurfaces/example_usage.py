"""
example_usage.py — ControlSurfaces library examples

Same shape works on TriCasterSurface and LC11Surface: every control
(input or output) is one flat, individually-addressable name. Swap
which class you instantiate and everything else here is unchanged.

Both panels are connected at once by their known USB serial numbers
(see TRICASTER_SERIAL / LC11_SERIAL below, set once from
identify_devices.py) -- no scanning, no protocol probing, no cache
file, just a direct lookup against whatever's plugged in right now.

Uncomment the example you want to run at the bottom of the file.
"""

import time
from serial.tools import list_ports
from control_surfaces import (
    TriCasterSurface, LC11Surface, MultiSurface,
    ButtonEvent, TBarEvent, DialEvent,
    DialTracker,
)

TRICASTER = 'tricaster'
LC11      = 'lc11'

# ─────────────────────────────────────────────────────────────────────
# Both panels' USB serial numbers -- found once with identify_devices.py
# and pasted in here. Each FTDI adapter's serial number is unique and
# permanent, so this doesn't change across reboots, reconnects, or
# which physical USB port it ends up on. No scanning, no protocol
# probing, no cache file: just look these two up against whatever's
# plugged in right now and connect directly.
# ─────────────────────────────────────────────────────────────────────
TRICASTER_SERIAL = 'FTTAH7HRA'   # <-- replace with your TriCaster's serial
LC11_SERIAL      = 'FTUE1DIBA'   # <-- replace with your LC-11's serial


def find_port_by_serial(serial_number: str) -> str | None:
    """Return the port a specific USB adapter is on right now, or None
    if nothing with that serial number is currently connected."""
    for port_info in list_ports.comports():
        if port_info.serial_number == serial_number:
            return port_info.device
    return None


def connect_devices(auto_leds: bool = True) -> MultiSurface:
    """
    Connect to whichever of the two known panels are plugged in right
    now -- one, or both. A macro app shouldn't have to know in advance
    how many panels are attached: hub.tricaster / hub.lc11 (or
    TRICASTER in hub / LC11 in hub) simply reflect whatever's actually
    connected, so macros can check before binding to a specific device.

    Raises
    ------
    RuntimeError -- neither known serial number is currently connected.
    """
    surfaces = {}

    tricaster_port = find_port_by_serial(TRICASTER_SERIAL)
    if tricaster_port:
        surfaces[TRICASTER] = TriCasterSurface(tricaster_port, auto_leds=auto_leds)
    else:
        print(f'  (TriCaster not found -- serial {TRICASTER_SERIAL!r} not connected)')

    lc11_port = find_port_by_serial(LC11_SERIAL)
    if lc11_port:
        surfaces[LC11] = LC11Surface(lc11_port, auto_leds=auto_leds)
    else:
        print(f'  (LC-11 not found -- serial {LC11_SERIAL!r} not connected)')

    if not surfaces:
        raise RuntimeError(
            "Neither panel is connected. Check TRICASTER_SERIAL / LC11_SERIAL "
            "at the top of this file against identify_devices.py's output, "
            "and make sure at least one panel is plugged in."
        )
    return MultiSurface(surfaces)


def _single_device_port(serial_number: str = TRICASTER_SERIAL) -> str:
    """
    Port for the single-device demo examples (2-5, 7) below, resolved
    from a serial number the same way connect_devices() resolves both
    panels -- so these examples work on whatever COM/tty the hardware
    actually landed on, not a hardcoded guess. For running both panels
    at once, use example 1 or 8 (connect_devices()) instead.
    """
    port = find_port_by_serial(serial_number)
    if port is None:
        raise RuntimeError(
            f"No device with serial number {serial_number!r} is connected. "
            f"This example needs it plugged in -- run identify_devices.py "
            f"if you need to re-check the serial number."
        )
    return port


# serial number for whichever class a single-device example was asked to
# use -- _single_device_port() must never silently default to the wrong
# device's serial just because a caller passed a different surface_cls.
SERIAL_FOR_CLASS = {
    TriCasterSurface: TRICASTER_SERIAL,
    LC11Surface:      LC11_SERIAL,
}


# ═══════════════════════════════════════════════════════════════════
#  EXAMPLE 1 — Connect whichever panels are plugged in, by serial number
#
#  No scanning, no protocol probing, no cache file: TRICASTER_SERIAL /
#  LC11_SERIAL above are each looked up directly against whatever's
#  plugged in right now. Works with just one panel connected or both --
#  a macro app shouldn't need to care which. Update the two constants
#  above to match your hardware (identify_devices.py prints each
#  connected panel's serial number).
# ═══════════════════════════════════════════════════════════════════

def connect_both_and_run():
    print('── Connect panels (Ctrl-C to quit) ─────────────────────')

    with connect_devices(auto_leds=True) as hub:
        connected = ', '.join(f'{dt}={s.port}' for dt, s in hub.surfaces.items())
        print(f'  connected: {connected}\n')

        @hub.on_button
        def _(event: ButtonEvent):
            print(f"  [{event.device_type:<9}] {event.control:<20} "
                  f"{'PRESS' if event.held else 'release'}")

        hub.run()


# ═══════════════════════════════════════════════════════════════════
#  EXAMPLE 2 — Auto LED interactive (simplest possible usage)
#
#  auto_leds=True wires the default behaviour automatically:
#    • Hold a control with an LED → its LED lights while held
#    • T-bar to top/bottom        → the matching endpoint LED follows
#
#  Identical on both devices -- only the class name changes.
# ═══════════════════════════════════════════════════════════════════

def auto_interactive(surface_cls=TriCasterSurface):
    print('── Auto LED interactive (Ctrl-C to quit) ─────────────')
    print('  Hold any control with an LED → it lights while pressed')
    print('  T-bar to top/bottom → endpoint LED follows\n')

    with surface_cls(_single_device_port(SERIAL_FOR_CLASS[surface_cls]), auto_leds=True) as surface:
        surface.run()


# ═══════════════════════════════════════════════════════════════════
#  EXAMPLE 3 — Manual callbacks, flat control names throughout
#
#  No rows or groups to reach through anywhere -- every control is
#  addressed directly by its own name, whichever device this is.
# ═══════════════════════════════════════════════════════════════════

def manual_interactive(surface_cls=TriCasterSurface):
    print('── Manual callback interactive (Ctrl-C to quit) ──────')
    print(f"  {'CONTROL':<20} EVENT")
    print('  ' + '─' * 40)

    with surface_cls(_single_device_port(SERIAL_FOR_CLASS[surface_cls])) as surface:

        @surface.on_button
        def _(event: ButtonEvent):
            print(f"  {event.control:<20} {'PRESS' if event.held else 'release'}")
            if not surface.controls[event.control].has_led:
                return
            if event.held:
                surface.set(event.control)
            else:
                surface.clear(event.control)

        @surface.on_tbar
        def _(event: TBarEvent):
            pos_str = f"{event.position * 100:.1f}%"
            flag = ' (TOP)' if event.at_top else ' (BOTTOM)' if event.at_bottom else ''
            print(f"  {'TBAR':<20} {pos_str + flag}")

        @surface.on_dial
        def _(event: DialEvent):
            print(f"  {event.control:<20} pos={event.value}")

        surface.run()


# ═══════════════════════════════════════════════════════════════════
#  EXAMPLE 4 — Per-control override on top of auto_leds
#
#  auto_leds handles every LED-bearing control by default. Exclude
#  just the ones you want custom behaviour for -- here, LIVE_CAM_1 on
#  a TriCaster (or LIVE_1 on an LC-11) becomes a toggle instead of a
#  momentary light -- and auto_leds keeps handling everything else
#  completely unmodified.
# ═══════════════════════════════════════════════════════════════════

def mixed_interactive(surface_cls=TriCasterSurface, toggle_control='LIVE_CAM_1'):
    print('── Mixed mode (Ctrl-C to quit) ─────────────────────────')
    print(f'  {toggle_control}: toggle (press to latch, press again to release)')
    print('  Everything else: auto LED (on while held)\n')

    with surface_cls(_single_device_port(SERIAL_FOR_CLASS[surface_cls]), auto_leds=True) as surface:
        surface.auto_leds.exclude(toggle_control)

        @surface.on(toggle_control)
        def _(event: ButtonEvent):
            if not event.held:
                return
            if surface.is_lit(toggle_control):
                surface.clear(toggle_control)
            else:
                surface.set(toggle_control)

        surface.run()


# ═══════════════════════════════════════════════════════════════════
#  EXAMPLE 5 — State inspection (no run loop needed)
# ═══════════════════════════════════════════════════════════════════

def state_snapshot(surface_cls=TriCasterSurface):
    with surface_cls(_single_device_port(SERIAL_FOR_CLASS[surface_cls])) as surface:

        # Every control is addressed by name, case-insensitively where
        # an alias is registered (e.g. 'top' for TBAR_LED_TOP).
        surface.set('TBAR_LED_TOP')
        surface.set('top')     # same control, via alias -- idempotent

        s = surface.state
        print(f"Lit:       {sorted(s.lit)}")
        print(f"Dials:     {s.dials}")
        print(f"T-bar:     {s.tbar}")
        print(f"Joysticks: {s.joysticks}")


# ═══════════════════════════════════════════════════════════════════
#  EXAMPLE 6 — Simulate without hardware
#
#  Useful for unit tests: inject fake events and watch the surface
#  react exactly as it would to real hardware.
# ═══════════════════════════════════════════════════════════════════

def simulate_without_hardware(surface_cls=TriCasterSurface, control='LIVE_CAM_1'):
    # The constructor only builds the control catalogue and callback
    # registries -- it never touches the serial port (that's connect()'s
    # job), so this genuinely never needs real hardware or a real port
    # string. auto_leds=False here since auto_leds reacts to simulated
    # presses by writing a real LED frame, which needs an actually-open
    # connection; register your own on_button callback (as below) if
    # you want to see simulated events without one.
    surface = surface_cls('SIMULATED', auto_leds=False)

    events = []
    surface.on_button(events.append)

    surface.simulate(ButtonEvent(control=control, held=True))
    print(f"events captured:    {events}")
    surface.simulate(ButtonEvent(control=control, held=False))
    print(f"events captured:    {events}")


# ═══════════════════════════════════════════════════════════════════
#  EXAMPLE 7 — Speed-controlled light show (TriCaster, LIVE/NEXT rows)
#
#  Ports Example 8 from the original tricaster_panel library over to
#  the flat naming scheme. DialTracker still handles the dial's
#  0→255→0 wraparound transparently; unbounded in both directions.
# ═══════════════════════════════════════════════════════════════════

def light_show_with_speed():
    print('── Speed-controlled light show (Ctrl-C to quit) ───────')
    print('  TRANSITION_SPEED dial → turn right to speed up,')
    print('                          turn left  to slow down.\n')

    tracker = DialTracker()
    CLICKS_PER_OCTAVE = 12
    columns = ['CAM_1', 'CAM_2', 'CAM_3', 'VGA', 'VCR', 'PIC', 'BKG', 'BLK']

    def p(base_t: float = 0.08) -> None:
        factor = 2.0 ** (tracker.position / CLICKS_PER_OCTAVE)
        time.sleep(max(0.005, base_t / factor))

    with TriCasterSurface(_single_device_port()) as surface:

        @surface.on_dial
        def _(event: DialEvent):
            if event.control != 'TRANSITION_SPEED':
                return
            delta = tracker.update(event.value)
            if delta:
                factor = 2.0 ** (tracker.position / CLICKS_PER_OCTAVE)
                print(f"  Speed: level={tracker.position:+d}  ×{factor:.2f}")

        surface.start()
        surface.all_off()

        try:
            while True:
                for n in list(range(8)) + list(range(6, -1, -1)):
                    surface.set_only(f'LIVE_{columns[n]}')
                    surface.set_only(f'NEXT_{columns[7 - n]}')
                    p(0.07)
        except KeyboardInterrupt:
            pass

    print('  Done.\n')


# ═══════════════════════════════════════════════════════════════════
#  EXAMPLE 8 — Macro app: whichever devices are connected, more
#  elaborate bindings
#
#  Same connect_devices() as Example 1 -- runs fine with one panel or
#  both. TBAR/TAKE/AUTO/etc. exist on both devices with the same name,
#  so every event carries .device_type telling a macro which physical
#  panel fired it, and hub.on(DEVICE, control, ...) binds a macro to
#  one device's control specifically. Guard device-specific bindings
#  with `if DEVICE in hub:` so the same script still runs fine if that
#  particular panel isn't plugged in today.
# ═══════════════════════════════════════════════════════════════════

def macro_app_both_devices():
    print('── Macro app (Ctrl-C to quit) ──────────────────────────')

    with connect_devices(auto_leds=True) as hub:
        connected = ', '.join(f'{dt}={s.port}' for dt, s in hub.surfaces.items())
        print(f'  connected: {connected}\n')

        # unified stream -- fires for a button on EITHER device
        @hub.on_button
        def _(event: ButtonEvent):
            print(f"  [{event.device_type:<9}] {event.control:<20} "
                  f"{'PRESS' if event.held else 'release'}")

        # a macro bound to one device specifically, disambiguating a
        # name (TAKE) that exists identically on both panels
        if TRICASTER in hub:
            @hub.on(TRICASTER, 'TAKE')
            def _(event: ButtonEvent):
                if event.held:
                    print('  >>> TriCaster TAKE macro fired (not LC-11\'s)')

        # cross-device macro: LC-11's T-bar position gates a TriCaster action
        @hub.on_tbar
        def _(event: TBarEvent):
            if event.device_type == LC11 and event.at_top and hub.tricaster:
                hub.tricaster.set_only('LIVE_BLK')

        hub.run()


def _choose_device() -> tuple[type, str]:
    """Prompt for TriCaster vs LC-11, return (surface_cls, an example
    LED-capable control name on that device) for the examples below."""
    print('  Which device?')
    print('    1. TriCaster')
    print('    2. LC-11')
    while True:
        raw = input('  Select device [1-2]: ').strip()
        if raw == '1':
            return TriCasterSurface, 'LIVE_CAM_1'
        if raw == '2':
            return LC11Surface, 'LIVE_1'
        print('  Enter 1 or 2.')


if __name__ == '__main__':

    # (name, fn, kind) -- kind controls what __main__ prompts for before
    # calling fn:
    #   'multi'          -- no device prompt; fn() already handles
    #                        whichever of both panels are connected
    #   'device'         -- prompt TriCaster/LC-11, call fn(surface_cls)
    #   'device+control' -- same, plus fn(surface_cls, example_control)
    examples = [
        ('Connect panels and run',                          connect_both_and_run,     'multi'),
        ('Auto LED interactive',                             auto_interactive,         'device'),
        ('Manual callbacks',                                 manual_interactive,       'device'),
        ('Mixed mode (toggle + auto LED)',                   mixed_interactive,        'device+control'),
        ('State snapshot',                                   state_snapshot,           'device'),
        ('Simulate without hardware',                        simulate_without_hardware,'device+control'),
        ('Light show (speed-controlled, TriCaster only)',    light_show_with_speed,    'multi'),
        ('Macro app, both devices at once',                  macro_app_both_devices,   'multi'),
    ]

    print()
    print('  ControlSurfaces — examples')
    print()
    for i, (name, _, _kind) in enumerate(examples, 1):
        print(f'  {i}.  {name}')
    print()

    choice = None
    while choice is None:
        try:
            raw = input(f'  Select example [1-{len(examples)}]: ').strip()
            n = int(raw)
            if 1 <= n <= len(examples):
                choice = n
            else:
                print(f'  Enter a number between 1 and {len(examples)}.')
        except ValueError:
            print('  Please enter a number.')
        except KeyboardInterrupt:
            print()
            raise SystemExit(0)

    print()
    _, fn, kind = examples[choice - 1]

    if kind == 'multi':
        fn()
    else:
        surface_cls, example_control = _choose_device()
        print()
        if kind == 'device':
            fn(surface_cls)
        else:   # 'device+control'
            fn(surface_cls, example_control)
