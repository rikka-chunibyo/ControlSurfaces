# OBSControl

OBSControl is a desktop mapping app that connects NewTek LC-11 and TriCaster
control surfaces to OBS Studio through OBS WebSocket 5.

It discovers scenes, transitions, inputs, and scene sources from the running OBS
instance. A panel control can run an ordered sequence of actions, and button LEDs
can follow OBS state such as the current scene, selected transition, mute state,
Studio Mode, or connection status.

## Run from this checkout

1. In OBS, open **Tools > WebSocket Server Settings**, enable the server, and
   leave OBS running.
2. From this directory, run `python main.py`.
3. The default **Use this computer's OBS settings** option reads the local port
   and password directly from OBS. The password is not copied into OBSControl's
   saved configuration in this mode.
4. Add or edit a panel, create input mappings on **Mappings**, and configure
   independent output rules on **LED feedback**.

Configuration is saved to `%APPDATA%\OBSControl\config.json`.

## Mapping model

- A mapping selects one panel control and a trigger: press/release for buttons,
  movement for analog controls, and top/bottom/change for the T-bar.
- Each mapping contains one or more ordered OBS actions with optional delays.
- **Transition to scene (Studio Mode)** selects both the destination scene and
  transition before running it; transition duration remains independently
  configurable when needed.
- **Transition current Preview (Studio Mode)** leaves the controller-selected
  Preview scene alone, selects only the transition, and takes Preview to Program.
- `$event.position` passes the physical T-bar's normalized position to OBS.
- `$event.volume` maps an LC-11 dial's 0--255 range to an OBS input's 0.0--1.0
  volume multiplier. Map the same click-capable dial's `change` trigger to
  **Input volume**, and its `press` trigger to **Input monitoring** with
  `toggle` to get a compact volume/monitor strip.
- LED rules independently select a panel, any addressable LED, and an OBS
  condition. Multiple rules may target the same LED and are combined with OR.
- LED conditions cover scenes, transitions, input mute, source visibility,
  Studio Mode, recording, streaming, virtual camera, replay buffer, and the OBS
  connection itself. Every condition can be inverted.
- Binary actions expose a single `toggle / on / off` mode instead of separate
  action types.
- **Advanced: raw OBS request** makes new OBS WebSocket requests usable without
  waiting for a new app release.

The app reconnects to OBS and enabled panels automatically. Action failures are
shown in the activity log and do not stop the controller loop.

## Development

Install the sibling `ControlSurfaces` package and this app in editable mode,
then run the tests:

```powershell
python -m pip install -e ..\ControlSurfaces
python -m pip install -e .
$env:PYTHONPATH = "src;..\ControlSurfaces"
python -m unittest discover -s tests -v
```
