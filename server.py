"""Orchestrates the HTTP, UDP, mDNS, and lamp-bridge components for one run."""

from __future__ import annotations

import asyncio
import logging
import signal

from aiohttp import web

from .config import ServerConfig
from .discovery import Discovery
from .http_api import build_app
from .lamp_bridge import LampBridge
from .state import WledState
from .udp_realtime import create_realtime_listener, realtime_timeout_watchdog

logger = logging.getLogger("wled_server.server")


class Server:
    def __init__(self, config: ServerConfig):
        self.config = config
        self.state = WledState()
        self.lamp = LampBridge(config)
        self.discovery = Discovery(config)

        self._runner: web.AppRunner | None = None
        self._udp_transport = None
        self._watchdog_task: asyncio.Task | None = None

    async def start(self):
        await self.lamp.start()

        app = build_app(self.config, self.state, self.lamp)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self.config.http_port)
        await site.start()
        logger.info("HTTP API listening on port %d", self.config.http_port)

        self._udp_transport = await create_realtime_listener(self.config, self.state, self.lamp)
        self._watchdog_task = asyncio.create_task(realtime_timeout_watchdog(self.state))

        await self.discovery.start()

    async def stop(self):
        logger.info("Shutting down...")
        if self._watchdog_task:
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
        await self.discovery.stop()
        if self._udp_transport:
            self._udp_transport.close()
        if self._runner:
            await self._runner.cleanup()
        await self.lamp.stop()

    async def run_forever(self):
        await self.start()
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except (NotImplementedError, AttributeError):
                pass
        try:
            await stop_event.wait()
        finally:
            await self.stop()
