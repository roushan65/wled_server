"""WLED-compatible JSON HTTP API (aiohttp).

Field names and the overall /json, /json/info, /json/state shape follow
WLED's own serializer (wled00/json.cpp, serializeInfo/serializeState) as
closely as a single-color bridge device reasonably can. Only the fields
SignalRGB's plugin or a curious human actually look at are populated with
real data; everything else is a plausible, harmless stub so clients that
expect a key to exist don't choke on a KeyError.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict

from aiohttp import web

from wled_server import __version__
from wled_server.config import ServerConfig
from wled_server.lamp_bridge import LampBridge
from wled_server.state import WledState

logger = logging.getLogger("wled_server.http_api")

WLED_VERSION_STRING = "0.14.4"  # reported "ver", a real WLED release number for maximum client compatibility
START_TIME = time.monotonic()


def _state_dict(state: WledState, config: ServerConfig) -> Dict[str, Any]:
    r, g, b = state.color
    return {
        "on": state.on,
        "bri": state.bri,
        "transition": 7,
        "ps": -1,
        "pl": -1,
        "nl": {"on": False, "dur": 60, "mode": 1, "tbri": 0, "rem": -1},
        "udpn": {"send": False, "recv": True, "sgrp": 1, "rgrp": 1},
        "lor": 0,
        "mainseg": 0,
        "live": state.live,
        "seg": [
            {
                "id": 0,
                "start": 0,
                "stop": config.led_count,
                "len": config.led_count,
                "grp": 1,
                "spc": 0,
                "of": 0,
                "on": state.on,
                "frz": False,
                "bri": state.bri,
                "cct": 127,
                "col": [[r, g, b], [0, 0, 0], [0, 0, 0]],
                "fx": 0,
                "sx": 128,
                "ix": 128,
                "pal": 0,
                "sel": True,
                "rev": False,
                "mi": False,
            }
        ],
    }


def _info_dict(config: ServerConfig, state: WledState, request: web.Request) -> Dict[str, Any]:
    host = request.transport.get_extra_info("sockname")
    ip = host[0] if host else "0.0.0.0"
    return {
        "ver": WLED_VERSION_STRING,
        "vid": 2114040,
        "leds": {
            "count": config.led_count,
            "pwr": 0,
            "fps": 30,
            "maxpwr": 0,
            "maxseg": 1,
            "lc": 1,
            "rgbw": False,
            "wv": False,
            "cct": False,
        },
        "str": False,
        "name": config.device_name,
        "udpport": config.udp_port,
        "simplifiedui": False,
        "live": state.live,
        "liveseg": -1,
        "lm": "",
        "lip": "",
        "ws": -1,
        "fxcount": 1,
        "palcount": 1,
        "cpalcount": 0,
        "maps": [{"id": 0}],
        "wifi": {"bssid": "00:00:00:00:00:00", "rssi": -50, "signal": 100, "channel": 1},
        "fs": {"u": 0, "t": 0, "pmt": 0},
        "ndc": -1,
        "arch": "wled_server_python",
        "core": __version__,
        "lwip": 0,
        "freeheap": 100000,
        "uptime": int(time.monotonic() - START_TIME),
        "time": int(time.time()),
        "opt": 0,
        "brand": "WLED",
        "product": "Lotus Lamp Bridge",
        "mac": config.mac,
        "ip": ip,
    }


def build_app(config: ServerConfig, state: WledState, lamp: LampBridge) -> web.Application:
    app = web.Application()

    async def get_json(request: web.Request):
        async with state.lock:
            return web.json_response(
                {
                    "state": _state_dict(state, config),
                    "info": _info_dict(config, state, request),
                    "effects": ["Solid"],
                    "palettes": ["Default"],
                }
            )

    async def get_state(request: web.Request):
        async with state.lock:
            return web.json_response(_state_dict(state, config))

    async def get_info(request: web.Request):
        async with state.lock:
            return web.json_response(_info_dict(config, state, request))

    async def get_si(request: web.Request):
        async with state.lock:
            return web.json_response(
                {"state": _state_dict(state, config), "info": _info_dict(config, state, request)}
            )

    async def get_eff(request: web.Request):
        return web.json_response(["Solid"])

    async def get_pal(request: web.Request):
        return web.json_response(["Default"])

    async def post_state(request: web.Request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)

        async with state.lock:
            if "on" in body:
                state.on = bool(body["on"])
                await lamp.set_power(state.on)
            if "t" in body:  # WLED's toggle shortcut
                state.on = not state.on
                await lamp.set_power(state.on)
            if "bri" in body:
                state.bri = max(0, min(255, int(body["bri"])))
                await lamp.set_brightness(state.bri)
            if "live" in body:
                if not body["live"]:
                    state.clear_realtime()
            if "seg" in body and isinstance(body["seg"], list) and body["seg"]:
                seg = body["seg"][0]
                if "col" in seg and seg["col"]:
                    r, g, b = (seg["col"][0] + [0, 0, 0])[:3]
                    state.color = (int(r), int(g), int(b))
                    lamp.send_color(state.color)
                if "on" in seg:
                    state.on = bool(seg["on"])
                    await lamp.set_power(state.on)
                if "bri" in seg:
                    state.bri = max(0, min(255, int(seg["bri"])))
                    await lamp.set_brightness(state.bri)

            response = _state_dict(state, config)

        return web.json_response(response)

    app.router.add_get("/json", get_json)
    app.router.add_get("/json/", get_json)
    app.router.add_get("/json/state", get_state)
    app.router.add_get("/json/state/", get_state)
    app.router.add_get("/json/info", get_info)
    app.router.add_get("/json/info/", get_info)
    app.router.add_get("/json/si", get_si)
    app.router.add_get("/json/eff", get_eff)
    app.router.add_get("/json/pal", get_pal)
    app.router.add_post("/json/state", post_state)
    app.router.add_post("/json/state/", post_state)

    return app
