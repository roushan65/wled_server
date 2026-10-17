"""Bridges the WLED-like state/commands to the physical Lotus Lamp over BLE."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional, Tuple

from lotus_lamp import LotusLamp

from .config import ServerConfig

logger = logging.getLogger("wled_server.lamp_bridge")

Color = Tuple[int, int, int]


class LampBridge:
    """Owns the BLE connection and serializes/rate-limits writes to the lamp.

    Color updates are "latest value wins": a fast stream of UDP packets just
    overwrites a single pending slot, and a background task drains it at
    most every ``min_send_interval_s``, skipping sends that are too close to
    the last color actually written to hardware.
    """

    def __init__(self, config: ServerConfig):
        self.config = config
        self._lamp: Optional[LotusLamp] = None
        self._connected = False
        self._closing = False

        self._pending_color: Optional[Color] = None
        self._color_event = asyncio.Event()
        self._last_sent_color: Optional[Color] = None
        self._last_sent_at = 0.0

        self._sender_task: Optional[asyncio.Task] = None
        self._watchdog_task: Optional[asyncio.Task] = None

    @property
    def connected(self) -> bool:
        return self._connected

    async def start(self):
        if not self.config.dry_run:
            await self._connect_with_retry(attempts=1)
        self._sender_task = asyncio.create_task(self._sender_loop(), name="lamp-color-sender")
        self._watchdog_task = asyncio.create_task(self._watchdog_loop(), name="lamp-watchdog")

    async def stop(self):
        self._closing = True
        self._color_event.set()
        for task in (self._sender_task, self._watchdog_task):
            if task:
                task.cancel()
        for task in (self._sender_task, self._watchdog_task):
            if task:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if self._lamp is not None and self._connected:
            try:
                await self._lamp.disconnect()
            except Exception:
                logger.exception("Error disconnecting from lamp during shutdown")

    def _build_lamp(self) -> LotusLamp:
        kwargs = {}
        if self.config.lamp_config_path:
            kwargs["config_path"] = Path(self.config.lamp_config_path)
        if self.config.lamp_device_name:
            kwargs["device_name"] = self.config.lamp_device_name
        return LotusLamp(**kwargs)

    async def _connect_with_retry(self, attempts: int = 1) -> bool:
        """Try to (re)connect. Returns True on success."""
        if self._lamp is None:
            try:
                self._lamp = self._build_lamp()
            except ValueError as e:
                logger.warning(
                    "No Lotus Lamp configuration found (%s). Falling back to --dry-run behavior.",
                    e,
                )
                self.config.dry_run = True
                return False

        delay = 1.0
        for attempt in range(attempts):
            try:
                ok = await self._lamp.connect()
                if ok:
                    self._connected = True
                    return True
            except Exception:
                logger.exception("Error connecting to lamp")
            if attempt < attempts - 1:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)
        return False

    async def _ensure_connected(self) -> bool:
        if self.config.dry_run:
            return True
        if self._connected and self._lamp and self._lamp.client and self._lamp.client.is_connected:
            return True
        self._connected = False
        return await self._connect_with_retry(attempts=1)

    async def _watchdog_loop(self):
        """Periodically verify the BLE link is actually alive and reconnect if not."""
        try:
            while not self._closing:
                await asyncio.sleep(5.0)
                if self.config.dry_run:
                    continue
                if self._lamp and self._lamp.client and not self._lamp.client.is_connected:
                    logger.warning("Lamp connection lost, attempting to reconnect...")
                    self._connected = False
                    await self._connect_with_retry(attempts=1)
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # Color streaming
    # ------------------------------------------------------------------

    def send_color(self, color: Color):
        """Queue a color to be written to the lamp (non-blocking, latest-wins)."""
        self._pending_color = color
        self._color_event.set()

    async def _sender_loop(self):
        try:
            while not self._closing:
                await self._color_event.wait()
                self._color_event.clear()
                color = self._pending_color
                if color is None:
                    continue

                now = time.monotonic()
                elapsed = now - self._last_sent_at
                if elapsed < self.config.min_send_interval_s:
                    await asyncio.sleep(self.config.min_send_interval_s - elapsed)
                    color = self._pending_color  # take the freshest value once we wake up

                if color is None or self._should_skip(color):
                    continue

                await self._write_color(color)
                self._last_sent_color = color
                self._last_sent_at = time.monotonic()
        except asyncio.CancelledError:
            pass

    def _should_skip(self, color: Color) -> bool:
        if self._last_sent_color is None:
            return False
        dist = sum(abs(a - b) for a, b in zip(color, self._last_sent_color))
        return dist < self.config.color_delta_threshold

    async def _write_color(self, color: Color):
        r, g, b = color
        if self.config.dry_run or not await self._ensure_connected():
            logger.info("[dry-run] set_rgb(%d, %d, %d)", r, g, b)
            return
        try:
            await self._lamp.set_rgb(r, g, b)
        except Exception:
            logger.exception("Failed to send color to lamp")
            self._connected = False

    # ------------------------------------------------------------------
    # Direct passthrough commands (not rate-limited; these are infrequent)
    # ------------------------------------------------------------------

    async def set_power(self, on: bool):
        if self.config.dry_run or not await self._ensure_connected():
            logger.info("[dry-run] %s", "power_on()" if on else "power_off()")
            return
        try:
            if on:
                await self._lamp.power_on()
            else:
                await self._lamp.power_off()
        except Exception:
            logger.exception("Failed to send power command to lamp")
            self._connected = False

    async def set_brightness(self, bri_0_255: int):
        lamp_brightness = max(0, min(100, round(bri_0_255 * 100 / 255)))
        if self.config.dry_run or not await self._ensure_connected():
            logger.info("[dry-run] set_brightness(%d)", lamp_brightness)
            return
        try:
            await self._lamp.set_brightness(lamp_brightness)
        except Exception:
            logger.exception("Failed to send brightness to lamp")
            self._connected = False
