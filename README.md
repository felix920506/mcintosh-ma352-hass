# McIntosh MA352 for Home Assistant

Local-push Home Assistant integration for the **McIntosh MA352** integrated amplifier over its RS232 control port. It works with a local serial adapter or with a network serial port server.

## Features

| Entity | Description |
| --- | --- |
| Media player | Power, volume (set/step), mute, input selection (BAL 1/2, UNBAL 1–3, MM PHONO) |
| Switches | Output 1, Output 2, Equalizer, Mono, Headphone HXD\*, Meter lights, Tube lights, Display auto off |
| Numbers | Balance (−50…+50), Input trim (−6…+6 dB in 0.5 dB steps) |
| Selects | Display brightness (25–100 %), Phono capacitance\*\* (50–800 pF) |
| Binary sensors | Headphones plugged in, Passthrough (inferred, see below) |

\* Only available while headphones are plugged in. \*\* Only available while MM PHONO is the selected input.

Status changes made on the amplifier (front panel, remote, headphones) are pushed to Home Assistant instantly. A full status query every 60 s also serves as a connection keepalive. If the link is lost, the integration reconnects automatically.

Optional **maximum volume** limit (Settings → Devices & services → McIntosh MA352 → Configure). It caps volume commands sent from Home Assistant. The front panel and remote are not affected.

## Installation (HACS)

1. HACS → ⋮ → *Custom repositories* → add `https://github.com/felix920506/mcintosh-ma352-hass` as an **Integration**.
2. Install **McIntosh MA352** and restart Home Assistant.
3. Settings → Devices & services → *Add integration* → **McIntosh MA352**.

Manual install: copy `custom_components/mcintosh_ma352` into your `config/custom_components` directory.

## Connection

The MA352 uses a 3.5 mm TRS jack (Tip = TX, Ring = RX, Sleeve = GND) at 8N1, no flow control. The baud rate is set in the amplifier's setup menu (default **115200**).

When adding the integration, either choose a detected serial port or type a URL:

| Connection | Example |
| --- | --- |
| Local USB/RS232 adapter | `/dev/serial/by-id/usb-FTDI_...-if00-port0` (preferred over `/dev/ttyUSB0`, which can change) |
| Raw TCP serial server | `socket://192.168.1.50:4001` |
| RFC 2217 serial server | `rfc2217://192.168.1.50:4001` |

For a raw TCP (`socket://`) server, set the baud rate on the server itself to match the amplifier. Many serial servers accept only one TCP client at a time, so close other tools before connecting.

The port can be changed later with **Reconfigure** without losing entities.

## Protocol notes

These are observations from a unit running firmware 1.07 that differ from or add to *MA352 External Control Rev A*:

- Meter lights use command `TML`, not `TTM` as documented.
- `TDS` (undocumented) controls **Display auto off**.
- After power-on the unit is unresponsive for about 16 s while it boots. Commands sent during this time are **queued, not dropped**, and all run once boot completes. The integration therefore holds back commands until the amplifier answers a single probe, so volume steps can't pile up. This applies whether the amp was turned on from Home Assistant, the front panel or the remote.
- There is no passthrough status, and set commands are accepted in passthrough (no `ERROR - In Passthru` was observed). See *Passthrough mode*.
- Front panel/remote volume changes made during that boot window are ignored by the unit (unlike RS232 commands, which are queued).
- Power-on (from RS232, the power button or the remote) pushes a full status dump. Mute is cleared on power-on.
- Relative commands (`VOL U`, `TBA L`, …) are acknowledged with the resulting absolute value.
- Absolute volume changes ramp in 1 % steps, and **every step is pushed** (`VOL 25` at 30 → `(VOL 29)(VOL 28)…(VOL 25)`). The integration waits for the target value.
- Set commands that leave the value unchanged are **not acknowledged** for `VOL`, `TBA`, `TIN`, `TEQ`, `TMO`, `TTL`, `TML`, `TDS` and `STA` (but are for `MUT`, `INP`, `OP1`, `OP2`, `TDB`). The integration skips writes that match the known state and confirms unacknowledged ones with a query.
- In standby, `QRY` returns only product info and `(PWR 0)`. Every other command except `PWR` returns `ERROR - Invalid Command`.

## Passthrough mode

The MA352 can be switched into passthrough (power amplifier only, fixed gain), e.g. by a 12 V trigger configured by the installer. The RS232 protocol has **no passthrough status**, so the integration infers it from what the unit does (observed on FW 1.07):

- In passthrough the unit reports a fixed volume of **69 %** and ignores the knob and remote. The display shows PASSTHRU.
- Entering and leaving passthrough always pushes a single `(VOL …)` frame: a jump to 69 and back to the previous volume (or `(VOL 69)` twice if the volume already was 69).
- The knob and remote push one frame per 1 % step.

So an unsolicited volume jump to or from 69 marks a transition, and any single step proves normal mode. If Home Assistant connects or the amplifier powers on while the volume is exactly 69, the mode can't be determined. The *Passthrough* sensor then shows **unknown** until the next volume step or transition.

While passthrough is active, the media player hides its volume level and rejects volume commands. Mute and input selection remain available. RS232 volume commands sent during passthrough are accepted by the unit but have no effect: the display stays on PASSTHRU and the previous volume is restored on exit. So volume control stays available while the mode is unknown.

## Development

```bash
pip install -r requirements_test.txt
pytest
```

Tests run against an emulator of the amplifier (`tests/emulator.py`) over a local TCP socket. You can also run it standalone (`python -m tests.emulator 4001`) and point a dev Home Assistant instance at `socket://127.0.0.1:4001`.

Optional tests against real hardware (low-risk, reversible changes only; volume is never raised above its starting level):

```bash
MA352_LIVE_URL=socket://host:port pytest tests/test_live.py -s
MA352_LIVE_URL=... MA352_LIVE_POWER=1 pytest tests/test_live.py -s   # includes a power cycle
MA352_LIVE_URL=... MA352_LIVE_WATCH=120 pytest tests/test_live.py -s # log changes while you operate the amp
```
