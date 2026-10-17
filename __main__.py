"""CLI entrypoint: ``python -m wled_server``."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from lotus_lamp.config import ConfigManager
from lotus_lamp.setup import run_setup

from wled_server.config import config_from_args
from wled_server.server import Server


def _find_lamp_config(config) -> Path | None:
    if config.lamp_config_path is not None:
        path = Path(config.lamp_config_path)
        return path if path.is_file() else None

    return next(
        (path for path in ConfigManager.DEFAULT_CONFIG_LOCATIONS if path.is_file()),
        None,
    )


def _ensure_lamp_config(config) -> bool:
    if config.dry_run:
        return True

    config_path = _find_lamp_config(config)
    if config_path is not None:
        config.lamp_config_path = config_path
        return True

    if config.lamp_config_path is not None:
        print(
            f"Lamp configuration not found: {config.lamp_config_path}\n"
            "The setup wizard will scan for nearby lamps. Save the config at that path."
        )
    else:
        print(
            "No Lotus Lamp configuration found. The setup wizard will scan for nearby lamps.\n"
            "Save the config in the current directory or your user config directory."
        )

    asyncio.run(run_setup())
    config_path = _find_lamp_config(config)
    if config_path is None:
        logging.getLogger("wled_server").error(
            "No usable lamp configuration was created; the server will not start."
        )
        return False

    config.lamp_config_path = config_path
    return True


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    config = config_from_args()
    if not _ensure_lamp_config(config):
        return

    server = Server(config)
    try:
        asyncio.run(server.run_forever())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
