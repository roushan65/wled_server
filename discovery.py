"""mDNS advertisement so SignalRGB (and the WLED app) can auto-discover this device.

WLED itself registers two services on port 80 (wled00/wled.cpp,
initInterfaces()): "_http._tcp" and "_wled._tcp", the latter carrying a
"mac" TXT record. SignalRGB's plugin specifically browses for
"_wled._tcp.local.".
"""

from __future__ import annotations

import logging
import socket

from zeroconf import ServiceInfo
from zeroconf.asyncio import AsyncZeroconf

from wled_server.config import ServerConfig

logger = logging.getLogger("wled_server.discovery")


def _local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class Discovery:
    def __init__(self, config: ServerConfig):
        self.config = config
        self._aiozc: AsyncZeroconf | None = None
        self._services: list[ServiceInfo] = []

    async def start(self):
        self._aiozc = AsyncZeroconf()
        ip = _local_ip()
        addr_bytes = socket.inet_aton(ip)
        server = f"{self.config.hostname}.local."

        for service_type in ("_http._tcp.local.", "_wled._tcp.local."):
            name = f"{self.config.hostname}.{service_type}"
            info = ServiceInfo(
                type_=service_type,
                name=name,
                addresses=[addr_bytes],
                port=self.config.http_port,
                properties={"mac": self.config.mac},
                server=server,
            )
            await self._aiozc.async_register_service(info)
            self._services.append(info)

        logger.info("Advertising mDNS as %s (%s)", server, ip)

    async def stop(self):
        if not self._aiozc:
            return
        for info in self._services:
            await self._aiozc.async_unregister_service(info)
        await self._aiozc.async_close()
