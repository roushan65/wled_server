"""Server-wide configuration for the WLED-compatible bridge."""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _random_mac() -> str:
    """Generate a locally-administered MAC, used only when no lamp address is known yet."""
    octets = [0x02] + [random.randint(0, 255) for _ in range(5)]
    return "".join(f"{o:02x}" for o in octets)


@dataclass
class ServerConfig:
    device_name: str = "Lotus Lamp"
    led_count: int = 1

    http_port: int = 80
    udp_port: int = 21324

    # Minimum time between BLE color writes, and the minimum perceptible
    # change required to bother sending one. Keeps "write without response"
    # BLE traffic from overwhelming the lamp during a fast realtime stream.
    min_send_interval_s: float = 1.0 / 30
    color_delta_threshold: int = 4

    dry_run: bool = False
    lamp_config_path: Optional[Path] = None
    lamp_device_name: Optional[str] = None

    mac: str = ""

    def __post_init__(self):
        if not self.mac:
            self.mac = _random_mac()

    @property
    def hostname(self) -> str:
        return f"wled-{self.mac[-6:]}"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wled_server",
        description="Serve a WLED-compatible HTTP/UDP endpoint backed by a Lotus Lamp.",
    )
    parser.add_argument("--name", default="Lotus Lamp", help="Device name reported to clients")
    parser.add_argument("--http-port", type=int, default=80, help="HTTP port (SignalRGB expects 80)")
    parser.add_argument("--udp-port", type=int, default=21324, help="UDP realtime port")
    parser.add_argument(
        "--lamp-config", type=Path, default=None,
        help="Path to a lotus_lamp_config.json (defaults to the library's normal search locations)",
    )
    parser.add_argument(
        "--lamp-device-name", default=None,
        help="Device name to select from the lamp config, if it has multiple devices",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Don't connect to any BLE hardware; just log what would be sent",
    )
    return parser


def config_from_args(args: Optional[list] = None) -> ServerConfig:
    parsed = build_arg_parser().parse_args(args)
    return ServerConfig(
        device_name=parsed.name,
        http_port=parsed.http_port,
        udp_port=parsed.udp_port,
        dry_run=parsed.dry_run,
        lamp_config_path=parsed.lamp_config,
        lamp_device_name=parsed.lamp_device_name,
    )
