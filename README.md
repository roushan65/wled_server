# WLED-compatible server for the Lotus Lamp

Makes the BLE-only [Lotus Lamp](../lotus-lamp-python) look like a [WLED](https://github.com/wled/WLED)
device on the network, so [SignalRGB](https://www.signalrgb.com/)'s built-in community WLED plugin
(and other WLED clients) can discover it and stream live colors to it.

## What it does and doesn't do

The Lotus Lamp has no individually addressable LEDs — it only supports one solid RGB
color, hardware brightness, and 213 built-in whole-strip animation modes over BLE. So
this server:

- Reports itself to clients as a **1-LED** WLED device.
- Implements WLED's UDP realtime protocols (WARLS/DRGB/DRGBW/DNRGB/DNRGBW on port 21324
  by default). Any pixel data received is averaged into a single RGB value and written
  to the lamp.
- Implements enough of the WLED JSON HTTP API (`/json`, `/json/info`, `/json/state`, ...)
  for SignalRGB to discover and recognize it, and for `on`/`bri` to work.
- Advertises itself over mDNS as `_wled._tcp.local.` (and `_http._tcp.local.`) so
  SignalRGB can auto-discover it, the same way it would discover a real WLED device.
- Does **not** map WLED "effects" to the lamp's 213 native animation modes — this is a
  pixel-streaming bridge only; effects run on the SignalRGB/PC side and the lamp just
  displays whatever color it's told.

## Setup

1. On first launch, if no `lotus_lamp_config.json` (or global Lotus Lamp config) is found,
  the server runs the setup wizard in the console to scan for nearby lamps. Keep the lamp
  powered on and nearby, then save the configuration in the current directory or the
  suggested user config directory. You can also configure it manually with the library's
  setup wizard (from the `lotus-lamp-python` directory):
   ```bash
   python -m lotus_lamp.setup
   ```
  This creates a `lotus_lamp_config.json`. The bridge server uses the library's normal
  config search path, so no separate config format is needed. When using `--lamp-config`
  with a path that does not exist, the wizard still runs; choose the custom-location option
  and enter that exact path.

2. Install dependencies:
   ```bash
   pip install -r wled_server/requirements.txt
   ```

3. Run the server. SignalRGB's control POST and its manual "add by IP" discovery
   fallback are both hardcoded to port 80, so for real use you need to bind port 80,
   which requires root on macOS/Linux:
   ```bash
   sudo python -m wled_server
   ```
   For local development without touching port 80 (SignalRGB auto-discovery and the
   manual-IP fallback won't work, but curl/UDP testing will):
   ```bash
   python -m wled_server --http-port 8080
   ```

4. No lamp nearby, or just testing the network layer? Add `--dry-run` — the server
   skips the BLE connection entirely and just logs what it would have sent.

## Building a standalone Windows executable

From the repository root, install PyInstaller and the project dependencies:

```powershell
py -m pip install pyinstaller
py -m pip install -r wled_server/requirements.txt
```

Then build from the `wled_server` directory, where `__main__.py` is located:

```powershell
cd wled_server
pyinstaller --collect-all lotus_lamp --collect-all bleak --collect-all colorsys __main__.py
```

The executable and its bundled files are written to `wled_server/dist/__main__/`.
Keep the files in that folder together when distributing or running the executable.
Build on Windows to produce a Windows executable. On first launch, the executable runs
the bundled setup wizard if no lamp configuration is found; no separate Python installation
or pre-existing `lotus_lamp_config.json` is required.

## Adding it in SignalRGB

- **Automatic**: with the server running on port 80, SignalRGB's WLED plugin should
  discover it via Bonjour/mDNS, listed under the device name you configured
  (`--name`, defaults to "Lotus Lamp").
- **Manual**: if auto-discovery doesn't pick it up, add a WLED device by IP address in
  SignalRGB's device list, pointing at the machine running this server.

## CLI options

```
--name NAME               Device name reported to clients (default: "Lotus Lamp")
--http-port PORT           HTTP port (default 80; SignalRGB expects 80)
--udp-port PORT             UDP realtime port (default 21324)
--lamp-config PATH          Path to a lotus_lamp_config.json
--lamp-device-name NAME     Device name to select if the lamp config has multiple devices
--dry-run                   Don't connect to BLE hardware; just log what would be sent
```

## Verifying it works without SignalRGB

```bash
# with the server running on --http-port 8080 --dry-run
curl -s localhost:8080/json/info
curl -s localhost:8080/json
curl -X POST -d '{"on":true,"bri":200}' localhost:8080/json/state

# craft a DNRGB realtime packet (protocol=4, timeout=2s, start index=0, one red pixel)
python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.sendto(bytes([4, 2, 0, 0, 255, 0, 0]), ('localhost', 21324))
"

# browse for the mDNS service (macOS)
dns-sd -B _wled._tcp
```

With `--dry-run`, the terminal running the server will log the color/power/brightness
calls it *would* have made to the lamp instead of touching BLE.

## Thanks

Thanks to [William Porter (@wporter82)](https://github.com/wporter82) for creating
the [lotus-lamp-python library](https://github.com/wporter82/lotus-lamp-python) that
this server uses to communicate with the Lotus Lamp.
