"""CLI entrypoint: ``python -m wled_server``."""

from __future__ import annotations

import asyncio
import logging

from wled_server.config import config_from_args
from wled_server.server import Server


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    config = config_from_args()
    server = Server(config)
    try:
        asyncio.run(server.run_forever())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
