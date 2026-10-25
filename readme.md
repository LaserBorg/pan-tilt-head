# Pan-Tilt Head

## Thingiverse

### original version by David Lung
https://www.thingiverse.com/thing:314027
https://bitbucket.org/lung/imscam/src/master/

### Arduino mod
https://www.thingiverse.com/thing:5461912


## Software

### ULN2003 driver
https://github.com/IDWizard/uln2003/blob/master/uln2003.py

### circuitpython 10 on raspberry pi pico (w)
https://circuitpython.org/board/raspberry_pi_pico/
https://circuitpython.org/libraries


### Firmware

Runs on a Raspberry Pi Pico W (CircuitPython 10), storage mounted as drive `D:`.
The head is controlled only through a REST API over Wi-Fi; there is no serial
or MQTT control.

| File | Responsibility |
| --- | --- |
| `circuitpython/stepper_driver.py` | `StepperMotor` (ULN2003) and `Button` (limit switch) |
| `circuitpython/pan_tilt.py` | per-axis settings, homing, coordinated moves |
| `circuitpython/rest_api.py` | HTTP routes: validate input and queue work |
| `circuitpython/main.py` | Wi-Fi, mDNS, HTTP server, job runner and main loop |
| `circuitpython/settings.toml` | pins, gear ratios, limits, step delays |
| `circuitpython/secrets.py` | Wi-Fi credentials; not in git, copy `secrets.py.example` and edit |
| `remote_control.py` | interactive REST client for the PC (standard library only) |

Required library in `circuitpython/lib/`: `adafruit_httpserver`.

Behavior:
- On boot both axes are homed (pan, then tilt). `GET /api/v1/state` reports
  `busy` while this runs.
- A move or home request is acknowledged immediately (`202`); the motion runs
  afterwards. The HTTP server keeps being polled while the motors step, so
  `GET /api/v1/state` and `POST /api/v1/disable` work during motion.
- Pan and tilt moves finish together.
- Only one job runs at a time; further move/home requests get `409` until the
  state reports `busy: false`.

### Coordinates (degrees)

- Pan is azimuth: 0° is the homed left-flank position; positive is clockwise
  viewed from above, negative is counterclockwise. Limits are [-90°, +135°].
- Tilt is relative to its homed zero: positive moves away from the -85° endstop,
  negative moves toward it. Limits are [-85°, +90°]. The physical up/down
  direction has not been independently verified.
- Moves use absolute logical angles and are clamped to the limits. Per-axis
  `*_reverse` settings map logical direction to motor direction without changing
  the coordinate signs.

### Homing

- Tilt seeks the lower endstop (bounded by the full range plus 10°), then moves
  to its logical zero.
- The pan switch has direction-dependent active regions near 0° and +30°; only
  the stable clockwise press at the left region defines pan zero. Starts are
  assumed within 45° of the switch and every search leg is bounded. A failed
  homing leaves the axis unhomed and is reported in `error`.

### Changing the firmware

Edit files in `circuitpython/`, then copy the changed files to `D:`.
CircuitPython reloads automatically when a file is written. Copy only changed
files; `D:` also holds board-only files such as `lib/`. `secrets.py` is
untracked: create it from `secrets.py.example` and copy it to `D:` once.

### REST API

Plain HTTP on port 8080, host `pan-tilt-head.local` (mDNS) or the Pico's IP
address. Every response is the current state:

```json
{"pan": 0.0, "tilt": 0.0, "pan_homed": true, "tilt_homed": true, "busy": false, "error": null}
```

`pan`/`tilt` are `null` until the axis is homed. `error` holds the last
failure (`"pan homing failed"`, `"stopped"`, or the reason for a `400`/`409`).

| Request | Body | Result |
| --- | --- | --- |
| `GET /api/v1/state` | - | `200` state |
| `POST /api/v1/move` | `{"pan": 30, "tilt": 50}` (either key optional, numbers) | `202`; `400` for invalid input or an unhomed axis; `409` while busy |
| `POST /api/v1/home` | `{"axis": "pan" \| "tilt" \| "both"}` (default `both`) | `202`; `400` for an invalid axis; `409` while busy |
| `POST /api/v1/disable` | - | `200`; stops motion, de-energizes the motors and unhomes both axes |

Examples (replace the address):

```sh
curl -H "Content-Type: application/json" -d '{"axis":"both"}' http://192.168.1.76:8080/api/v1/home
curl -H "Content-Type: application/json" -d '{"pan":30,"tilt":50}' http://192.168.1.76:8080/api/v1/move
curl http://192.168.1.76:8080/api/v1/state
curl -X POST http://192.168.1.76:8080/api/v1/disable
```

The server has no authentication. Keep it on a trusted local network and do not
expose or port-forward it to the internet.

### Remote control client

```sh
python remote_control.py --host 192.168.1.76
```

| Command | Action |
| --- | --- |
| `p <deg>`, `t <deg>`, `pt <p> <t>` | absolute pan / tilt / both |
| `h`, `hp`, `ht` | home both / pan / tilt |
| `d` | stop and de-energize the motors |
| `s` | state |
| `q` | quit |

After each request it prints the HTTP status and round-trip time; for moves and
homing it then polls the state until the head is idle. `--host` defaults to
`$PAN_TILT_HOST` or `pan-tilt-head.local`; use the IP address if the name is
slow to resolve.
