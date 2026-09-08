# ControlSurfaces

`control-surfaces` is an application-facing Python driver for the NewTek
TriCaster VM and LiveControl LC-11 control panels. It translates both serial
protocols into the same typed event and LED API. It intentionally does not
contain OBS-specific policy; an OBS application can own mappings and keep LEDs
synchronized with OBS state.

## Install

For development from this checkout:

```powershell
python -m pip install -e .
```

Python 3.10 or newer and `pyserial` 3.5 or newer are required.

## Application integration

Desktop applications should enable queued callbacks and reconnect support.
Call `poll()` from the GUI thread (for example with Tk's `after`) so application
code never runs on the serial reader thread.

```python
from control_surfaces import LC11Surface

surface = LC11Surface(
    "COM5",
    threadsafe=True,
    reconnect=True,
    auto_leds=False,
)

@surface.on_button
def on_button(event):
    if event.held:
        dispatch_mapping(event.control)

@surface.on_tbar
def on_tbar(event):
    set_transition_position(event.position)

@surface.on_connection
def on_connection(event):
    update_device_badge(event.status.value)

@surface.on_error
def on_error(event):
    show_device_error(event.operation, str(event.error), event.fatal)

surface.connect()
surface.start()

def service_surface():
    surface.poll()
    root.after(10, service_surface)

root.after(10, service_surface)
root.protocol("WM_DELETE_WINDOW", lambda: (surface.disconnect(), root.destroy()))
```

Use `auto_leds=False` for an OBS-style application. The application should set
LEDs from OBS's authoritative state, rather than merely mirroring whether a
physical button is held:

```python
surface.set_only([control_for_scene[current_program_scene]])
```

`MultiSurface` provides the same event model for both panels. Hub input events
contain `event.device_type` and `event.surface`; hub lifecycle and error
callbacks receive `(device_type, surface, event)`.

## Reliability behavior

- Serial parsers preserve incomplete frames across arbitrary USB read chunks
  and resynchronize after malformed input.
- User callback failures are reported through `on_error` without terminating
  the reader or skipping later callbacks.
- `reconnect=True` retries a removed device at `reconnect_interval` seconds and
  reports lifecycle changes through `on_connection`.
- Connecting and reconnecting force all physical LEDs to their off baseline.
- LED state changes are transactional: a failed serial write does not update
  the library's state snapshot.
- Events use monotonic timestamps suitable for debouncing and ordering.
- Queued continuous events are coalesced by default, preventing a paused GUI
  from replaying stale T-bar/dial positions; button edges remain lossless.
- The LC-11 requires two endpoint samples by default, suppressing isolated
  false `0%`/`100%` T-bar spikes. A lone real endpoint is released after a
  short settle delay. Set `tbar_endpoint_confirmations=1` to expose every raw
  report immediately.

## Main API

- `TriCasterSurface` / `LC11Surface`: one physical panel.
- `MultiSurface`: lifecycle and event aggregation for multiple panels.
- `detect_devices()` / `auto_connect()`: optional discovery helpers.
- `surface.controls`: flat control metadata catalogue.
- `surface.state`: immutable-style snapshot of LEDs, inputs, and connection
  status.
- `on_button`, `on_dial`, `on_tbar`, `on_joystick`, and `on(control)`:
  application input subscriptions.
- `set`, `clear`, and `set_only`: LED output control.
- `remove_callback`: detach callbacks when a view or mapping is destroyed.

## Validation

Run the hardware-independent suite with:

```powershell
python -m unittest discover -v
```

The suite exercises fragmented and malformed protocol input, endpoint spike
handling, lifecycle state, callback isolation, queued GUI dispatch, and
transactional LED state. Physical unplug/replug and every control/LED should
also be exercised on both real panel models before a live production session.
