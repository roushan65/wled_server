"""WLED UDP realtime protocol listener (WARLS / DRGB / DRGBW / DNRGB / DNRGBW).

Byte layouts below are taken directly from WLED's own parser
(wled00/udp.cpp, handleNotifications()):

    byte 0: protocol id (1=WARLS, 2=DRGB, 3=DRGBW, 4=DNRGB, 5=DNRGBW)
    byte 1: realtime timeout in seconds (0 cancels realtime mode immediately)

    WARLS   (from byte 2): repeating [index, R, G, B]
    DRGB    (from byte 2): repeating [R, G, B], sequential from LED 0
    DRGBW   (from byte 2): repeating [R, G, B, W], sequential from LED 0
    DNRGB   (bytes 2-3 = big-endian start index, then from byte 4): [R, G, B]...
    DNRGBW  (bytes 2-3 = big-endian start index, then from byte 4): [R, G, B, W]...

SignalRGB's WLED plugin only ever sends DNRGB, but all five are implemented
here for genuine WLED compatibility with other clients.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Tuple

from .config import ServerConfig
from .lamp_bridge import LampBridge
from .state import WledState

logger = logging.getLogger("wled_server.udp_realtime")

Color = Tuple[int, int, int]

WARLS, DRGB, DRGBW, DNRGB, DNRGBW = 1, 2, 3, 4, 5


def _average(colors: List[Color]) -> Color:
    n = len(colors)
    r = sum(c[0] for c in colors) // n
    g = sum(c[1] for c in colors) // n
    b = sum(c[2] for c in colors) // n
    return (r, g, b)


def parse_realtime_packet(data: bytes, led_count: int) -> Tuple[int, List[Tuple[int, Color]]]:
    """Parse a realtime UDP packet.

    Returns (timeout_seconds, [(led_index, (r,g,b)), ...]) restricted to
    indices within [0, led_count). Raises ValueError on anything too short
    or an unrecognized protocol id.
    """
    if len(data) < 2:
        raise ValueError("packet too short")

    protocol = data[0]
    timeout = data[1]
    pixels: List[Tuple[int, Color]] = []

    if protocol == WARLS:
        i = 2
        while i + 3 < len(data):
            idx, r, g, b = data[i], data[i + 1], data[i + 2], data[i + 3]
            if idx < led_count:
                pixels.append((idx, (r, g, b)))
            i += 4

    elif protocol == DRGB:
        i = 2
        idx = 0
        while i + 2 < len(data) and idx < led_count:
            r, g, b = data[i], data[i + 1], data[i + 2]
            pixels.append((idx, (r, g, b)))
            i += 3
            idx += 1

    elif protocol == DRGBW:
        i = 2
        idx = 0
        while i + 3 < len(data) and idx < led_count:
            r, g, b = data[i], data[i + 1], data[i + 2]
            pixels.append((idx, (r, g, b)))
            i += 4
            idx += 1

    elif protocol == DNRGB:
        if len(data) < 4:
            raise ValueError("DNRGB packet too short for start index")
        start = (data[2] << 8) | data[3]
        i = 4
        idx = start
        while i + 2 < len(data) and idx < led_count:
            r, g, b = data[i], data[i + 1], data[i + 2]
            pixels.append((idx, (r, g, b)))
            i += 3
            idx += 1

    elif protocol == DNRGBW:
        if len(data) < 4:
            raise ValueError("DNRGBW packet too short for start index")
        start = (data[2] << 8) | data[3]
        i = 4
        idx = start
        while i + 3 < len(data) and idx < led_count:
            r, g, b = data[i], data[i + 1], data[i + 2]
            pixels.append((idx, (r, g, b)))
            i += 4
            idx += 1

    else:
        raise ValueError(f"unknown realtime protocol id {protocol}")

    return timeout, pixels


class RealtimeProtocol(asyncio.DatagramProtocol):
    def __init__(self, config: ServerConfig, state: WledState, lamp: LampBridge):
        self.config = config
        self.state = state
        self.lamp = lamp
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport
        logger.info("UDP realtime listener bound on port %d", self.config.udp_port)

    def datagram_received(self, data: bytes, addr):
        try:
            timeout, pixels = parse_realtime_packet(data, self.config.led_count)
        except ValueError as e:
            logger.debug("Ignoring malformed realtime packet from %s: %s", addr, e)
            return

        if timeout == 0:
            self.state.clear_realtime()
            return

        if not pixels:
            return

        self.state.mark_realtime_packet(timeout_s=float(timeout))
        self.state.color = _average([c for _, c in pixels])
        self.lamp.send_color(self.state.color)

    def error_received(self, exc):
        logger.warning("UDP error: %s", exc)


async def create_realtime_listener(config: ServerConfig, state: WledState, lamp: LampBridge):
    loop = asyncio.get_running_loop()
    transport, _protocol = await loop.create_datagram_endpoint(
        lambda: RealtimeProtocol(config, state, lamp),
        local_addr=("0.0.0.0", config.udp_port),
    )
    return transport


async def realtime_timeout_watchdog(state: WledState, poll_interval: float = 0.5):
    """Flip ``live`` back off once a client stops sending realtime packets.

    WLED's own timeout byte is per-packet (how long to stay in realtime mode
    since *that* packet), so we track it against wall-clock time rather than
    using a single fixed timeout.
    """
    import time

    try:
        while True:
            await asyncio.sleep(poll_interval)
            if state.live and (time.monotonic() - state.last_realtime_packet) > state.last_realtime_timeout_s:
                state.clear_realtime()
    except asyncio.CancelledError:
        pass
