"""Shared, lock-guarded WLED-like device state."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Tuple


@dataclass
class WledState:
    """Mutable state shared between the HTTP API, UDP listener, and lamp bridge."""

    on: bool = True
    bri: int = 255  # 0-255, WLED convention
    color: Tuple[int, int, int] = (255, 255, 255)

    live: bool = False
    last_realtime_packet: float = field(default=0.0)
    last_realtime_timeout_s: float = field(default=2.0)

    def __post_init__(self):
        self._lock = asyncio.Lock()

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    def mark_realtime_packet(self, timeout_s: float = 2.0):
        self.live = True
        self.last_realtime_packet = time.monotonic()
        self.last_realtime_timeout_s = timeout_s

    def clear_realtime(self):
        self.live = False
